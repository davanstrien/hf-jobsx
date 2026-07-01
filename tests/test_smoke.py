"""Smoke tests for packaging/dispatch. Real behavior tests live in test_selectors/test_metrics."""

import subprocess
import sys
from pathlib import Path

# Guard the whole suite: a hung streaming command must fail fast, not lock pytest.
_SUBPROCESS_TIMEOUT = 15

_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _run(*args: str, timeout: float = _SUBPROCESS_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "hf_jobsx", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
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
    result = _run("run", str(example), "--name", "Daniel", "--dry-run")
    assert result.returncode == 0, result.stderr
    cmd = result.stdout.strip()
    assert cmd.startswith("hf jobs uv run")
    assert "--flavor cpu-basic" in cmd
    # env value has spaces -> shlex quotes the whole KEY=VALUE token; assert on the payload
    assert "GREETING=hello from a [tool.hf-jobs] runtime header" in cmd
    # the script + its own args are passed through verbatim
    assert str(example) in cmd
    assert "--name Daniel" in cmd
    assert "resolved runtime" in result.stderr


def test_run_dry_run_on_bundled_image_mode_example():
    """The shipped image-mode example resolves the full launch triple uv can't see."""
    example = _EXAMPLES / "image-mode-vllm.py"
    result = _run("run", str(example), "in_ds", "out_ds", "--max-samples", "10", "--dry-run")
    assert result.returncode == 0, result.stderr
    cmd = result.stdout.strip()
    assert "--image vllm/vllm-openai:unlimited-ocr" in cmd
    assert "--python /usr/bin/python3" in cmd
    assert "--env PYTHONPATH=/usr/local/lib/python3.12/dist-packages" in cmd
    assert "--secrets HF_TOKEN" in cmd
    assert "in_ds out_ds --max-samples 10" in cmd


def test_run_dry_run_override_wins():
    """An explicit flag beats the header value (image-mode example declares l4x1)."""
    example = _EXAMPLES / "image-mode-vllm.py"
    result = _run("run", str(example), "--flavor", "a100-large", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "--flavor a100-large" in result.stdout
    assert "l4x1" not in result.stdout


def test_run_dry_run_timeout_is_a_per_run_flag():
    """timeout isn't a header key, but --timeout still passes through to native (per-run)."""
    example = _EXAMPLES / "hello-jobs.py"
    result = _run("run", str(example), "--timeout", "90m", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "--timeout 90m" in result.stdout


def test_run_dry_run_no_header_passes_through(tmp_path):
    """A script with no [tool.hf-jobs] block still launches — just no injected flags."""
    script = tmp_path / "plain.py"
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint('hi')\n")
    result = _run("run", str(script), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("hf jobs uv run")
    assert "no [tool.hf-jobs] block" in result.stderr


def test_pick_is_honest_stub():
    """`pick` (Phase 2, not yet implemented) exits non-zero with a clear message."""
    result = _run("pick")
    assert result.returncode != 0
    assert "not implemented" in result.stderr.lower()


def test_bad_selector_exits_clean():
    """A garbage selector exits non-zero with a message — no traceback, no hang."""
    result = _run("resolve", "@status=pending")
    assert result.returncode != 0
    assert "unknown status" in result.stderr.lower()
