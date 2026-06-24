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

Note on runtime types: JobInfo.__init__ stores flavor / status.stage as the raw
strings the server sends (no enum coercion), even though the annotations say
JobHardware / JobStage. We handle both str and enum defensively via _flavor_str /
_stage_str so this never becomes a display bug.
"""

from __future__ import annotations

import re
from datetime import datetime

from huggingface_hub import JobHardware, JobInfo, JobStage

# Valid stages for status= predicate validation (real enum members).
_VALID_STAGES = {s.value for s in JobStage}
_HEX_ID = re.compile(r"^[0-9a-fA-F]{6,}$")


class SelectorError(Exception):
    """Raised on ambiguity, out-of-range @N, or unparseable selector."""


# --------------------------------------------------------------------------- #
# Pure: indexing + display helpers
# --------------------------------------------------------------------------- #


def index_jobs(jobs: list[JobInfo]) -> dict[int, JobInfo]:
    """Sort jobs by created_at descending (most recent first), assign @N (0-indexed).

    None created_at sorts last (oldest). Stable.
    """
    ordered = sorted(jobs, key=_sort_key, reverse=True)
    return dict(enumerate(ordered))


def _sort_key(job: JobInfo) -> tuple[int, float]:
    """Most-recent first: (present, timestamp). None → (0, 0.0) sorts after reverse."""
    ca = job.created_at
    if ca is None:
        return (0, 0.0)
    return (1, ca.timestamp() if isinstance(ca, datetime) else float(ca))


def stage_str(job: JobInfo) -> str:
    """Clean stage string ('RUNNING'), whether stored as str or JobStage enum."""
    stage = job.status.stage if job.status else None
    if stage is None:
        return "UNKNOWN"
    if isinstance(stage, JobStage):
        return stage.value
    return str(stage).upper()


def flavor_str(job: JobInfo) -> str:
    """Clean flavor string ('cpu-basic'), whether stored as str or JobHardware enum."""
    f = job.flavor
    if f is None:
        return "-"
    if isinstance(f, JobHardware):
        return f.value
    return str(f)


def display_name(job: JobInfo) -> str:
    """Human label for a job: docker image, else space, else id."""
    return job.docker_image or job.space_id or job.id


def fmt_duration(job: JobInfo) -> str:
    """Compact runtime from durations.running_secs (e.g. '2h14m', '5m', '12s')."""
    d = job.durations
    secs = d.running_secs if d and d.running_secs is not None else 0
    if secs < 60:
        return f"{secs}s"
    m = secs // 60
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h{m}m"


# --------------------------------------------------------------------------- #
# Pure: parsing
# --------------------------------------------------------------------------- #


def _split_tokens(spec: str) -> list[str]:
    """Split a single selector arg on commas ('@2,@5' → ['@2','@5'])."""
    return [t.strip() for t in spec.split(",") if t.strip()]


def _parse_token(token: str) -> tuple[str, object]:
    """Parse one selector token into (kind, value). Raises SelectorError on garbage.

    `@` is the universal selector sigil: anything starting with `@` is a selector,
    anything else is a literal job id (optionally `namespace/id`).
    """
    t = token.strip()
    if not t:
        raise SelectorError("empty selector")

    if t.startswith("@"):
        body = t[1:]
        low = body.lower()
        if body.isdigit():
            return ("position", int(body))
        if low == "latest":
            return ("position", 0)
        if low == "running":
            return ("status", "RUNNING")
        if low == "me":
            return ("all", None)
        if low.startswith("status="):
            stage = body.split("=", 1)[1].strip().upper()
            if stage not in _VALID_STAGES:
                raise SelectorError(
                    f"unknown status '{stage}'. Valid: {', '.join(sorted(_VALID_STAGES))}"
                )
            return ("status", stage)
        if low.startswith("label="):
            rest = body.split("=", 1)[1]  # 'KEY' or 'KEY=VAL'
            if "=" in rest:
                k, v = rest.split("=", 1)
                return ("label", (k.strip(), v.strip()))
            return ("label", (rest.strip(), None))
        raise SelectorError(
            f"unrecognized selector '{t}'. Use @N, @latest, @status=…, "
            f"@label=…, @running, @me, or a job id."
        )

    # Not a selector → literal id, optionally 'namespace/id'
    leaf = t.rsplit("/", 1)[-1]
    if _HEX_ID.match(leaf):
        return ("literal", leaf)

    raise SelectorError(
        f"unrecognized '{t}'. Selectors start with @ (@N, @status=…, @label=…, …); "
        f"or give a literal job id."
    )


# --------------------------------------------------------------------------- #
# Pure: matching
# --------------------------------------------------------------------------- #


def _matches(parsed: tuple[str, object], indexed: dict[int, JobInfo]) -> list[tuple[int, JobInfo]]:
    """Return all (index, job) pairs matching one parsed selector."""
    kind, value = parsed

    if kind == "position":
        n = value  # type: ignore[assignment]
        if n not in indexed:
            raise SelectorError(f"@{n} out of range (have {len(indexed)} jobs)")
        return [(n, indexed[n])]

    if kind == "status":
        want = value  # type: ignore[assignment]
        return [(i, j) for i, j in indexed.items() if stage_str(j) == want]

    if kind == "label":
        key, val = value  # type: ignore[misc]
        out: list[tuple[int, JobInfo]] = []
        for i, j in indexed.items():
            labels = j.labels or {}
            if key in labels and (val is None or labels[key] == val):
                out.append((i, j))
        return out

    if kind == "all":
        return list(indexed.items())

    if kind == "literal":
        leaf = value  # type: ignore[assignment]
        return [(i, j) for i, j in indexed.items() if j.id == leaf]

    raise SelectorError(f"internal: unknown selector kind '{kind}'")  # pragma: no cover


# --------------------------------------------------------------------------- #
# Public resolution API
# --------------------------------------------------------------------------- #


def resolve_indexed(
    specs: list[str], jobs: list[JobInfo], *, namespace: str
) -> list[tuple[int, JobInfo]]:
    """Resolve selector spec(s) to (index, job) pairs, deduped by id, order-preserving.

    Each spec may itself contain commas. Raises SelectorError on bad syntax / @N range.
    """
    indexed = index_jobs(jobs)
    seen: set[str] = set()
    out: list[tuple[int, JobInfo]] = []
    for spec in specs:
        for token in _split_tokens(spec):
            for i, job in _matches(_parse_token(token), indexed):
                if job.id in seen:
                    continue
                seen.add(job.id)
                out.append((i, job))
    return out


def resolve_selectors(specs: list[str], jobs: list[JobInfo], *, namespace: str) -> list[JobInfo]:
    """Resolve selectors to a job list (order-preserving, deduped)."""
    return [job for _, job in resolve_indexed(specs, jobs, namespace=namespace)]


def require_single(specs: list[str], jobs: list[JobInfo], *, namespace: str) -> JobInfo:
    """For single-target commands (logs/ssh/cancel/inspect).

    Returns the one matched job, or raises SelectorError:
      - 0 matches → 'no jobs match'
      - >1 matches → lists them with @N so the user can disambiguate
    """
    pairs = resolve_indexed(specs, jobs, namespace=namespace)
    if not pairs:
        raise SelectorError("no jobs match the selector")
    if len(pairs) > 1:
        lines = [f"  @{i:<3} {j.id}  {stage_str(j):<10} {display_name(j)}" for i, j in pairs]
        raise SelectorError(
            f"selector matched {len(pairs)} jobs — narrow it with @N or status=:\n"
            + "\n".join(lines)
        )
    return pairs[0][1]


def format_line(index: int, job: JobInfo) -> str:
    """One-line job display used by `resolve` and ambiguity errors."""
    return (
        f"@{index:<3} {job.id}  {stage_str(job):<10} {flavor_str(job):<14} "
        f"{fmt_duration(job):<6} {display_name(job)}"
    )
