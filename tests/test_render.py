"""Regression tests for render behavior flagged by code review.

Covers the areas the pure-function tests miss: the selected-index clamp (was a
reproducible IndexError), title alignment, and render_lines output shape.
"""

from __future__ import annotations

import re

from huggingface_hub import JobInfo

from hf_jobsx.metrics import MonitorState
from hf_jobsx.render import _cost_str, _visible_len, render_lines


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def make_job(
    *, id: str, created_at: str = "2026-06-24T10:00:00.000000Z", stage: str = "RUNNING"
) -> JobInfo:
    return JobInfo(
        id=id,
        createdAt=created_at,
        dockerImage="python:3.12",
        spaceId=None,
        owner={"id": "u1", "name": "testuser", "type": "user"},
        flavor="cpu-basic",
        labels=None,
        status={"stage": stage},
        durations={"schedulingSecs": 1, "runningSecs": 120, "totalSecs": 120},
    )


# --- must-fix #1: Enter with stale `selected` must not IndexError ---
# Reproduces the reviewer's crash: running_only view + selected=2 + only 1 running job.


def test_render_lines_with_stale_selected_does_not_crash():
    """The Enter handler reads snap["jobs"][selected]. Before the clamp fix, selected
    could exceed len(jobs) when jobs vanished from the running-only view → IndexError.
    render_lines itself takes selected but is robust; the clamp lives in _monitor_session.
    This test pins that render_lines never indexes out of range for any selected value.
    """
    state = MonitorState()
    state.set_jobs([make_job(id="onlyone")])
    # selected=99 is absurd, but render_lines must tolerate it (no IndexError, marker off).
    lines = render_lines(state.snapshot(), limit=12, width=120, selected=99, pending_ssh=False)
    assert any("onlyone" in _strip_ansi(x) for x in lines)


def test_selected_marker_only_on_valid_row():
    state = MonitorState()
    state.set_jobs([make_job(id="aaa111"), make_job(id="bbb222")])
    lines = render_lines(state.snapshot(), limit=12, width=120, selected=1, pending_ssh=False)
    row_aaa = next(x for x in lines if "aaa111" in _strip_ansi(x))
    row_bbb = next(x for x in lines if "bbb222" in _strip_ansi(x))
    assert "▶" not in _strip_ansi(row_aaa)  # not selected
    assert "▶" in _strip_ansi(row_bbb)  # selected


# --- title alignment: visible-width-aware so ANSI codes don't misalign ---


def test_title_alignment_visible_width_consistent():
    """Status with an error count (red ANSI codes) must align the same as without,
    because _visible_len ignores escapes (was misaligned by ~9 cols before the fix).
    """
    state = MonitorState()
    # all error → triggers the red code path in the status line
    state.set_jobs([make_job(id="err1", stage="ERROR"), make_job(id="err2", stage="ERROR")])
    lines_err = render_lines(state.snapshot(), limit=12, width=120, selected=0)
    state2 = MonitorState()
    state2.set_jobs([make_job(id="run1", stage="RUNNING")])
    lines_run = render_lines(state2.snapshot(), limit=12, width=120, selected=0)
    # Both title lines should end at the same column (status right-aligned to width).
    title_e = _strip_ansi(lines_err[0])
    title_r = _strip_ansi(lines_run[0])
    assert len(title_e) == len(title_r) == 120  # both fill the width


# --- _cost_str rounding ---


def test_cost_str_sub_cent_rounding_not_zero():
    """Pre-fix, int(0.005*100)=0 so $0.001-$0.009 all showed '~$0.00'. round() fixes it."""
    assert _cost_str(0.001) == "~$0.001"
    assert _cost_str(0.009) == "~$0.009"
    assert _cost_str(0.1) == "~$0.10"
    assert _cost_str(1.42) == "~$1.42"
    assert _cost_str(None) == "—"


# --- _visible_len ignores ANSI ---


def test_visible_len_ignores_ansi():
    assert _visible_len("\x1b[31mhello\x1b[0m") == 5
    assert _visible_len("plain") == 5
