import logging
from datetime import date, datetime, timedelta, timezone

import pytest

from services import quiz_dispatch_runtime, quiz_dispatcher
from services.quiz_lifecycle import RunOutcome


def _jobs(specs):
    return [
        {
            "id": f"job-{index}",
            "quiz_id": spec["quiz_id"],
            "logical_date": spec["logical_date"],
            "subject_key": spec["subject_key"],
            "code_sha": "sha",
            "retry_count": index,
        }
        for index, spec in enumerate(specs)
    ]


def test_daily_job_specs_cover_exactly_thirteen_subjects_in_utc():
    specs = quiz_dispatcher.daily_job_specs(date(2026, 8, 8))
    assert len(specs) == 13
    assert len({row["subject_key"] for row in specs}) == 13
    assert len({row["quiz_id"] for row in specs}) == 13
    assert all(row["due_at"].endswith("+00:00") for row in specs)


def test_delayed_dispatch_claims_every_due_job_and_isolates_failures(monkeypatch):
    now = datetime(2026, 8, 8, 14, tzinfo=timezone.utc)
    specs = quiz_dispatcher.daily_job_specs(date(2026, 8, 8))
    jobs = _jobs(specs)
    transitions = []
    failures = []

    def record_transition(**kwargs):
        transitions.append(kwargs)

    monkeypatch.setattr(quiz_dispatcher.quiz_jobs_repo, "ensure_daily", lambda *a, **k: jobs)
    monkeypatch.setattr(quiz_dispatcher.quiz_jobs_repo, "claim_due", lambda **k: jobs)
    monkeypatch.setattr(
        quiz_dispatcher.quiz_jobs_repo,
        "transition",
        record_transition,
    )
    monkeypatch.setattr(
        quiz_dispatcher.quiz_jobs_repo,
        "fail",
        lambda **kwargs: failures.append(kwargs) or {"status": "retry_wait"},
    )

    def runner(subject, **kwargs):
        if subject == jobs[3]["subject_key"]:
            raise TimeoutError("temporary source timeout")
        return RunOutcome.GENERATED_AND_POSTED

    result = quiz_dispatcher.dispatch_due_jobs(runner, now=now, worker_id="worker")
    assert result.claimed == 13
    assert len(transitions) == 13
    assert len(failures) == 1
    assert len(result.outcomes) == 13
    assert result.outcomes[jobs[3]["subject_key"]].startswith("retry_wait:")


def test_already_posted_is_synchronized_and_unknown_is_quarantined(monkeypatch):
    now = datetime(2026, 8, 8, 14, tzinfo=timezone.utc)
    specs = quiz_dispatcher.daily_job_specs(date(2026, 8, 8))
    jobs = _jobs(specs[:2])
    synced = []
    unknown = []
    monkeypatch.setattr(quiz_dispatcher.quiz_jobs_repo, "ensure_daily", lambda *a, **k: jobs)
    monkeypatch.setattr(quiz_dispatcher.quiz_jobs_repo, "claim_due", lambda **k: jobs)
    monkeypatch.setattr(quiz_dispatcher.quiz_jobs_repo, "transition", lambda **k: None)
    monkeypatch.setattr(
        quiz_dispatcher.quiz_jobs_repo,
        "sync_posted_run",
        lambda **kwargs: synced.append(kwargs),
    )
    monkeypatch.setattr(
        quiz_dispatcher.quiz_jobs_repo,
        "mark_posting_unknown",
        lambda **kwargs: unknown.append(kwargs),
    )

    outcomes = iter([RunOutcome.ALREADY_POSTED, RunOutcome.POSTING_OUTCOME_UNKNOWN])
    result = quiz_dispatcher.dispatch_due_jobs(
        lambda *a, **k: next(outcomes), now=now, worker_id="worker"
    )
    assert synced == [{"quiz_id": jobs[0]["quiz_id"], "worker_id": "worker"}]
    assert unknown[0]["job_id"] == jobs[1]["id"]
    assert result.actionable_failures is True


def test_midnight_catchup_runs_each_job_for_its_own_logical_date(monkeypatch):
    now = datetime(2026, 8, 8, 19, tzinfo=timezone.utc)
    old_specs = quiz_dispatcher.daily_job_specs(date(2026, 8, 8))
    old_job = _jobs(old_specs[:1])[0]
    targets = []

    monkeypatch.setattr(
        quiz_dispatcher.quiz_jobs_repo,
        "ensure_daily",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        quiz_dispatcher.quiz_jobs_repo,
        "claim_due",
        lambda **kwargs: [old_job],
    )
    monkeypatch.setattr(
        quiz_dispatcher.quiz_jobs_repo,
        "transition",
        lambda **kwargs: None,
    )

    def runner(subject, **kwargs):
        targets.append((kwargs["target_date"], kwargs["durable_retry_count"]))
        return RunOutcome.GENERATED_AND_POSTED

    result = quiz_dispatcher.dispatch_due_jobs(
        runner,
        now=now,
        worker_id="worker",
    )

    assert result.logical_date == date(2026, 8, 9)
    assert targets == [(date(2026, 8, 8), 0)]


