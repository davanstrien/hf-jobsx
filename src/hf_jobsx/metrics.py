"""Metrics pure core + the streaming substrate. (SPEC §3 metrics.py)

This module is where the old jobs-dashboard was architecturally WRONG: it refetched
the entire log buffer every 2s with a timeout hack instead of streaming. Here we
stream metrics properly — and metrics ARE point-in-time samples, so streaming them
into a ring buffer is the correct primitive, not a workaround.

Metrics SSE schema (verified, one dict/sec, never ends):
    {
      "cpu_usage_pct": 0, "cpu_millicores": 3500,
      "memory_used_bytes": .., "memory_total_bytes": ..,
      "rx_bps": 0, "tx_bps": 0,
      "gpus": {"<id>": {"utilization": .., "memory_used_bytes": .., "memory_total_bytes": ..}},
      "replica": ".."
    }

Streaming pattern to MIRROR (do not reinvent): hf jobs stats uses
ThreadPool(N) + iflatmap_unordered + KeyboardInterrupt cleanup (jobs.py:500-535,1270).

Concurrency honesty: metrics SSE never ends; a thread blocked in socket recv() on
Ctrl-C may linger. We use DAEMON threads so the process exits safely. This is the
honest version of what the old project's consume_with_timeout pretended to fully solve.

NOT YET IMPLEMENTED — pure core in Phase 3, fan-in in Phase 3.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from huggingface_hub import JobHardwareInfo, JobInfo

_SPARK = "▁▂▃▄▅▆▇█"  # 8 buckets, older→newer left→right
_RING_MAXLEN = 48


@dataclass(slots=True)
class Sample:
    ts: float
    cpu_pct: float
    mem_pct: float
    gpu_pct: float | None  # None if no GPUs
    net_bps: int  # rx + tx


def parse_sample(raw: dict[str, Any], *, ts: float | None = None) -> Sample:
    """Flatten a metrics SSE dict into a Sample. TODO Phase 3."""
    raise NotImplementedError("Phase 3")


def agg_gpu(gpus: dict[str, Any]) -> float | None:
    """Mean utilization across GPUs (None if none). TODO Phase 3."""
    raise NotImplementedError("Phase 3")


def push(ring: deque[Sample], s: Sample, *, maxlen: int = _RING_MAXLEN) -> deque[Sample]:
    """Append sample to bounded ring buffer. TODO Phase 3."""
    raise NotImplementedError("Phase 3")


def accrued_cost(job: JobInfo, pricing: dict[str, JobHardwareInfo]) -> float | None:
    """APPROXIMATE client-side cost: running_secs * unit_cost_usd / 60. None if unknown.

    This is NOT billing (that lives in Hub settings). Label the column '~$'.
    TODO Phase 3.
    """
    raise NotImplementedError("Phase 3")


def to_sparkline(ring: deque[Sample], attr: str, *, width: int = 8) -> str:
    """Render a ring-buffer attribute as block sparkline (▁▂▃▅▇▇▇). TODO Phase 3."""
    raise NotImplementedError("Phase 3")


class MetricsFanIn:
    """One daemon thread per job consuming fetch_metrics(). Pushes (job_id, Sample)
    onto a thread-safe queue; main thread drains on the render frame clock.

    Reference: jobs.py iflatmap_unordered. TODO Phase 3.
    """

    def start(self, job_ids: list[str]) -> None:
        raise NotImplementedError("Phase 3")

    def stop(self) -> None:
        """Signal stop-flag + best-effort join(0.5). Daemon threads make lingering safe."""
        raise NotImplementedError("Phase 3")

    def samples(self):  # Iterator[tuple[str, Sample]]
        raise NotImplementedError("Phase 3")
