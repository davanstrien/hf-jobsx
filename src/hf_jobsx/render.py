"""`top` dense live monitor. (SPEC §3 render.py) ⭐ the social artifact

Tufte discipline: max data-ink, no borders/chrome. One rule line top and bottom.
Direct labels. Word-sized history (sparklines).

Refresh: alternate screen buffer + clear-and-home every frame, with each line
hard-fit to terminal width (ANSI-aware) so wrapping is structurally impossible.
This is the bulletproof pattern (htop/btop/watch): no cursor-up math to get wrong.
Trade-off: no scrollback (acceptable for a live dashboard). Restored on exit.

Status glyphs (REAL JobStage members, no phantom PENDING):
    ● RUNNING(green) ○ SCHEDULING(yellow) ✕ ERROR(red) ■ CANCELED(dim)
    ✓ COMPLETED(dim) 🗑 DELETED(dim)

Sparkline coloring: green normal, yellow sustained >85%, RED when 0% while RUNNING
(the "GPU flatlined" stall signal — the hero frame of the demo gif).
"""

from __future__ import annotations

import re
import select
import shutil
import sys
import termios
import threading
import time
import tty
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from hf_jobsx.metrics import MetricsFanIn, MonitorState, accrued_cost, to_sparkline
from hf_jobsx.selectors import fmt_duration, job_name, stage_str

if TYPE_CHECKING:
    from hf_jobsx.jobs_client import JobsClient

LINE_CLEAR = "\x1b[2K"
CLEAR_SCREEN = "\x1b[2J"
HOME = "\x1b[H"  # cursor to top-left (row 1, col 1)
ALT_SCREEN_ON = "\x1b[?1049h"
ALT_SCREEN_OFF = "\x1b[?1049l"
RULE = "─"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _visible_len(s: str) -> int:
    """Display width of a string, ignoring ANSI color escapes."""
    return len(_ANSI_RE.sub("", s))


def _fit(s: str, width: int) -> str:
    """Hard-trim a line to exactly `width` display columns (ANSI-aware).

    Guarantees no line can ever exceed terminal width → no autowrap → each logical
    line is always exactly one physical row. This makes the full-screen redraw safe.
    """
    # Walk the string accumulating visible columns; stop at width.
    out: list[str] = []
    visible = 0
    i = 0
    while i < len(s):
        m = _ANSI_RE.match(s, i)
        if m:
            out.append(m.group(0))  # keep escape, costs no display columns
            i = m.end()
            continue
        if visible >= width:
            break
        out.append(s[i])
        visible += 1
        i += 1
    return "".join(out)


@contextmanager
def _cbreak():
    """Put stdin in cbreak mode (read single keystrokes, no echo, no line buffering).

    Restores original termios on exit. Used for clickthrough key handling in top.
    No-op (yields False) when stdin isn't a TTY (e.g. piped) so top still renders.
    """
    if not sys.stdin.isatty():
        yield False
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_key(timeout: float = 0.0) -> str | None:
    """Read one keystroke if available within `timeout` seconds. None if nothing.

    Lowercases letters; maps all four arrows to vim-style nav, Enter, Esc. Must be in _cbreak().
    Bare Esc (no sequence following) quits; unknown escape sequences are IGNORED (not quit).
    """
    rlist, _, _ = select.select([sys.stdin], [], [], timeout)
    if not rlist:
        return None
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        # Bare Esc (nothing following) = quit. Otherwise it's an escape sequence.
        if not select.select([sys.stdin], [], [], 0)[0]:
            return "esc"
        rest = sys.stdin.read(2)
        seq = ch + rest
        # All four arrows → nav. Unknown sequences (PgUp, Home, etc.) → ignored, not quit.
        return {"\x1b[A": "k", "\x1b[B": "j", "\x1b[C": "j", "\x1b[D": "k"}.get(seq, "ignore")
    if ch in ("\r", "\n"):
        return "enter"  # cbreak keeps ICRNL on, so Enter arrives as \n, not \r
    return ch.lower()


def _redraw(lines: list[str], rendered: int, *, width: int) -> int:
    """Full-screen in-place redraw: clear screen, home cursor, print each line.

    Robust against line-wrapping (the cause of the 'pushing up' bug): every line is
    hard-fit to `width` display columns first, so no line can wrap to a 2nd row.
    No cursor-up counting to get wrong — we always repaint from the top-left.
    Returns the new row count (= len(lines)).
    """
    n = len(lines)
    buf = [CLEAR_SCREEN, HOME]
    for i, line in enumerate(lines):
        buf.append(_fit(line, width))
        if i < n - 1:
            buf.append("\r\n")
    sys.stdout.write("".join(buf))
    sys.stdout.flush()
    return n


