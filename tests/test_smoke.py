"""Smoke tests for packaging/dispatch. Real behavior tests live in test_selectors/test_metrics."""

import subprocess
import sys

# Guard the whole suite: a hung streaming command must fail fast, not lock pytest.
_SUBPROCESS_TIMEOUT = 15


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


_SCRIPT_WITH_HEADER = """\
# /// script
# requires-python = ">=3.11"
# dependencies = ["datasets", "pillow", "tqdm", "toolz"]
#
# [tool.hf-jobs]
# image = "vllm/vllm-openai:unlimited-ocr"
# flavor = "l4x1"
# python = "/usr/bin/python3"
# env = { PYTHONPATH = "/usr/local/lib/python3.12/dist-packages" }
# secrets = ["HF_TOKEN"]
# ///
print("ocr")
"""


def test_run_dry_run_resolves_header_and_passes_through(tmp_path):
    """`run --dry-run` reads the header, builds the native command, forwards script args,
    and launches nothing (no network)."""
    script = tmp_path / "unlimited-ocr-vllm.py"
    script.write_text(_SCRIPT_WITH_HEADER)

    result = _run("run", str(script), "in_ds", "out_ds", "--max-samples", "10", "--dry-run")
    assert result.returncode == 0, result.stderr
    cmd = result.stdout.strip()
    # header runtime made it into the native command...
    assert cmd.startswith("hf jobs uv run")
    assert "--image vllm/vllm-openai:unlimited-ocr" in cmd
    assert "--flavor l4x1" in cmd
    assert "--python /usr/bin/python3" in cmd
    assert "--env PYTHONPATH=/usr/local/lib/python3.12/dist-packages" in cmd
    assert "--secrets HF_TOKEN" in cmd
    # ...and the script + its own args are passed through verbatim.
    assert "in_ds out_ds --max-samples 10" in cmd
    # the resolved runtime is echoed to stderr for the human.
    assert "resolved runtime" in result.stderr


def test_run_dry_run_override_wins(tmp_path):
    script = tmp_path / "s.py"
    script.write_text(_SCRIPT_WITH_HEADER)
    result = _run("run", str(script), "--flavor", "a100-large", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "--flavor a100-large" in result.stdout
    assert "l4x1" not in result.stdout


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
