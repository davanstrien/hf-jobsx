"""Deterministic fake data generator. (SPEC §3 fake.py) — ESSENTIAL.

HF_JOBSX_FAKE=1 swaps JobsClient for a fake: 5–8 jobs (mix RUNNING/SCHEDULING/
ERROR/COMPLETED) + a metrics simulator with realistic shapes (one climbing, one
flatlined = the OOM hero, one ramping, one idle) + ticking fake log lines.

Deterministic seed so the demo gif is reproducible. Lets you develop `top` and
take screenshots WITHOUT burning GPU compute. Default all demo content to fake mode.

NOT YET IMPLEMENTED (build alongside Phase 3 top; usable early for dev).
"""

from __future__ import annotations

FAKE_ENV = "HF_JOBSX_FAKE"


def is_fake_enabled() -> bool:
    """True if HF_JOBSX_FAKE is set to a truthy value."""
    import os

    return os.environ.get(FAKE_ENV, "").lower() in {"1", "true", "yes"}


def fake_client():  # -> JobsClient-compatible
    """Return a fake JobsClient with simulated jobs + metrics streams. TODO Phase 3."""
    raise NotImplementedError("Phase 3")