# ANSI colors (basic 8 — portable, no truecolor needed)
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

STAGE_GLYPH = {
    "RUNNING": f"{GREEN}●{RESET}",
    "SCHEDULING": f"{YELLOW}○{RESET}",
    "ERROR": f"{RED}✕{RESET}",
    "CANCELED": f"{DIM}■{RESET}",
    "COMPLETED": f"{DIM}✓{RESET}",
    "DELETED": f"{DIM}🗑{RESET}",
}


def _sparkline_color(latest: float | None, stage: str) -> str:
    """Color a sparkline: red if 0% while RUNNING (stall), yellow if >85%, else green."""
    if stage == "RUNNING" and (latest is None or latest <= 0.5):
        return RED
    if latest is not None and latest > 85:
        return YELLOW
    return GREEN


def _truncate(s: str, width: int) -> str:
    """Ellipsize a string to width (handles ANSI-stripped display width)."""
    if len(s) <= width:
        return s
    if width <= 1:
        return s[:width]
    return s[: width - 1] + "…"


# --------------------------------------------------------------------------- #
# Rendering (pure-ish: state snapshot → list[str] lines)
# --------------------------------------------------------------------------- #


def _cost_str(cost: float | None) -> str:
    # ~ prefix signals this is an ESTIMATE (running_secs × unit price), not billing.
    if cost is None:
        return "—"
    if cost < 0.01:
        return f"~$0.0{int(cost * 100)}"
    return f"~${cost:.2f}"


def _clean_log_line(line: str) -> str:
    """Strip ANSI + collapse whitespace from a log line for inline display."""
    import re

    line = re.sub(r"\x1b\[[0-9;]*m", "", line)  # strip ANSI color codes
    return " ".join(line.split())  # collapse whitespace/newlines


def render_lines(
    snap: dict[str, Any],
    *,
    limit: int,
    width: int,
    selected: int | None = None,
    pending_ssh: bool = False,
) -> list[str]:
    """Render the full table as a list of display lines. Caller prints + clears.

    selected: if set, the row at that index is marked with ▶ (the clickthrough cursor).
    pending_ssh: True after pressing 's' (next Enter drills into ssh instead of logs).
    """
    jobs = snap["jobs"][:limit]
    rings = snap["rings"]
    tails = snap["tail_logs"]
    pricing = snap["pricing"]
    action_hint = "ssh" if pending_ssh else "logs"  # defined before loop (footer uses it)

    n_running = sum(1 for j in snap["jobs"] if stage_str(j) == "RUNNING")
    n_error = sum(1 for j in snap["jobs"] if stage_str(j) == "ERROR")

    lines: list[str] = []
    title = f"{BOLD} HF Jobs{RESET}"
    status = f"{n_running} running" + (f" / {RED}{n_error} error{RESET}" if n_error else "")
    lines.append(f"{title}{status:>50}")
    lines.append(RULE * width)

    # Column layout (responsive): @N cpu gpu net id name st run cost | log(rest)
    # ~69 chars incl. separators before the optional cost + log columns
    fixed_no_log = 4 + 9 + 9 + 9 + 10 + 16 + 2 + 6 + 4
    fixed_with_cost = fixed_no_log + 7  # ~76
    # Drop cost column under ~96 cols so the log line gets room; under ~80 drop logs too.
    show_cost = width >= 96
    show_log = width >= 82
    log_width = max(0, width - (fixed_with_cost if show_cost else fixed_no_log)) if show_log else 0

    # Column header (dim) — labels the sparklines so 'cpu gpu net' aren't ambiguous.
    # Prefix: marker(1) + '@N'(3) + space(1) = 5 chars, matching each data row.
    header = f"     {DIM}{'cpu':^8} {'gpu':^8} {'net':^8}  {'id':<10} {'job':<16} st {'run':>5}"
    if show_cost:
        header += f" {'~cost':>6}"
    if show_log:
        header += "  last log"
    header += RESET
    lines.append(header)

    for i, job in enumerate(jobs):
        jid = job.id[:8]
        name = _truncate(job_name(job), 16)
        stage = stage_str(job)
        glyph = STAGE_GLYPH.get(stage, DIM + "·" + RESET)
        run = fmt_duration(job)
        cost = _cost_str(accrued_cost(job, pricing))

        ring = rings.get(job.id, [])
        # CPU
        cpu_spark = to_sparkline_deque(ring, "cpu_pct")
        cpu_latest = ring[-1].cpu_pct if ring else None
        cpu = f"{_sparkline_color(cpu_latest, stage)}{cpu_spark}{RESET}"
        # GPU
        gpu_latest = ring[-1].gpu_pct if ring else None
        gpu_spark = to_sparkline_deque(ring, "gpu_pct")
        gpu_color = _sparkline_color(gpu_latest, stage)
        gpu = f"{gpu_color}{gpu_spark}{RESET}" if ring else f"{DIM}{' ' * 8}{RESET}"
        # NET
        net_spark = to_sparkline_deque(ring, "net_bps")
        net = f"{GREEN}{net_spark}{RESET}" if ring else f"{DIM}{' ' * 8}{RESET}"

        cost = _cost_str(accrued_cost(job, pricing))
        cost_col = f" {cost:>6}  " if show_cost else " "
        log = _clean_log_line(tails.get(job.id, "")) if log_width > 10 else ""
        log = (
            _truncate(log, log_width)
            if log
            else (DIM + "(no logs yet)" + RESET if log_width > 10 else "")
        )

        marker = f"{BOLD}▶{RESET}" if i == selected else " "
        action_hint = "ssh" if pending_ssh else "logs"
        row = (
            f"{marker}{DIM}@{i:<2}{RESET} {cpu} {gpu} {net}  {jid:<10} "
            f"{name:<16} {glyph} {run:>5}{cost_col}{log}"
        )
        lines.append(row)

    if not jobs:
        lines.append(f" {DIM}no jobs found{RESET}")

    lines.append(RULE * width)
    hint = (
        f" {DIM}enter {action_hint}  ·  s ssh  ·  ↑/↓ or j/k move  ·  q quit   "
        f"·   hf jobsx logs -f @N to follow a job's stream{RESET}"
    )
    lines.append(hint)
    return lines


