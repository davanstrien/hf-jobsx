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
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from huggingface_hub import HfApi, JobHardwareInfo, JobInfo

if TYPE_CHECKING:
    pass


class JobsClient:
    """Thin synchronous wrapper. Callers handle concurrency (top) or exec (logs)."""

    def __init__(self, token: str | None = None, namespace: str | None = None) -> None:
        self._api = HfApi(token=token)
        self._token = token
        self._namespace = namespace
        self._pricing: dict[str, JobHardwareInfo] | None = None

    @property
    def namespace(self) -> str:
        """Lazily resolved via whoami(), cached. Deferred so auth/network errors
        become command-time errors, not import-time crashes."""
        if self._namespace is None:
            info = self._api.whoami(cache=True)
            self._namespace = info["name"]
        return self._namespace

    @property
    def token(self) -> str | None:
        """The token passed at construction (None = use cached auth). For propagating
        to native `hf jobs` subprocess calls (drill from top)."""
        return self._token

    def list_jobs(self) -> list[JobInfo]:
        return self._api.list_jobs(namespace=self.namespace)

    def get_job(self, job_id: str) -> JobInfo:
        return self._api.inspect_job(job_id=job_id, namespace=self.namespace)

    def fetch_logs(self, job_id: str, *, follow: bool, tail: int | None = None) -> Iterable[str]:
        return self._api.fetch_job_logs(
            job_id=job_id, namespace=self.namespace, follow=follow, tail=tail
        )

    def fetch_metrics(self, job_id: str) -> Iterable[dict[str, Any]]:
        """SSE stream, one dict/sec, NEVER ends. Caller must handle Ctrl-C. (Phase 3)"""
        return self._api.fetch_job_metrics(job_id=job_id, namespace=self.namespace)

    def hardware_pricing(self) -> dict[str, JobHardwareInfo]:
        """list_jobs_hardware() cached on the instance. name → JobHardwareInfo."""
        if self._pricing is None:
            self._pricing = {hw.name: hw for hw in self._api.list_jobs_hardware()}
        return self._pricing


def get_client(*, namespace: str | None, token: str | None) -> JobsClient:
    """Factory used by CLI commands. Returns a fresh client each invocation.

    Honors ``HF_JOBSX_FAKE=1`` (see ``fake.py``) so EVERY command — not just ``top`` —
    can run against the deterministic fake roster: demos, screenshots, and smoke tests
    that must work offline/logged-out (CI).
    """
    from hf_jobsx.fake import fake_client, is_fake_enabled

    if is_fake_enabled():
        return fake_client(token=token, namespace=namespace)
    return JobsClient(token=token, namespace=namespace)
