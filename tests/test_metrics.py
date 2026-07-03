"""Tests for metrics.py pure core. (rendered/loop behavior is manual/integration.)"""

from __future__ import annotations

from collections import deque

import pytest
from huggingface_hub import JobHardware, JobInfo

from hf_jobsx.metrics import (
    MonitorState,
    Sample,
    accrued_cost,
    agg_gpu,
    parse_sample,
    push,
    to_sparkline,
)


def make_job(*, flavor="cpu-basic", running_secs=120) -> JobInfo:
    return JobInfo(
        id="abc123def456",
        createdAt="2026-06-24T10:00:00.000000Z",
        dockerImage="python:3.12",
        spaceId=None,
        owner={"id": "u1", "name": "testuser", "type": "user"},
        flavor=flavor,
        labels=None,
        status={"stage": "RUNNING"},
        durations={"schedulingSecs": 1, "runningSecs": running_secs, "totalSecs": running_secs},
    )


# --- parse_sample / agg_gpu ---


def test_parse_sample_basic():
    raw = {
        "cpu_usage_pct": 42.5,
        "cpu_millicores": 2100,
        "memory_used_bytes": 8_000_000_000,
        "memory_total_bytes": 16_000_000_000,
        "rx_bps": 1_000_000,
        "tx_bps": 500_000,
        "gpus": {"g0": {"utilization": 70.0, "memory_used_bytes": 1, "memory_total_bytes": 2}},
    }
    s = parse_sample(raw, ts=1000.0)
    assert s.ts == 1000.0
    assert s.cpu_pct == 42.5
    assert s.mem_pct == 50.0
    assert s.gpu_pct == 70.0
    assert s.net_bps == 1_500_000


def test_parse_sample_no_gpus():
    s = parse_sample(
        {"cpu_usage_pct": 0, "memory_used_bytes": 0, "memory_total_bytes": 0, "gpus": {}}
    )
    assert s.gpu_pct is None
    assert s.mem_pct == 0.0


def test_parse_sample_missing_fields_safe():
    s = parse_sample({})
    assert s.cpu_pct == 0.0
    assert s.net_bps == 0


def test_agg_gpu_mean():
    assert agg_gpu({"a": {"utilization": 40}, "b": {"utilization": 60}}) == 50.0
    assert agg_gpu({}) is None
    assert agg_gpu({"a": {"utilization": 0}}) == 0.0


# --- ring buffer ---


def test_push_bounded():
    ring = deque(maxlen=48)
    for i in range(60):
        push(ring, Sample(ts=float(i), cpu_pct=0, mem_pct=0, gpu_pct=None, net_bps=0))
    assert len(ring) == 48
    assert ring[-1].ts == 59.0  # newest kept


# --- sparkline ---


def test_sparkline_ascending():
    ring = deque(maxlen=48)
    for i in range(8):
        push(ring, Sample(ts=i, cpu_pct=float(i) * 10, mem_pct=0, gpu_pct=None, net_bps=0))
    assert to_sparkline(ring, "cpu_pct") == "▁▂▃▄▅▆▇█"


def test_sparkline_empty_is_spaces():
    assert to_sparkline(deque(maxlen=48), "cpu_pct") == "        "


def test_sparkline_flat_zero_is_low_blocks():
    ring = deque(maxlen=48)
    for _ in range(8):
        push(ring, Sample(ts=0, cpu_pct=0, mem_pct=0, gpu_pct=0.0, net_bps=0))
    # flatlined at zero → all low blocks (visually "dead")
    assert set(to_sparkline(ring, "gpu_pct")) == {"▁"}


def test_sparkline_flat_nonzero_is_absolute():
    """Flat line scales by absolute value: 50%→mid block, 100%→full block."""
    ring = deque(maxlen=48)
    for _ in range(8):
        push(ring, Sample(ts=0, cpu_pct=50.0, mem_pct=0, gpu_pct=None, net_bps=0))
    assert set(to_sparkline(ring, "cpu_pct")) == {"▅"}  # 50% → index 4
    ring2 = deque(maxlen=48)
    for _ in range(8):
        push(ring2, Sample(ts=0, cpu_pct=100.0, mem_pct=0, gpu_pct=None, net_bps=0))
    assert set(to_sparkline(ring2, "cpu_pct")) == {"█"}  # 100% → full


