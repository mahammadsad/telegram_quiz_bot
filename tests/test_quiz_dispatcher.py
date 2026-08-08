from datetime import date, datetime, timezone

from services import quiz_dispatcher
from services.quiz_lifecycle import RunOutcome


def _jobs(specs):
    return [
        {
            "id": f"job-{index}",
            "quiz_id": spec["quiz_id"],
            "subject_key": spec["subject_key"],
            "code_sha": "sha",
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
