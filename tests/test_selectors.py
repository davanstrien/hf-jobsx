"""Exhaustive tests for selectors.py — the foundation everything trusts.

Built against the REAL JobInfo constructor (not MagicMock), so we catch the exact
class of bug that sank the old jobs-dashboard (status/flavor enums, phantom PENDING).
"""

from __future__ import annotations

import pytest
from huggingface_hub import JobInfo

from hf_jobsx.selectors import (
    SelectorError,
    display_name,
    flavor_str,
    fmt_duration,
    index_jobs,
    require_single,
    resolve_indexed,
    resolve_selectors,
    stage_str,
)

# --------------------------------------------------------------------------- #
# fixtures: real JobInfo objects
# --------------------------------------------------------------------------- #


def make_job(
    *,
    id: str,
    created_at: str = "2026-06-24T10:00:00Z",
    stage: str = "RUNNING",
    flavor: str | None = "cpu-basic",
    docker_image: str | None = "python:3.12",
    space_id: str | None = None,
    labels: dict[str, str] | None = None,
    running_secs: int | None = 0,
) -> JobInfo:
    """Build a real JobInfo via its actual constructor (camelCase API keys)."""
    return JobInfo(
        id=id,
        createdAt=created_at,
        dockerImage=docker_image,
        spaceId=space_id,
        owner={"id": "u1", "name": "testuser", "type": "user"},
        flavor=flavor,
        labels=labels,
        status={"stage": stage},
        durations={"schedulingSecs": 1, "runningSecs": running_secs, "totalSecs": running_secs},
    )


@pytest.fixture
def sample_jobs() -> list[JobInfo]:
    """Three jobs: newest first is abc (10:00), ghi (09:00), def (08:00)."""
    return [
        make_job(
            id="abc123def456",
            created_at="2026-06-24T10:00:00Z",
            stage="RUNNING",
            flavor="a10g-small",
            docker_image="train:latest",
            labels={"exp": "baseline", "model": "llama"},
        ),
        make_job(
            id="ghi789abc012",
            created_at="2026-06-24T09:00:00Z",
            stage="ERROR",
            flavor="a10g-large",
            docker_image="train:latest",
            running_secs=5400,
        ),
        make_job(
            id="def456ghi789",
            created_at="2026-06-24T08:00:00Z",
            stage="SCHEDULING",
            flavor="cpu-basic",
            space_id="user/space",
        ),
        make_job(
            id="mno999000111",
            created_at="2026-06-24T07:00:00Z",
            stage="COMPLETED",
            flavor="cpu-basic",
            running_secs=120,
        ),
    ]


# --------------------------------------------------------------------------- #
# indexing + display helpers
# --------------------------------------------------------------------------- #


def test_index_jobs_orders_by_created_desc(sample_jobs):
    indexed = index_jobs(sample_jobs)
    assert list(indexed.keys()) == [0, 1, 2, 3]
    assert indexed[0].id == "abc123def456"  # newest
    assert indexed[3].id == "mno999000111"  # oldest


def test_index_jobs_none_created_at_sorts_last():
    jobs = [
        make_job(id="new", created_at="2026-06-24T10:00:00Z"),
        make_job(id="noca", created_at="2026-06-24T10:00:00Z"),  # tiebreaker
        make_job(id="unk", created_at=None),  # type: ignore[arg-type]
    ]
    indexed = index_jobs(jobs)
    assert indexed[2].id == "unk"


def test_stage_str_handles_str_and_enum():
    assert stage_str(make_job(id="a", stage="running")) == "RUNNING"  # case folded
    assert stage_str(make_job(id="b", stage="COMPLETED")) == "COMPLETED"
    # missing status entirely
    j = make_job(id="c")
    j.status = None  # type: ignore[assignment]
    assert stage_str(j) == "UNKNOWN"


def test_flavor_str_none():
    assert flavor_str(make_job(id="a", flavor=None)) == "-"
    assert flavor_str(make_job(id="b", flavor="a10g-small")) == "a10g-small"


def test_display_name_prefers_image_then_space():
    assert display_name(make_job(id="a", docker_image="img:1")) == "img:1"
    assert display_name(make_job(id="a", docker_image=None, space_id="user/space")) == "user/space"
    assert display_name(make_job(id="abc123", docker_image=None, space_id=None)) == "abc123"


def test_fmt_duration():
    assert fmt_duration(make_job(id="a", running_secs=45)) == "45s"
    assert fmt_duration(make_job(id="b", running_secs=5400)) == "1h30m"
    assert fmt_duration(make_job(id="c", running_secs=300)) == "5m"
    assert fmt_duration(make_job(id="d", running_secs=0)) == "0s"


# --------------------------------------------------------------------------- #
# resolution: positions & latest
# --------------------------------------------------------------------------- #


def test_resolve_position_and_latest_equivalent(sample_jobs):
    ns = "testuser"
    assert resolve_selectors(["@0"], sample_jobs, namespace=ns)[0].id == "abc123def456"
    assert resolve_selectors(["@latest"], sample_jobs, namespace=ns)[0].id == "abc123def456"


