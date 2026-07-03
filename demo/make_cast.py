#!/usr/bin/env python3
"""Generate a deterministic asciinema cast (.cast) demo for hf-jobsx.

Builds the cast directly (no PTY recording) so it's reproducible and flicker-free:
each "frame" is printed with a cursor-home reset, exactly like top's real render.
The terminal-dim, fake-data path is the same code top uses in production.

Usage:
    uv run python3 demo/make_cast.py > demo/hf-jobsx-demo.cast

Then preview:   asciinema play demo/hf-jobsx-demo.cast
Convert to gif: agg demo/hf-jobsx-demo.cast demo/hf-jobsx-demo.gif --speed 1.0
Embed in docs:  https://asciinema.org/a/<ID> (after `asciinema upload`)
"""

from __future__ import annotations

import json

from hf_jobsx.fake import _FAKE_JOB_DEFS, _fake_log, _sim_sample, fake_client
from hf_jobsx.metrics import MonitorState, parse_sample
from hf_jobsx.render import render_lines
from hf_jobsx.selectors import display_name, fmt_duration, stage_str

WIDTH = 120
ROWS = 16


class Cast:
    """Minimal asciinema v2 cast writer. Header + [time, "o", data] events."""

    def __init__(self, cols: int, rows: int):
        self.events: list[list] = []
        self.t = 0.0
        self.header = {"version": 2, "width": cols, "height": rows, "env": {"SHELL": "/bin/bash"}}

    def at(self, delay: float, data: str) -> None:
        self.t += delay
        self.events.append([round(self.t, 6), "o", data])

    def dump(self) -> str:
        out = [json.dumps(self.header)]
        for e in self.events:
            out.append(json.dumps(e))
        return "\n".join(out) + "\n"


def clear(cast: Cast) -> None:
    cast.at(0.0, "\x1b[2J\x1b[H")


def type_line(cast: Cast, text: str, *, delay: float = 0.04, hold: float = 0.6) -> None:
    """Type a command line char-by-char (the 'typed' asciinema look), then hold."""
    for ch in text:
        cast.at(delay, ch)
    cast.at(hold, "\r\n")


def show(cast: Cast, text: str, *, hold: float = 0.8) -> None:
    """Print a line of output instantly, then hold."""
    cast.at(0.0, text + "\r\n")
    cast.at(hold, "")


def build_top_state(frame: int) -> MonitorState:
    """A monitor state with `frame` samples accumulated, so sparklines fill over time."""
    c = fake_client()
    state = MonitorState()
    state.set_jobs(c.list_jobs())
    state.set_pricing(c.hardware_pricing())
    for defn in _FAKE_JOB_DEFS:
        jid, _, _, _, _, _, label, kind = defn
        if kind is None:
            continue
        for step in range(frame):
            state.push_sample(jid, parse_sample(_sim_sample(kind, step)))
        if stage_str(state.jobs[[j.id for j in state.jobs].index(jid)]) in {"RUNNING", "ERROR"}:
            state.set_tail(jid, _fake_log(kind, frame + 12))
    return state


def render_top_frame(state: MonitorState, *, selected: int, pending_ssh: bool) -> str:
    """Render one top frame as the user sees it (ANSI included)."""
    lines = render_lines(
        state.snapshot(), limit=6, width=WIDTH, selected=selected, pending_ssh=pending_ssh
    )
    # Join with \r\n, then cursor-home + clear so the next frame overwrites cleanly.
    body = "\r\n".join(lines)
    return "\x1b[H\x1b[J" + body


def main() -> None:
    cast = Cast(WIDTH, ROWS)
    clear(cast)

    # --- Scene 1: the pain point ---
    show(cast, "# The daily ritual:", hold=0.5)
    type_line(
        cast,
        "$ hf jobs logs $(hf jobs ps --json | jq -r '.[0].id') -f",
        delay=0.03,
        hold=1.0,
    )
    show(cast, "# ...every time. There has to be a better way.", hold=1.2)
    cast.at(0.3, "\r\n")
    clear(cast)

    # --- Scene 2: selectors ---
    type_line(cast, "$ hf jobsx resolve @me          # jobs, with @N indexes", hold=0.6)
    c = fake_client()
    for i, job in enumerate(c.list_jobs()):
        line = f"@{i:<3} {job.id[:8]}…  {stage_str(job):<10} {fmt_duration(job):<6}"
        show(cast, f"{line} {display_name(job)}", hold=0.12)
    cast.at(0.6, "\r\n")
    clear(cast)

    # --- Scene 3: the killer line ---
    type_line(cast, "$ hf jobsx logs -f @latest       # one command, no jq", hold=1.0)
    show(cast, "jobsx: a1b2c3d4… RUNNING  train:latest", hold=0.4)
    show(cast, "step 14021 | loss 0.0491 | lr 2e-5", hold=0.25)
    show(cast, "step 14022 | loss 0.0488 | lr 2e-5", hold=0.25)
    show(cast, "…", hold=1.0)
    cast.at(0.4, "\r\n")
    clear(cast)

    # --- Scene 4: top — the star. Animate sparklines filling in. ---
    type_line(cast, "$ HF_JOBSX_FAKE=1 hf jobsx top   # dense live monitor", hold=0.8)
    cast.at(0.2, "\r\n")

    # 18 frames, ~0.5s each: sparklines grow, selected cursor moves, a drill hint
    NFRAMES = 18
    for f in range(1, NFRAMES + 1):
        state = build_top_state(f)
        selected = (f // 4) % 4  # cursor walks down over time
        pending_ssh = f > NFRAMES // 2  # halfway, switch the action hint to ssh
        frame = render_top_frame(state, selected=selected, pending_ssh=pending_ssh)
        cast.at(0.5 if f > 1 else 0.3, frame)

    # --- Scene 5: outro ---
    cast.at(0.8, "\r\n\r\n")
    show(cast, "# sparklines (history) + inline tail-log + ~cost + clickthrough.", hold=1.6)
    show(cast, "# install:  hf extensions install davanstrien/hf-jobsx", hold=1.0)

    print(cast.dump())


if __name__ == "__main__":
    main()