def test_global_health_keeps_unclaimed_dead_letter_red():
    now = datetime(2026, 8, 8, 14, tzinfo=timezone.utc)
    specs = quiz_dispatcher.daily_job_specs(date(2026, 8, 8))
    rows = [{
        "subject_key": spec["subject_key"],
        "status": "posted",
        "retry_count": 0,
    } for spec in specs]
    rows[3] = {
        "subject_key": specs[3]["subject_key"],
        "status": "dead_letter",
        "retry_count": 8,
        "last_error_category": "validation_failed",
    }

    outcomes = quiz_dispatcher.global_due_outcomes(specs, rows, now=now)

    assert outcomes[specs[3]["subject_key"]] == "dead_letter:validation_failed"
    result = quiz_dispatcher.DispatchResult(date(2026, 8, 8), 13, 0, {}, outcomes)
    assert result.actionable_failures is True


def test_global_health_alerts_when_due_quiz_is_over_thirty_minutes_late():
    now = datetime(2026, 8, 8, 14, tzinfo=timezone.utc)
    specs = quiz_dispatcher.daily_job_specs(date(2026, 8, 8))
    outcomes = quiz_dispatcher.global_due_outcomes(specs, [], now=now)

    assert any(value == "overdue:missing" for value in outcomes.values())


def test_dispatch_result_tracks_the_earliest_database_retry_timestamp(monkeypatch):
    now = datetime(2026, 8, 8, 14, tzinfo=timezone.utc)
    specs = quiz_dispatcher.daily_job_specs(date(2026, 8, 8))
    jobs = _jobs(specs[:2])
    retry_times = iter([
        now + timedelta(seconds=90),
        (now + timedelta(seconds=65)).isoformat(),
    ])
    monkeypatch.setattr(quiz_dispatcher.quiz_jobs_repo, "ensure_daily", lambda *a, **k: jobs)
    monkeypatch.setattr(quiz_dispatcher.quiz_jobs_repo, "claim_due", lambda **k: jobs)
    monkeypatch.setattr(quiz_dispatcher.quiz_jobs_repo, "transition", lambda **k: None)
    monkeypatch.setattr(
        quiz_dispatcher.quiz_jobs_repo,
        "fail",
        lambda **kwargs: {
            "status": "retry_wait",
            "next_retry_at": next(retry_times),
        },
    )

    def fail(*args, **kwargs):
        raise TimeoutError("temporary provider failure")

    result = quiz_dispatcher.dispatch_due_jobs(fail, now=now, worker_id="worker")

    assert result.next_retry_at == now + timedelta(seconds=65)


class _FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


def test_bounded_inline_retry_waits_until_database_timestamp(monkeypatch):
    started = datetime(2026, 8, 8, 14, tzinfo=timezone.utc)
    clock = _FakeClock(started)
    calls: list[datetime] = []
    results = iter([
        quiz_dispatcher.DispatchResult(
            date(2026, 8, 8),
            13,
            1,
            {"science": "retry_wait:validation_failed"},
            {"science": "retrying:retry_wait"},
            started + timedelta(seconds=60),
        ),
        quiz_dispatcher.DispatchResult(
            date(2026, 8, 8),
            13,
            1,
            {"science": "generated_and_posted"},
            {"science": "posted"},
        ),
    ])

    def dispatch_once(**kwargs):
        calls.append(kwargs["now"])
        return next(results)

    monkeypatch.setattr(quiz_dispatch_runtime, "dispatch_due_jobs", dispatch_once)
    result = quiz_dispatch_runtime.dispatch_due_jobs_with_bounded_retries(
        dispatcher=object(),
        runner=lambda *a, **k: RunOutcome.GENERATED_AND_POSTED,
        worker_id="worker",
        logger=logging.getLogger("test"),
        max_passes=4,
        retry_window_seconds=900,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert clock.sleeps == [62.0]
    assert calls == [started, started + timedelta(seconds=62)]
    assert result.global_outcomes == {"science": "posted"}


def test_bounded_inline_retry_defers_work_outside_window(monkeypatch):
    started = datetime(2026, 8, 8, 14, tzinfo=timezone.utc)
    clock = _FakeClock(started)
    result = quiz_dispatcher.DispatchResult(
        date(2026, 8, 8),
        13,
        1,
        {"environment": "retry_wait:provider_transient"},
        {"environment": "retrying:retry_wait"},
        started + timedelta(seconds=901),
    )
    calls = []
    monkeypatch.setattr(
        quiz_dispatch_runtime,
        "dispatch_due_jobs",
        lambda **kwargs: calls.append(kwargs) or result,
    )

    observed = quiz_dispatch_runtime.dispatch_due_jobs_with_bounded_retries(
        dispatcher=object(),
        runner=lambda *a, **k: RunOutcome.GENERATED_AND_POSTED,
        worker_id="worker",
        logger=logging.getLogger("test"),
        max_passes=4,
        retry_window_seconds=900,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert observed is result
    assert len(calls) == 1
    assert clock.sleeps == []


@pytest.mark.parametrize(
    ("max_passes", "window", "message"),
    [(0, 900, "max_passes"), (4, -1, "retry_window_seconds")],
)
def test_bounded_inline_retry_rejects_invalid_limits(max_passes, window, message):
    with pytest.raises(ValueError, match=message):
        quiz_dispatch_runtime.dispatch_due_jobs_with_bounded_retries(
            dispatcher=object(),
            runner=lambda *a, **k: RunOutcome.GENERATED_AND_POSTED,
            worker_id="worker",
            logger=logging.getLogger("test"),
            max_passes=max_passes,
            retry_window_seconds=window,
        )
