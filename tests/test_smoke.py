"""Smoke tests for the scaffold (Phase 0). Real tests land with each phase."""

import subprocess
import sys


def test_package_imports():
    import hf_jobsx

    assert hf_jobsx.__version__ == "0.1.0"


def test_help_lists_subcommands():
    """`hf-jobsx --help` exits 0 and lists all planned commands."""
    result = subprocess.run(
        [sys.executable, "-m", "hf_jobsx", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    for cmd in ["resolve", "logs", "ssh", "cancel", "inspect", "pick", "top"]:
        assert cmd in result.stdout, f"missing {cmd} in --help"


def test_stub_commands_are_honest():
    """Unimplemented commands exit non-zero with a clear message (not silent success)."""
    result = subprocess.run(
        [sys.executable, "-m", "hf_jobsx", "resolve", "@0"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "not implemented" in result.stderr.lower()