def test_resolve_position_out_of_range(sample_jobs):
    with pytest.raises(SelectorError, match="out of range"):
        resolve_selectors(["@99"], sample_jobs, namespace="testuser")


def test_resolve_position_garbage():
    with pytest.raises(SelectorError, match="unrecognized selector"):
        resolve_selectors(["@abc"], [], namespace="testuser")


# --------------------------------------------------------------------------- #
# resolution: status & label predicates
# --------------------------------------------------------------------------- #


def test_resolve_status_single(sample_jobs):
    res = resolve_selectors(["@status=error"], sample_jobs, namespace="testuser")
    assert [j.id for j in res] == ["ghi789abc012"]


def test_resolve_status_case_insensitive(sample_jobs):
    res = resolve_selectors(["@status=RUNNING"], sample_jobs, namespace="testuser")
    assert [j.id for j in res] == ["abc123def456"]


def test_resolve_status_no_matches(sample_jobs):
    assert resolve_selectors(["@status=canceled"], sample_jobs, namespace="testuser") == []


def test_resolve_status_unknown_stage():
    with pytest.raises(SelectorError, match="unknown status 'PENDING'"):
        resolve_selectors(["@status=pending"], [], namespace="testuser")  # phantom PENDING rejected


def test_resolve_running_sugar(sample_jobs):
    assert (
        resolve_selectors(["@running"], sample_jobs, namespace="testuser")[0].id == "abc123def456"
    )


def test_resolve_label_key_only(sample_jobs):
    res = resolve_selectors(["@label=exp"], sample_jobs, namespace="testuser")
    assert [j.id for j in res] == ["abc123def456"]


def test_resolve_label_key_value(sample_jobs):
    res = resolve_selectors(["@label=model=llama"], sample_jobs, namespace="testuser")
    assert [j.id for j in res] == ["abc123def456"]
    assert resolve_selectors(["@label=model=other"], sample_jobs, namespace="testuser") == []


def test_resolve_me_all(sample_jobs):
    res = resolve_selectors(["@me"], sample_jobs, namespace="testuser")
    assert len(res) == 4


# --------------------------------------------------------------------------- #
# resolution: literals, lists, dedup
# --------------------------------------------------------------------------- #


def test_resolve_literal_id(sample_jobs):
    res = resolve_selectors(["abc123def456"], sample_jobs, namespace="testuser")
    assert [j.id for j in res] == ["abc123def456"]


def test_resolve_namespaced_literal(sample_jobs):
    res = resolve_selectors(["testuser/abc123def456"], sample_jobs, namespace="testuser")
    assert [j.id for j in res] == ["abc123def456"]


def test_resolve_comma_list(sample_jobs):
    res = resolve_selectors(["@0,@2"], sample_jobs, namespace="testuser")
    assert [j.id for j in res] == ["abc123def456", "def456ghi789"]


def test_resolve_multiple_args(sample_jobs):
    res = resolve_selectors(["@0", "@1"], sample_jobs, namespace="testuser")
    assert [j.id for j in res] == ["abc123def456", "ghi789abc012"]


def test_resolve_dedup_same_id(sample_jobs):
    res = resolve_selectors(["@0", "@latest", "@0"], sample_jobs, namespace="testuser")
    assert [j.id for j in res] == ["abc123def456"]


def test_resolve_unrecognized_token():
    with pytest.raises(SelectorError, match="unrecognized"):
        resolve_selectors(["banana"], [], namespace="testuser")


# --------------------------------------------------------------------------- #
# require_single
# --------------------------------------------------------------------------- #


def test_require_single_ok(sample_jobs):
    job = require_single(["@status=error"], sample_jobs, namespace="testuser")
    assert job.id == "ghi789abc012"


def test_require_single_zero_raises(sample_jobs):
    with pytest.raises(SelectorError, match="no jobs match"):
        require_single(["@status=canceled"], sample_jobs, namespace="testuser")


def test_require_single_ambiguous_lists_matches(sample_jobs):
    jobs = sample_jobs + [
        make_job(id="run2abc000000", created_at="2026-06-24T11:00:00Z", stage="RUNNING")
    ]
    with pytest.raises(SelectorError) as exc:
        require_single(["@status=running"], jobs, namespace="testuser")
    msg = str(exc.value)
    assert "matched 2 jobs" in msg
    assert "@0" in msg and "run2abc000000" in msg  # lists them with @N for disambiguation


def test_resolve_indexed_preserves_order_and_indices(sample_jobs):
    pairs = resolve_indexed(["@status=scheduling,@0"], sample_jobs, namespace="testuser")
    # scheduling = def (index 2 in full list), @0 = abc (index 0)
    assert pairs[0][0] == 2 and pairs[0][1].id == "def456ghi789"
    assert pairs[1][0] == 0 and pairs[1][1].id == "abc123def456"
