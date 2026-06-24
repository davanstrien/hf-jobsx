"""`top` dense live monitor renderer. (SPEC §3 render.py) ⭐ the social artifact

Tufte discipline: max data-ink, no borders/chrome/alt-screen. One rule line top
and bottom. Direct labels. Word-sized history (sparklines).

Refresh: in-place via ANSI cursor-up + clear-line (copy hf jobs stats _clear_line),
NO alternate screen buffer — preserves scrollback, clean Ctrl-C, no termios raw mode.

    LINE_UP = "\\033[1A"; LINE_CLEAR = "\\x1b[2K"
    clear_lines(n): for _ in range(n): print(LINE_UP, end=LINE_CLEAR)

Status glyphs (REAL JobStage members, no phantom PENDING):
    ● RUNNING   ○ SCHEDULING   ✕ ERROR   ■ CANCELED   ✓ COMPLETED   🗑 DELETED

Sparkline coloring: green normal, yellow sustained >85%, RED when 0% while RUNNING
(the "GPU flatlined" stall signal — the hero frame of the demo gif).

Layout drops columns gracefully under width: cost first, then shrink sparklines,
status glyph + id stay last.

NOT YET IMPLEMENTED (Phase 3).
"""

from __future__ import annotations

LINE_UP = "\033[1A"
LINE_CLEAR = "\x1b[2K"


def clear_lines(n: int) -> None:
    """Move cursor up n lines and clear each (in-place refresh, no scrollback loss)."""
    for _ in range(n):
        print(LINE_UP, end=LINE_CLEAR)


def render_frame() -> None:
    """Draw the full top table. TODO Phase 3."""
    raise NotImplementedError("Phase 3")


def run_top(*, namespace: str | None, refresh: float, token: str | None) -> None:
    """Frame loop: MetricsFanIn + ring buffers + inline tail-log poll + render_frame. TODO Phase 3."""
    raise NotImplementedError("Phase 3")
