from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services import content_replenishment_service as service

START = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def worker(monkeypatch):
    state = SimpleNamespace(elapsed=0.0, claims=[], completions=[], loads=[], events=[], fail=None)
    jobs = [
        dict(id=f"job-{i}", subject_key="computer", micro_topic_id=f"topic-{i}", generation_batch_size=5, retry_count=0)
        for i in range(3)
    ]
    state.jobs = jobs.copy()
    monkeypatch.setattr(service, "monotonic", lambda: state.elapsed)
    monkeypatch.setattr(service.content_inventory_repo, "ensure_due_replenishment_jobs", lambda **kw: jobs)

    def claim(**kwargs):
        state.events.append("claim")
        state.claims.append(kwargs)
        count = kwargs["limit"]
        result, state.jobs = state.jobs[:count], state.jobs[count:]
        return result

    def load(job_id, **kwargs):
        state.loads.append(kwargs["now"])
        return [{"difficulty_counts": {"easy": 13, "medium": 6, "hard": 0}}]

    def generate(*args, **kwargs):
        state.events.append("generate")
        assert kwargs["difficulty_counts"] == {"easy": 13, "medium": 6, "hard": 0}
        state.elapsed += 25 * 60
        if state.fail:
            raise state.fail
        return service.ReplenishmentBatchResult([], [{"code": "proof_invalid"}], {}, {})

    def complete(**kwargs):
        state.events.append("complete")
        state.completions.append(kwargs)
        return {"status": "retry_wait"}

    monkeypatch.setattr(service.content_inventory_repo, "claim_replenishment_jobs", claim)
    monkeypatch.setattr(service.content_inventory_repo, "get_replenishment_bundle", load)
    monkeypatch.setattr(service, "_bundle_from_rows", lambda rows: SimpleNamespace(chapter="Operating Systems"))
    monkeypatch.setattr(service, "generate_and_store_candidate_batch", generate)
    monkeypatch.setattr(service.content_inventory_repo, "complete_replenishment_batch", complete)
    return state


def test_jobs_are_claimed_only_after_previous_batch_finishes(worker):
    result = service.process_due_replenishment_jobs(object(), worker_id="worker", now=START, limit=3)
    assert result.claimed == 3
    assert worker.events == ["claim", "generate", "complete"] * 3
    assert [call["limit"] for call in worker.claims] == [1, 1, 1]
    assert [call["now"] for call in worker.claims] == [START + timedelta(minutes=m) for m in (0, 25, 50)]
    assert worker.loads == [START + timedelta(minutes=m) for m in (0, 25, 50)]
    assert [call["retry_at"] for call in worker.completions] == [START + timedelta(minutes=m) for m in (40, 65, 90)]


def test_exception_backoff_starts_after_failure_not_run_start(worker):
    worker.fail = ValueError("invalid candidate response")
    result = service.process_due_replenishment_jobs(object(), worker_id="worker", now=START, limit=1)
    assert result.outcomes == {"computer:topic-0": "retry_wait:ValueError"}
    assert worker.completions[0]["retry_at"] == START + timedelta(minutes=40)
    assert worker.completions[0]["accepted_count"] == 0


@pytest.mark.parametrize("generation_fails", [False, True])
def test_completion_failure_is_not_replayed_or_followed_by_another_claim(worker, monkeypatch, generation_fails):
    if generation_fails:
        worker.fail = ValueError("invalid content")
    calls = []

    def fail_completion(**kwargs):
        calls.append(kwargs)
        raise TimeoutError("completion response lost")

    monkeypatch.setattr(service.content_inventory_repo, "complete_replenishment_batch", fail_completion)
    with pytest.raises(TimeoutError, match="completion response lost"):
        service.process_due_replenishment_jobs(object(), worker_id="worker", now=START, limit=3)
    assert len(calls) == 1
    assert len(worker.claims) == 1
    assert len(worker.jobs) == 2


def test_empty_queue_stops_without_reserving_extra_work(worker):
    worker.jobs = []
    result = service.process_due_replenishment_jobs(object(), worker_id="worker", now=START, limit=5)
    assert result.claimed == 0
    assert result.outcomes == {}
    assert worker.events == ["claim"]


def test_batch_limit_is_a_hard_cap_with_more_due_work(worker):
    service.process_due_replenishment_jobs(object(), worker_id="worker", now=START, limit=2)
    assert len(worker.claims) == len(worker.completions) == 2
    assert len(worker.jobs) == 1


def test_successful_topic_can_return_for_another_bounded_batch(worker, monkeypatch):
    job = worker.jobs[0]
    calls = []

    def claim(**kwargs):
        calls.append(kwargs)
        return [job]

    monkeypatch.setattr(service.content_inventory_repo, "claim_replenishment_jobs", claim)
    monkeypatch.setattr(
        service,
        "generate_and_store_candidate_batch",
        lambda *a, **kw: service.ReplenishmentBatchResult([{"verified": True}], [], {}, {}),
    )
    monkeypatch.setattr(
        service.content_inventory_repo,
        "complete_replenishment_batch",
        lambda **kw: worker.completions.append(kw) or {"status": "due"},
    )
    result = service.process_due_replenishment_jobs(object(), worker_id="worker", now=START, limit=2)
    assert result.claimed == len(calls) == len(worker.completions) == 2
    assert result.outcomes == {"computer:topic-0": "due"}
    assert all(
        call["accepted_count"] == 1 and call["retry_at"] is None and call["error_code"] is None
        for call in worker.completions
    )


@pytest.mark.parametrize("limit", [0, -1, 26, True, 1.5])
def test_invalid_batch_budget_fails_before_any_database_write(worker, monkeypatch, limit):
    def no_write(**kwargs):
        pytest.fail("invalid budget reached database writer")

    monkeypatch.setattr(service.content_inventory_repo, "ensure_due_replenishment_jobs", no_write)
    with pytest.raises(ValueError, match="between 1 and 25"):
        service.process_due_replenishment_jobs(object(), worker_id="worker", now=START, limit=limit)


def test_naive_start_is_normalized_to_utc(worker):
    service.process_due_replenishment_jobs(object(), worker_id="worker", now=START.replace(tzinfo=None), limit=1)
    assert worker.claims[0]["now"] == START