def test_sparkline_left_pads_few_samples():
    ring = deque(maxlen=48)
    push(ring, Sample(ts=0, cpu_pct=100.0, mem_pct=0, gpu_pct=None, net_bps=0))
    spark = to_sparkline(ring, "cpu_pct", width=8)
    assert spark == "       █"  # 7 spaces + full block


def test_sparkline_gpu_none_attr_skipped():
    ring = deque(maxlen=48)
    push(ring, Sample(ts=0, cpu_pct=50.0, mem_pct=0, gpu_pct=None, net_bps=0))
    assert to_sparkline(ring, "gpu_pct") == "        "  # None values dropped


# --- accrued cost ---


def test_accrued_cost_basic():
    from huggingface_hub import JobHardwareInfo

    job = make_job(flavor="cpu-basic", running_secs=600)  # 10 min
    pricing = {
        "cpu-basic": JobHardwareInfo(
            name="cpu-basic",
            prettyName="CPU Basic",
            cpu="2 vCPU",
            ram="16 GB",
            ephemeralStorage="20 GB",
            accelerator=None,
            unitCostMicroUSD=167,
            unitCostUSD=0.000167,
            unitLabel="minute",
        )
    }
    cost = accrued_cost(job, pricing)
    assert cost is not None
    assert cost == pytest.approx(600 / 60 * 0.000167)  # 10min * $0.000167


def test_accrued_cost_unknown_flavor_none():
    job = make_job(flavor="nope", running_secs=600)
    assert accrued_cost(job, {}) is None


def test_accrued_cost_enum_flavor():
    from huggingface_hub import JobHardwareInfo

    job = make_job(flavor="cpu-basic", running_secs=60)
    job.flavor = JobHardware.CPU_BASIC  # enum not str
    pricing = {
        "cpu-basic": JobHardwareInfo(
            name="cpu-basic",
            prettyName="CPU Basic",
            cpu="2 vCPU",
            ram="16 GB",
            ephemeralStorage="20 GB",
            accelerator=None,
            unitCostMicroUSD=167,
            unitCostUSD=0.000167,
            unitLabel="minute",
        )
    }
    assert accrued_cost(job, pricing) == pytest.approx(60 / 60 * 0.000167)


def test_accrued_cost_no_running_secs_none():
    job = make_job(running_secs=None)  # type: ignore[arg-type]
    assert accrued_cost(job, {"cpu-basic": object()}) is None  # type: ignore[arg-type]


# --- MonitorState thread-safety (smoke) ---


def test_monitor_state_set_and_snapshot():
    state = MonitorState()
    state.set_jobs([make_job()])
    state.push_sample("abc123def456", Sample(ts=1, cpu_pct=10, mem_pct=0, gpu_pct=None, net_bps=0))
    state.set_tail("abc123def456", "hello")
    snap = state.snapshot()
    assert len(snap["jobs"]) == 1
    assert snap["rings"]["abc123def456"][0].cpu_pct == 10
    assert snap["tail_logs"]["abc123def456"] == "hello"


def test_monitor_state_set_jobs_materializes_generator():
    # HfApi.list_jobs is a lazy paginating generator; if stored as-is, concurrent
    # iteration from the renderer + log-poller threads raises
    # "ValueError: generator already executing". set_jobs must materialize it.
    state = MonitorState()
    state.set_jobs(make_job() for _ in range(2))
    assert isinstance(state.jobs, list)
    assert len(state.jobs) == 2
    # Repeated reads must not exhaust anything.
    assert len(state.snapshot()["jobs"]) == 2
    assert len(state.snapshot()["jobs"]) == 2
