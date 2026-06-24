"""Thin I/O wrapper around huggingface_hub public API. (SPEC §3 jobs_client.py)

NON-NEGOTIABLE: namespace is resolved LAZILY (on first access), never at import.
Auth/network failures must surface as user-facing command errors, not import crashes.
(This is the lesson the old jobs-dashboard learned the hard way.)

Public API consumed (all top-level importable, verified):
    from huggingface_hub import (
        HfApi, JobInfo, list_jobs, inspect_job, fetch_job_logs,
        fetch_job_metrics, list_jobs_hardware,
    )
Do NOT import from huggingface_hub._jobs_api (private).

NOT YET IMPLEMENTED (Phase 1).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from huggingface_hub import JobHardwareInfo, JobInfo


class JobsClient:
    """Thin wrapper. Methods are synchronous; callers handle concurrency (top) or exec (logs)."""

    def __init__(self, token: str | None = None, namespace: str | None = None) -> None:
        self._token = token
        self._namespace = namespace

    @property
    def namespace(self) -> str:
        """Lazily resolved via whoami(), cached. TODO Phase 1."""
        raise NotImplementedError("Phase 1")

    def list_jobs(self) -> list[JobInfo]:
        raise NotImplementedError("Phase 1")

    def get_job(self, job_id: str) -> JobInfo:
        raise NotImplementedError("Phase 1")

    def fetch_logs(self, job_id: str, *, follow: bool, tail: int | None = None) -> Iterable[str]:
        raise NotImplementedError("Phase 1")

    def fetch_metrics(self, job_id: str) -> Iterable[dict[str, Any]]:
        """SSE stream, one dict/sec, NEVER ends. Caller must handle Ctrl-C. TODO Phase 3."""
        raise NotImplementedError("Phase 3")

    def hardware_pricing(self) -> dict[str, JobHardwareInfo]:
        """list_jobs_hardware() cached on the instance. TODO Phase 3."""
        raise NotImplementedError("Phase 3")
