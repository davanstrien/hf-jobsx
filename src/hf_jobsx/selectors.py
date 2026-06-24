"""Selector grammar, parsing, and resolution. (SPEC §2 & §3 selectors.py)

THE foundational module — every command trusts it. Pure: no I/O, fully unit-tested.

Grammar:
    selector   := single ( "," single )*
    single     := "@" INT              # @0 ≡ @latest, 0 = most recent
                | "latest"             # ≡ @0
                | "status=" STAGE      # status=running, status=error
                | "label=" KEY ["=" VAL]
                | "running"            # ≡ status=running
                | "me"                 # all jobs in active namespace
                | literal_id | namespace "/" literal_id

Resolution:
    - Fresh list_jobs() snapshot, sorted by created_at desc. @N is positional in it.
    - Predicates may match MANY; single-target commands require exactly one match
      (else error listing matches with their @N so the user can disambiguate).

Real JobStage members: COMPLETED, CANCELED, ERROR, DELETED, SCHEDULING, RUNNING.
(NO phantom PENDING — that was the old dashboard's bug.)

NOT YET IMPLEMENTED (Phase 1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from huggingface_hub import JobInfo


class SelectorError(Exception):
    """Raised on ambiguity, out-of-range @N, or unparseable selector."""


def index_jobs(jobs: list[JobInfo]) -> dict[int, JobInfo]:
    """Sort by created_at desc, assign @N (0-indexed). TODO Phase 1."""
    raise NotImplementedError("Phase 1 — see SPEC.md §2")


def resolve_selectors(specs: list[str], jobs: list[JobInfo], *, namespace: str) -> list[JobInfo]:
    """Resolve selector tokens to JobInfo list. Raises SelectorError on ambiguity. TODO Phase 1."""
    raise NotImplementedError("Phase 1 — see SPEC.md §2")
