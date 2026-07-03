"""Smoke tests for packaging/dispatch. Real behavior tests live in test_selectors/test_metrics."""

import os
import subprocess
import sys
from pathlib import Path

# Guard the whole suite: a hung streaming command must fail fast, not lock pytest.
_SUBPROCESS_TIMEOUT = 15

_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _run(
    *args: str,
    timeout: float = _SUBPROCESS_TIMEOUT,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    # Typer force-enables terminal styling when GITHUB_ACTIONS is set, and NO_COLOR
    # only strips colors — bold/dim codes still land inside the strings assertions
    # grep for. Scrub the CI-detection vars so subprocess output is plain everywhere.
    merged_env = {**(env if env is not None else os.environ), "NO_COLOR": "1", "COLUMNS": "120"}
    for var in ("GITHUB_ACTIONS", "FORCE_COLOR", "CI"):
        merged_env.pop(var, None)
    return subprocess.run(
        [sys.executable, "-m", "hf_jobsx", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=merged_env,
    )


def test_package_imports():
    import hf_jobsx

    assert hf_jobsx.__version__ == "0.1.0"


def test_help_lists_subcommands():
    """`hf-jobsx --help` exits 0 and lists all commands."""
    result = _run("--help")
    assert result.returncode == 0, result.stderr
    for cmd in ["resolve", "logs", "ssh", "cancel", "inspect", "pick", "top", "run"]:
        assert cmd in result.stdout, f"missing {cmd} in --help"


def test_run_dry_run_on_bundled_cheap_example():
    """The shipped cpu-basic example resolves its header and forwards script args.

    Doubles as a drift guard: if examples/hello-jobs.py's header changes, this fails.
    """
    example = _EXAMPLES / "hello-jobs.py"
    result = _run("run", "--dry-run", str(example), "--name", "Daniel")
    assert result.returncode == 0, result.stderr
    cmd = result.stdout.strip()
    assert cmd.startswith("hf jobs uv run")
    assert "--flavor cpu-basic" in cmd
    # env values are emitted dotenv-double-quoted (native re-parses them; unquoted `#`
    # would start a comment); shlex then quotes the whole token. Assert on the payload.
    assert 'GREETING="hello from a [tool.hf-jobs] runtime header"' in cmd
    # the script + its own args are passed through verbatim
    assert str(example) in cmd
    assert "--name Daniel" in cmd
    assert "resolved runtime" in result.stderr


def test_run_dry_run_on_bundled_image_mode_example():
    """The shipped image-mode example resolves the full launch triple uv can't see."""
    example = _EXAMPLES / "image-mode-vllm.py"
    result = _run("run", "--dry-run", str(example), "in_ds", "out_ds", "--max-samples", "10")
    assert result.returncode == 0, result.stderr
    cmd = result.stdout.strip()
    assert "--image vllm/vllm-openai:unlimited-ocr" in cmd
    assert "--python /usr/bin/python3" in cmd
    assert 'PYTHONPATH="/usr/local/lib/python3.12/dist-packages"' in cmd
    assert "--secrets HF_TOKEN" in cmd
    assert "in_ds out_ds --max-samples 10" in cmd


def test_run_dry_run_override_wins():
    """An explicit flag beats the header value (image-mode example declares l4x1)."""
    example = _EXAMPLES / "image-mode-vllm.py"
    result = _run("run", "--flavor", "a100-large", "--dry-run", str(example))
    assert result.returncode == 0, result.stderr
    assert "--flavor a100-large" in result.stdout
    assert "l4x1" not in result.stdout


def test_run_dry_run_timeout_is_a_per_run_flag():
    """timeout isn't a header key, but --timeout still passes through to native (per-run)."""
    example = _EXAMPLES / "hello-jobs.py"
    result = _run("run", "--timeout", "90m", "--dry-run", str(example))
    assert result.returncode == 0, result.stderr
    assert "--timeout 90m" in result.stdout


def test_run_known_flag_after_script_goes_to_script():
    """Docker-style boundary: a jobsx-known flag AFTER the script belongs to the script.

    `-d` after the script must ride in the script's argv — the job must NOT detach.
    (Previously ignore_unknown_options + interspersed parsing hijacked it as --detach.)
    """
    example = _EXAMPLES / "hello-jobs.py"
    result = _run("run", "--dry-run", str(example), "-d")
    assert result.returncode == 0, result.stderr
    cmd = result.stdout.strip()
    assert "--detach" not in cmd
    # `-d` appears after the script path, i.e. in the script's argv
    assert cmd.index("-d", cmd.index(str(example))) > cmd.index(str(example))


def test_run_jobsx_flag_after_script_passes_verbatim():
    """`--image foo` after the script goes to the script; the header flavor still applies."""
    example = _EXAMPLES / "hello-jobs.py"
    result = _run("run", "--dry-run", str(example), "--image", "foo")
    assert result.returncode == 0, result.stderr
    cmd = result.stdout.strip()
    assert "--flavor cpu-basic" in cmd  # header still applied
    assert "--image foo" in cmd
    assert cmd.index("--image foo") > cmd.index(str(example))  # in script args, not launch flags


def test_run_unknown_flag_before_script_is_loud():
    """An unknown flag BEFORE the script is a usage error — never silently bound as
    the script path (which used to skip the real script's header without a peep)."""
    example = _EXAMPLES / "hello-jobs.py"
    result = _run("run", "--with", "numpy", str(example))
    assert result.returncode != 0
    assert "--with" in result.stderr
    assert "no [tool.hf-jobs] block" not in result.stderr
    assert "no [tool.hf-jobs] block" not in result.stdout


def test_run_bare_env_resolves_from_environment():
    """`-e KEY` (no value) copies the value from the caller's environment, like native."""
    example = _EXAMPLES / "hello-jobs.py"
    env = {**os.environ, "JOBSX_SMOKE_VAR": "hunter2"}
    result = _run("run", "-e", "JOBSX_SMOKE_VAR", "--dry-run", str(example), env=env)
    assert result.returncode == 0, result.stderr
    assert 'JOBSX_SMOKE_VAR="hunter2"' in result.stdout


def test_run_bare_env_unset_warns_and_skips():
    """`-e KEY` with KEY unset warns on stderr and skips the flag — exit 0, no death."""
    example = _EXAMPLES / "hello-jobs.py"
    env = {k: v for k, v in os.environ.items() if k != "JOBSX_SMOKE_UNSET_VAR"}
    result = _run("run", "-e", "JOBSX_SMOKE_UNSET_VAR", "--dry-run", str(example), env=env)
    assert result.returncode == 0, result.stderr
    assert "JOBSX_SMOKE_UNSET_VAR" not in result.stdout
    assert "not set in your environment" in result.stderr


def test_run_dry_run_no_header_passes_through(tmp_path):
    """A script with no [tool.hf-jobs] block still launches — just no injected flags."""
    script = tmp_path / "plain.py"
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint('hi')\n")
    result = _run("run", "--dry-run", str(script))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("hf jobs uv run")
    assert "no [tool.hf-jobs] block" in result.stderr


def test_run_bad_header_env_exits_clean(tmp_path):
    """A wrong-typed header value dies with a one-line `jobsx:` error — never a traceback."""
    script = tmp_path / "bad.py"
    script.write_text('# /// script\n# [tool.hf-jobs]\n# env = "PYTHONPATH=/x"\n# ///\n')
    result = _run("run", "--dry-run", str(script))
    assert result.returncode != 0
    assert "jobsx:" in result.stderr
    assert "`env` must be a table" in result.stderr
    assert "Traceback" not in result.stderr and "Traceback" not in result.stdout


def test_run_non_table_tool_exits_clean(tmp_path):
    """A scalar `tool` key gets the real error, not the generic 'could not read script'."""
    script = tmp_path / "scalar-tool.py"
    script.write_text('# /// script\n# tool = "x"\n# ///\n')
    result = _run("run", "--dry-run", str(script))
    assert result.returncode != 0
    assert "must be a table" in result.stderr
    assert "could not read script" not in result.stderr
    assert "Traceback" not in result.stderr


def test_pick_is_honest_stub():
    """`pick` (Phase 2, not yet implemented) exits non-zero with a clear message."""
    result = _run("pick")
    assert result.returncode != 0
    assert "not implemented" in result.stderr.lower()


def test_bad_selector_exits_clean():
    """A garbage selector exits non-zero with a message — no traceback, no hang.

    Runs in fake mode: deterministic offline/logged-out (CI has no HF token, and
    without fake mode this would hit the real jobs API when a token IS present).
    """
    result = _run("resolve", "@status=pending", env={**os.environ, "HF_JOBSX_FAKE": "1"})
    assert result.returncode != 0
    assert "unknown status" in result.stderr.lower()
