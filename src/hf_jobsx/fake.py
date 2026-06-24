"""Deterministic fake data generator. (SPEC §3 fake.py) — ESSENTIAL.

HF_JOBSX_FAKE=1 swaps JobsClient for a fake: a fixed roster of jobs (mix RUNNING/
SCHEDULING/ERROR/COMPLETED) + a metrics simulator with realistic shapes (one climbing,
one flatlined GPU = the OOM hero, one ramping, one idle) + ticking fake log lines.

Deterministic seed so the demo gif is reproducible. Lets you develop `top` and take
screenshots WITHOUT burning GPU compute. The fake metrics generators sleep between
yields (like real SSE) so the monitor animates live.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from huggingface_hub import JobInfo

FAKE_ENV = "HF_JOBSX_FAKE"

# Fixed job roster for a compelling demo. Names/stages chosen to exercise every glyph.
_FAKE_JOB_DEFS = [
    # (id, stage, flavor, image, created_ago_min, running_secs, label, sim_kind)
    ("a1b2c3d4e5f6", "RUNNING", "a10g-small", "train:latest", 134, 8064, "baseline", "gpu_steady"),
    ("b2c3d4e5f6a1", "RUNNING", "a10g-large", "train:latest", 302, 18000, "big-train", "gpu_high"),
    ("c3d4e5f6a1b2", "SCHEDULING", "cpu-basic", "eval:latest", 0, None, "eval", None),
    ("d4e5f6a1b2c3", "ERROR", "a10g-small", "distill:latest", 90, 5400, "distill", "gpu_oom"),
    ("e5f6a1b2c3d4", "COMPLETED", "cpu-basic", "cleanup:latest", 200, 120, "cleanup", None),
    ("f6a1b2c3d4e5", "RUNNING", "l4x1", "finetune:latest", 12, 720, "finetune", "cpu_heavy"),
]


def is_fake_enabled() -> bool:
    import os

    return os.environ.get(FAKE_ENV, "").lower() in {"1", "true", "yes"}


def _fake_job(defn: tuple, *, now: datetime) -> JobInfo:
    jid, stage, flavor, image, ago_min, running_secs, label, _ = defn
    created = now - timedelta(minutes=ago_min)
    # parse_datetime expects the '...Z' suffix format
    created_str = created.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return JobInfo(
        id=jid,
        createdAt=created_str,
        dockerImage=image,
        spaceId=None,
        owner={"id": "u1", "name": "demo", "type": "user"},
        flavor=flavor,
        labels={"exp": label},
        status={"stage": stage},
        durations={
            "schedulingSecs": 3,
            "runningSecs": running_secs,
            "totalSecs": running_secs or 0,
        },
    )


def _sim_sample(kind: str, step: int) -> dict[str, Any]:
    """Generate a fake metrics dict for a given sim kind and step counter."""
    if kind == "gpu_steady":
        cpu = 45 + 15 * math.sin(step * 0.3)
        gpu = 68 + 8 * math.sin(step * 0.2)
    elif kind == "gpu_high":
        cpu = 80 + 10 * math.sin(step * 0.25)
        gpu = 92 + 4 * math.sin(step * 0.15)
    elif kind == "cpu_heavy":
        cpu = 88 + 6 * math.sin(step * 0.4)
        gpu = 5.0
    else:  # gpu_oom — was high, now flatlined at 0 (the hero: red sparkline)
        cpu = 12.0
        gpu = 0.0
    return {
        "cpu_usage_pct": round(max(0, cpu), 1),
        "cpu_millicores": int(max(0, cpu) * 25),
        "memory_used_bytes": int(8e9 + 2e9 * math.sin(step * 0.1)),
        "memory_total_bytes": 16_000_000_000,
        "rx_bps": int(1e6 * (0.5 + 0.5 * math.sin(step * 0.2))) if kind != "gpu_oom" else 0,
        "tx_bps": int(5e5 * (0.5 + 0.5 * math.cos(step * 0.2))) if kind != "gpu_oom" else 0,
        "gpus": {
            "gpu0": {
                "utilization": round(gpu, 1),
                "memory_used_bytes": int(15e9),
                "memory_total_bytes": 24e9,
            }
        },
    }


def _fake_log(kind: str, step: int) -> str:
    if kind == "gpu_oom":
        return "RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB"
    if kind == "cpu_heavy":
        return f"step {step:05d}/50000 | loss {0.3 * math.exp(-step * 0.001):.4f} | acc 0.89"
    if kind == "gpu_steady":
        loss = 0.2 * math.exp(-(14000 + step) * 0.0001)
        return f"step {14000 + step:05d}/50000 | loss {loss:.4f} | lr 2e-5"
    if kind == "gpu_high":
        loss = 0.094 + 0.001 * math.sin(step)
        return f"step {31000 + step:05d}/100000 | loss {loss:.4f} | grad_norm 0.42"
    return "waiting for scheduler..."


class FakeJobsClient:
    """Drop-in replacement for JobsClient with simulated data + live streams."""

    namespace = "demo"

    def __init__(self, token: str | None = None, namespace: str | None = None) -> None:
        self._token = token
        self._namespace = namespace or "demo"
        self._now = datetime.now(timezone.utc)
        self._rng = random.Random(42)

    def list_jobs(self) -> list[JobInfo]:
        return [_fake_job(d, now=self._now) for d in _FAKE_JOB_DEFS]

    def get_job(self, job_id: str) -> JobInfo:
        for d in _FAKE_JOB_DEFS:
            if d[0] == job_id:
                return _fake_job(d, now=self._now)
        raise KeyError(job_id)

    def hardware_pricing(self) -> dict:
        from huggingface_hub import JobHardwareInfo

        def hw(name: str, cost_usd: float) -> JobHardwareInfo:
            return JobHardwareInfo(
                name=name,
                prettyName=name,
                cpu="4 vCPU",
                ram="16 GB",
                ephemeralStorage="20 GB",
                accelerator=None,
                unitCostMicroUSD=int(cost_usd * 1e6),
                unitCostUSD=cost_usd,
                unitLabel="minute",
            )

        return {
            h.name: h
            for h in [
                hw("cpu-basic", 0.000167),
                hw("a10g-small", 0.00105),
                hw("a10g-large", 0.0021),
                hw("l4x1", 0.0008),
            ]
        }

    def fetch_metrics(self, job_id: str) -> Iterable[dict[str, Any]]:
        kind = next((d[7] for d in _FAKE_JOB_DEFS if d[0] == job_id and d[7]), None)
        if kind is None:  # not a sim job → nothing to stream
            return
        return self._metrics_gen(job_id, kind)

    def _metrics_gen(self, job_id: str, kind: str) -> Iterable[dict[str, Any]]:
        step = 0
        while True:
            yield _sim_sample(kind, step)
            step += 1
            time.sleep(1.0)

    def fetch_logs(self, job_id: str, *, follow: bool, tail: int | None = None) -> Iterable[str]:
        kind = next((d[7] for d in _FAKE_JOB_DEFS if d[0] == job_id and d[7]), None)
        if kind is None:
            return []
        step = self._rng.randint(0, 50)
        lines = [_fake_log(kind, step + i) for i in range(max(1, tail or 1))]
        return lines


def fake_client(*, token: str | None = None, namespace: str | None = None) -> FakeJobsClient:
    return FakeJobsClient(token=token, namespace=namespace)