def to_sparkline_deque(ring: list, attr: str, *, width: int = 8) -> str:
    """Adapter: render a list (snapshot copy) as a sparkline."""
    from collections import deque

    return to_sparkline(deque(ring), attr, width=width)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# The run loop
# --------------------------------------------------------------------------- #


def _refresh_jobs_loop(
    client: JobsClient, state: MonitorState, stop: threading.Event, interval: float
) -> None:
    """Periodically refresh the jobs list + pricing."""
    try:
        state.set_pricing(client.hardware_pricing())
    except Exception:
        pass
    while not stop.wait(interval):
        try:
            jobs = client.list_jobs()
            state.set_jobs(jobs)
        except Exception:
            pass


def _poll_logs_loop(
    client: JobsClient, state: MonitorState, stop: threading.Event, interval: float
) -> None:
    """Periodically fetch tail logs. RUNNING every interval; ERROR once (frozen logs)."""
    fetched_terminal: set[str] = set()
    while not stop.wait(interval):
        snap_jobs = state.jobs
        active = [j for j in snap_jobs if stage_str(j) in {"RUNNING", "ERROR"}]
        for job in active:
            if stop.is_set():
                return
            # ERROR jobs: fetch once (logs are frozen), then never again.
            if stage_str(job) == "ERROR":
                if job.id in fetched_terminal:
                    continue
                fetched_terminal.add(job.id)
            try:
                lines = list(client.fetch_logs(job.id, follow=False, tail=3))
                if lines:
                    state.set_tail(job.id, lines[-1])
            except Exception:
                pass


