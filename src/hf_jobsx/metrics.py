"""Metrics pure core + the streaming substrate. (SPEC §3 metrics.py)

This is where the old jobs-dashboard was architecturally WRONG: it refetched the
entire log buffer every 2s with a timeout hack instead of streaming. Here we stream
metrics properly — metrics ARE point-in-time samples, so streaming them into a ring
buffer is the correct primitive.

Metrics SSE schema (verified, one dict/sec, never ends):
    {"cpu_usage_pct": 0, "cpu_millicores": 3500,
     "memory_used_bytes": .., "memory_total_bytes": ..,
     "rx_bps": 0, "tx_bps": 0,
     "gpus": {"<id>": {"utilization": .., "memory_used_bytes": .., "memory_total_bytes": ..}},
     "replica": ".."}

Streaming pattern mirrored from hf jobs stats (jobs.py:500-535): N threads consuming
N SSE streams, fanned into shared state. Concurrency honesty: metrics SSE never ends;
a thread blocked in socket recv() on Ctrl-C may linger. We use DAEMON threads so the
process exits safely. This is the honest version of what the old project's
consume_with_timeout pretended to fully solve.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from huggingface_hub import JobHardware

if TYPE_CHECKING:
    from huggingface_hub import JobHardwareInfo, JobInfo

_SPARK = "▁▂▃▄▅▆▇█"  # 8 buckets, older→newer left→right
_RING_MAXLEN = 48  # ~48s history at 1 sample/sec


# --------------------------------------------------------------------------- #
# Sample + parsing (pure)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Sample:
    ts: float
    cpu_pct: float
    mem_pct: float
    gpu_pct: float | None  # None if no GPUs
    net_bps: int  # rx + tx


def parse_sample(raw: dict[str, Any], *, ts: float | None = None) -> Sample:
    """Flatten a metrics SSE dict into a Sample."""
    ts = ts if ts is not None else time.time()
    mem_total = raw.get("memory_total_bytes") or 0
    mem_used = raw.get("memory_used_bytes") or 0
    mem_pct = 100.0 * mem_used / mem_total if mem_total else 0.0
    return Sample(
        ts=ts,
        cpu_pct=float(raw.get("cpu_usage_pct") or 0.0),
        mem_pct=mem_pct,
        gpu_pct=agg_gpu(raw.get("gpus") or {}),
        net_bps=int(raw.get("rx_bps") or 0) + int(raw.get("tx_bps") or 0),
    )


def agg_gpu(gpus: dict[str, Any]) -> float | None:
    """Mean utilization across GPUs (None if none)."""
    if not gpus:
        return None
    utils = [float(g.get("utilization") or 0) for g in gpus.values()]
    return sum(utils) / len(utils) if utils else None


def push(ring: deque[Sample], s: Sample, *, maxlen: int = _RING_MAXLEN) -> None:
    """Append sample to a bounded ring buffer."""
    ring.append(s)


def accrued_cost(job: JobInfo, pricing: dict[str, JobHardwareInfo]) -> float | None:
    """APPROXIMATE client-side cost: running_secs * unit_cost_usd / 60. None if unknown.

    This is NOT billing (that lives in Hub settings). Label the column '~$'.
    """
    flavor = job.flavor
    if flavor is None:
        return None
    name = flavor.value if isinstance(flavor, JobHardware) else str(flavor)
    hw = pricing.get(name)
    if not hw:
        return None
    secs = job.durations.running_secs if job.durations else None
    if not secs:
        return None
    return secs / 60.0 * hw.unit_cost_usd


def to_sparkline(ring: deque[Sample], attr: str, *, width: int = 8) -> str:
    """Render a ring-buffer attribute as a block sparkline (▁▂▃▅▇▇▇), left-padded.

    Older samples on the left, newest on the right. Scaled to the buffer's own max.
    """
    vals = [getattr(s, attr) for s in ring]
    vals = [v for v in vals if v is not None]
    if not vals:
        return " " * width
    recent = vals[-width:]
    lo, hi = min(recent), max(recent)
    if hi == lo:
        # Flat line: scale the block by ABSOLUTE value, not a fixed mid.
        # 0→▁ (visually dead), 100→█ (full), 50→▅ (mid).
        idx = (
            min(len(_SPARK) - 1, max(0, int(round(lo / 100 * (len(_SPARK) - 1))))) if lo >= 0 else 0
        )
        chars = [_SPARK[idx]] * len(recent)
    else:
        span = hi - lo
        chars = [
            _SPARK[min(len(_SPARK) - 1, max(0, int((v - lo) / span * (len(_SPARK) - 1))))]
            for v in recent
        ]
    # left-pad if fewer samples than width
    return " " * (width - len(chars)) + "".join(chars)


# --------------------------------------------------------------------------- #
# Thread-safe monitor state + fan-in
# --------------------------------------------------------------------------- #


class MonitorState:
    """Shared, locked state written by background threads, read by the renderer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.jobs: list = []  # list[JobInfo], newest first
        self.rings: dict[str, deque[Sample]] = {}
        self.tail_logs: dict[str, str] = {}
        self.pricing: dict = {}  # dict[str, JobHardwareInfo]

    def set_jobs(self, jobs: list) -> None:
        with self._lock:
            self.jobs = jobs
            for j in jobs:
                self.rings.setdefault(j.id, deque(maxlen=_RING_MAXLEN))
                self.tail_logs.setdefault(j.id, "")

    def push_sample(self, job_id: str, s: Sample) -> None:
        with self._lock:
            ring = self.rings.setdefault(job_id, deque(maxlen=_RING_MAXLEN))
            ring.append(s)

    def set_tail(self, job_id: str, line: str) -> None:
        with self._lock:
            self.tail_logs[job_id] = line

    def set_pricing(self, pricing: dict) -> None:
        with self._lock:
            self.pricing = pricing

    def snapshot(self) -> dict[str, Any]:
        """Read-only snapshot for rendering (shallow copies to avoid races)."""
        with self._lock:
            return {
                "jobs": list(self.jobs),
                "rings": {k: list(v) for k, v in self.rings.items()},
                "tail_logs": dict(self.tail_logs),
                "pricing": dict(self.pricing),
            }


class MetricsFanIn:
    """One daemon thread per job consuming fetch_metrics() SSE.

    Each thread pushes (job_id, Sample) into the shared state. Threads die naturally
    when a stream ends (terminal job) or at process exit (daemon).
    """

    def __init__(self, client, state: MonitorState) -> None:
        self._client = client
        self._state = state
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self, job_ids: list[str]) -> None:
        for jid in job_ids:
            t = threading.Thread(
                target=self._consume, args=(jid,), daemon=True, name=f"metrics-{jid[:8]}"
            )
            t.start()
            self._threads.append(t)

    def _consume(self, job_id: str) -> None:
        try:
            for raw in self._client.fetch_metrics(job_id):
                if self._stop.is_set():
                    break
                self._state.push_sample(job_id, parse_sample(raw))
        except Exception:
            pass  # stream ended (terminal) or error — thread exits quietly

    def stop(self) -> None:
        self._stop.set()
