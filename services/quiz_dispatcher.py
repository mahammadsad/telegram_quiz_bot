"""Durable heartbeat dispatcher for all due subject quizzes."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from config.settings import (
    APP_TIMEZONE,
    PRODUCTION_CONFIG_HASH,
    QUIZ_JOB_LEASE_MINUTES,
    QUIZ_JOB_MAX_RETRIES,
    QUIZ_JOB_RETRY_BASE_SECONDS,
    QUIZ_JOB_RETRY_MAX_SECONDS,
)
from config.subjects import QUIZ_SUBJECTS
from services.quiz_lifecycle import RunOutcome, is_successful_outcome
from storage import quiz_jobs_repo
from utils.quiz_ids import build_quiz_id

LOG = logging.getLogger("quiz-dispatcher")

JobRunner = Callable[..., str | RunOutcome]


@dataclass(frozen=True, slots=True)
class DispatchResult:
    logical_date: date
    ensured: int
    claimed: int
    outcomes: dict[str, str]
    global_outcomes: dict[str, str]

    @property
    def actionable_failures(self) -> bool:
        observed = {**self.outcomes, **self.global_outcomes}
        return any(
            value.startswith(("blocked:", "dead_letter:", "unknown:"))
            or value.startswith("overdue:")
            for value in observed.values()
        )


def daily_job_specs(logical_date: date) -> list[dict[str, str]]:
    zone = ZoneInfo(APP_TIMEZONE)
    specs: list[dict[str, str]] = []
    for subject in QUIZ_SUBJECTS:
        if not subject.scheduled_time_ist:
            raise RuntimeError(f"Missing due time for {subject.key}.")
        hour, minute = (int(part) for part in subject.scheduled_time_ist.split(":"))
        due_local = datetime(
            logical_date.year,
            logical_date.month,
            logical_date.day,
            hour,
            minute,
            tzinfo=zone,
        )
        specs.append({
            "quiz_id": build_quiz_id(logical_date, subject.key),
            "logical_date": logical_date.isoformat(),
            "subject_key": subject.key,
            "due_at": due_local.astimezone(timezone.utc).isoformat(),
        })
    return specs


def dispatch_due_jobs(
    runner: JobRunner,
    *,
    now: datetime | None = None,
    worker_id: str,
    code_sha: str | None = None,
    source_bundle_hash: str | None = None,
) -> DispatchResult:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    logical_date = current.astimezone(ZoneInfo(APP_TIMEZONE)).date()
    specs = daily_job_specs(logical_date)
    ensured = quiz_jobs_repo.ensure_daily(
        specs,
        configuration_hash=PRODUCTION_CONFIG_HASH,
        code_sha=(code_sha or os.environ.get("GITHUB_SHA") or "local-uncommitted"),
        source_bundle_hash=source_bundle_hash,
    )
    claimed = quiz_jobs_repo.claim_due(
        worker_id=worker_id,
        now=current.astimezone(timezone.utc),
        lease_minutes=QUIZ_JOB_LEASE_MINUTES,
        limit=len(QUIZ_SUBJECTS),
    )
    outcomes: dict[str, str] = {}
    for job in claimed:
        subject_key = str(job["subject_key"])
        job_id = str(job["id"])
        quiz_id = str(job["quiz_id"])
        try:
            job_logical_date = date.fromisoformat(str(job["logical_date"]))
            quiz_jobs_repo.transition(
                job_id=job_id,
                worker_id=worker_id,
                target_status="generating",
                event_type="dispatch_started",
                detail={"code_sha": job.get("code_sha")},
            )
            outcome = runner(
                subject_key,
                target_date=job_logical_date,
                durable_job_id=job_id,
                durable_worker_id=worker_id,
                durable_retry_count=int(job.get("retry_count") or 0),
            )
            outcome_text = str(outcome)
            if outcome == RunOutcome.ALREADY_POSTED:
                quiz_jobs_repo.sync_posted_run(quiz_id=quiz_id, worker_id=worker_id)
            elif outcome == RunOutcome.POSTING_OUTCOME_UNKNOWN:
                quiz_jobs_repo.mark_posting_unknown(
                    job_id=job_id,
                    worker_id=worker_id,
                    category="telegram_delivery_unknown",
                    code="compatible_run_posting_unknown",
                    reason="Compatible quiz run requires Telegram reconciliation.",
                )
                outcome_text = "unknown:telegram_delivery_unknown"
            elif not is_successful_outcome(outcome):
                retryable = outcome == RunOutcome.ALREADY_CLAIMED
                failure = quiz_jobs_repo.fail(
                    job_id=job_id,
                    worker_id=worker_id,
                    retryable=retryable,
                    category=outcome_text,
                    code=outcome_text,
                    reason=f"Subject runner returned unresolved outcome: {outcome_text}",
                    max_retries=QUIZ_JOB_MAX_RETRIES,
                    base_delay_seconds=QUIZ_JOB_RETRY_BASE_SECONDS,
                    max_delay_seconds=QUIZ_JOB_RETRY_MAX_SECONDS,
                )
                outcome_text = f"{failure['status']}:{outcome_text}"
            outcomes[subject_key] = outcome_text
        except Exception as exc:
            category = str(getattr(exc, "category", type(exc).__name__))
            retryable = bool(getattr(exc, "retryable", True))
            try:
                failure = quiz_jobs_repo.fail(
                    job_id=job_id,
                    worker_id=worker_id,
                    retryable=retryable,
                    category=category,
                    code=type(exc).__name__,
                    reason=str(exc)[:500],
                    max_retries=QUIZ_JOB_MAX_RETRIES,
                    base_delay_seconds=QUIZ_JOB_RETRY_BASE_SECONDS,
                    max_delay_seconds=QUIZ_JOB_RETRY_MAX_SECONDS,
                )
                outcomes[subject_key] = f"{failure['status']}:{category}"
            except Exception:
                # The delivery trigger may already have moved the job to
                # posting_unknown; normal retry handling must not overwrite it.
                outcomes[subject_key] = f"unknown:{category}"
            LOG.exception(
                "QUIZ_JOB_FAILED job_id=%s quiz_id=%s subject=%s category=%s",
                job_id,
                quiz_id,
                subject_key,
                category,
            )
    try:
        global_outcomes = global_due_outcomes(
            specs,
            job_health_rows(logical_date),
            now=current.astimezone(timezone.utc),
        )
    except Exception:
        LOG.exception("QUIZ_JOB_GLOBAL_HEALTH_QUERY_FAILED date=%s", logical_date)
        global_outcomes = {"__health__": "blocked:health_query_failed"}
    return DispatchResult(
        logical_date,
        len(ensured),
        len(claimed),
        outcomes,
        global_outcomes,
    )


def global_due_outcomes(
    specs: list[dict[str, str]],
    rows: list[dict[str, Any]],
    *,
    now: datetime,
    grace: timedelta = timedelta(minutes=30),
) -> dict[str, str]:
    """Evaluate every globally due subject, including unclaimed dead letters."""
    by_subject = {str(row.get("subject_key")): row for row in rows}
    outcomes: dict[str, str] = {}
    for spec in specs:
        subject = spec["subject_key"]
        due_at = datetime.fromisoformat(spec["due_at"])
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        if due_at > now:
            outcomes[subject] = "not_due"
            continue
        row = by_subject.get(subject)
        if row is None:
            outcomes[subject] = (
                "overdue:missing" if due_at + grace <= now else "retrying:missing"
            )
            continue
        status = str(row.get("status") or "unknown")
        retry_count = int(row.get("retry_count") or 0)
        if status == "posted":
            outcomes[subject] = "posted"
        elif status == "dead_letter":
            outcomes[subject] = "dead_letter:" + str(
                row.get("last_error_category") or "unknown"
            )
        elif status in {"blocked", "posting_unknown"}:
            outcomes[subject] = "blocked:" + status
        elif retry_count >= QUIZ_JOB_MAX_RETRIES:
            outcomes[subject] = "blocked:retry_policy_exhausted"
        elif due_at + grace <= now:
            outcomes[subject] = "overdue:" + status
        else:
            outcomes[subject] = "retrying:" + status
    return outcomes


def job_health_rows(logical_date: date) -> list[dict[str, Any]]:
    return [dict(row) for row in quiz_jobs_repo.list_for_date(logical_date.isoformat())]