def run_top(
    *, client: JobsClient, refresh: float = 0.75, limit: int = 12, running_only: bool = True
) -> None:
    """Frame loop: stream metrics into ring buffers + poll tail logs + render.

    running_only: hide non-running jobs (a monitor is for active work). --all shows all.
    Keys (when stdin is a TTY): j/k move, Enter → logs, s → ssh (then Enter), q/Esc quit.
    """
    state = MonitorState()
    stop = threading.Event()

    # Initial job fetch (so first frame isn't empty)
    try:
        jobs = client.list_jobs()
        state.set_jobs(jobs)
    except Exception as e:
        print(f"{RED}jobsx: failed to list jobs: {e}{RESET}", file=sys.stderr)
        return
    try:
        state.set_pricing(client.hardware_pricing())
    except Exception:
        pass

    # Start metrics fan-in for RUNNING jobs
    running_ids = [j.id for j in jobs if stage_str(j) == "RUNNING"]
    fanin = MetricsFanIn(client, state)
    if running_ids:
        fanin.start(running_ids)

    # Background refreshers
    refresher = threading.Thread(
        target=_refresh_jobs_loop,
        args=(client, state, stop, 10.0),
        daemon=True,
        name="jobs-refresher",
    )
    refresher.start()
    log_poller = threading.Thread(
        target=_poll_logs_loop, args=(client, state, stop, 2.0), daemon=True, name="log-poller"
    )
    log_poller.start()

    try:
        # Outer loop: each iteration is one monitor session. A drill returns here, so
        # the user navigates BACK to the monitor after viewing logs/ssh (back-nav).
        while True:
            drill = _monitor_session(
                client=client,
                state=state,
                fanin=fanin,
                stop=stop,
                refresh=refresh,
                limit=limit,
                running_only=running_only,
            )
            if drill is None:
                break  # user quit (q/Esc/Ctrl-C)
            # Terminal already restored by _monitor_session's finally. Run native as a
            # subprocess so when it exits we regain control and re-enter the monitor.
            _drill_subprocess(drill[0], drill[1], client=client)
    finally:
        stop.set()
        fanin.stop()
    print(f"{DIM}jobsx: stopped{RESET}")


def _monitor_session(
    *,
    client: JobsClient,
    state: MonitorState,
    fanin: MetricsFanIn,
    stop: threading.Event,
    refresh: float,
    limit: int,
    running_only: bool,
) -> list[str] | None:
    """One alt-screen monitor session. Returns ['logs'|'ssh', job_id] on drill, None on quit."""
    selected = 0
    pending_ssh = False
    rendered = 0
    interactive = False

    sys.stdout.write(f"{ALT_SCREEN_ON}\x1b[?25l")
    sys.stdout.flush()
    try:
        with _cbreak() as interactive:
            while True:
                width = shutil.get_terminal_size().columns
                snap = state.snapshot()
                if running_only:
                    snap = {**snap, "jobs": [j for j in snap["jobs"] if stage_str(j) == "RUNNING"]}
                lines = render_lines(
                    snap, limit=limit, width=width, selected=selected, pending_ssh=pending_ssh
                )
                rendered = _redraw(lines, rendered, width=width)

                if interactive:
                    key = _read_key(timeout=refresh)
                    n_displayed = min(len(snap["jobs"]), limit)
                    if key in ("q", "esc"):
                        return None
                    elif key == "j" and n_displayed:
                        selected = min(selected + 1, n_displayed - 1)
                    elif key == "k" and n_displayed:
                        selected = max(selected - 1, 0)
                    elif key == "s":
                        pending_ssh = True
                    elif key == "enter" and n_displayed:
                        job = snap["jobs"][selected]
                        return ["ssh" if pending_ssh else "logs", job.id]
                else:
                    time.sleep(refresh)

                cur_running = {j.id for j in state.jobs if stage_str(j) == "RUNNING"}
                _maybe_start_new_streams(fanin, client, state, cur_running)
    except KeyboardInterrupt:
        return None  # Ctrl-C quits the monitor
    finally:
        # GUARANTEED terminal restoration before a drill subprocess takes over the tty.
        sys.stdout.write(f"\x1b[?25h{ALT_SCREEN_OFF}")
        sys.stdout.flush()


def _drill_subprocess(action: str, job_id: str, *, client: JobsClient) -> None:
    """Run native `hf jobs <action> <id>` as a subprocess.

    Returns when the child exits (Ctrl-C on the logs, or the stream ends), so the
    monitor resumes. Swallows the parent's SIGINT that Ctrl-C also delivers to us —
    that ended the child, not a request to quit jobsx.
    """
    import subprocess

    ns = getattr(client, "namespace", None)
    argv = ["jobs", action, job_id]
    if ns:
        argv += ["--namespace", ns]
    if action == "logs":
        argv.append("-f")
    hf = shutil.which("hf")
    cmd = [hf] if hf else [sys.executable, "-m", "huggingface_hub.cli.hf"]
    try:
        subprocess.run([*cmd, *argv])
    except KeyboardInterrupt:
        pass  # child got Ctrl-C; we resume the monitor, not quit


_started: set[str] = set()
_started_lock = threading.Lock()


def _maybe_start_new_streams(fanin, client, state, cur_running: set[str]) -> None:
    """Start metric streams for running jobs we aren't yet tracking (best-effort)."""
    new = cur_running - _started
    if not new:
        return
    with _started_lock:
        to_start = [j for j in new if j not in _started]
        _started.update(to_start)
    if to_start:
        fanin.start(to_start)
