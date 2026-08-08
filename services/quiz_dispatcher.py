"""Durable heartbeat dispatcher for all due subject quizzes."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
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

    @property
    def actionable_failures(self) -> bool:
        return any(
            value.startswith(("blocked:", "dead_letter:", "unknown:"))
            for value in self.outcomes.values()
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
            quiz_jobs_repo.transition(
                job_id=job_id,
                worker_id=worker_id,
                target_status="generating",
                event_type="dispatch_started",
                detail={"code_sha": job.get("code_sha")},
            )
            outcome = runner(
                subject_key,
                target_date=logical_date,
                durable_job_id=job_id,
                durable_worker_id=worker_id,
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
    return DispatchResult(logical_date, len(ensured), len(claimed), outcomes)


def job_health_rows(logical_date: date) -> list[dict[str, Any]]:
    return [dict(row) for row in quiz_jobs_repo.list_for_date(logical_date.isoformat())]
