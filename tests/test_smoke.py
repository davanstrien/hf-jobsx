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
    for cmd in ["resolve", "logs", "ssh", "cancel", "inspect", "pick", "top"]:
        assert cmd in result.stdout, f"missing {cmd} in --help"


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
