"""Runtime reporting and recovery orchestration for scheduled quiz jobs."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from logging import Logger
from typing import Any
from zoneinfo import ZoneInfo

from services.quiz_lifecycle import DailyHealthReport, RunOutcome, SubjectHealth
from utils.quiz_ids import build_quiz_id


def run_health_outcome(run: Mapping[str, Any] | None) -> str:
    if not run:
        return "missing"
    status = str(run.get("status") or "unknown")
    if status == "posted":
        return str(RunOutcome.ALREADY_POSTED)
    if status == "posting_unknown":
        return str(RunOutcome.POSTING_OUTCOME_UNKNOWN)
    if status in {"pending", "generating", "generated", "ready", "posting"}:
        return f"retrying:{status}"
    if status in {"generation_failed", "posting_failed", "integrity_failed"}:
        category = str(run.get("last_error_category") or status)
        prefix = "retrying" if run.get("retryable") is True else "blocked"
        return f"{prefix}:{category}"
    return f"blocked:{status}"


def daily_health_report(
    logical_date: date,
    *,
    current_hhmm: str,
    subjects: Iterable[Any],
    runs: Iterable[Mapping[str, Any]],
    outcomes: Mapping[str, str] | None = None,
) -> DailyHealthReport:
    run_by_subject = {str(run.get("subject_key")): run for run in runs}
    subject_outcomes: dict[str, str] = {}
    details: dict[str, SubjectHealth] = {}
    for subject in subjects:
        due = bool(subject.scheduled_time_ist and subject.scheduled_time_ist <= current_hhmm)
        run = run_by_subject.get(subject.key)
        outcome = "not_due" if not due else (outcomes or {}).get(subject.key, run_health_outcome(run))
        subject_outcomes[subject.key] = outcome
        details[subject.key] = SubjectHealth(
            stage=str((run or {}).get("status") or ("not_due" if not due else "missing")),
            category=(run or {}).get("last_error_category") or (outcome.split(":", 1)[1] if ":" in outcome else None),
            retry_count=int((run or {}).get("generation_attempt_count") or 0),
            last_error_at=(run or {}).get("last_error_at"),
            telegram_message_id=(run or {}).get("telegram_message_id"),
        )
    return DailyHealthReport(logical_date, subject_outcomes, details)


def durable_daily_health_report(
    logical_date: date,
    *,
    current_hhmm: str,
    subjects: Iterable[Any],
    jobs: Iterable[Mapping[str, Any]],
) -> DailyHealthReport:
    job_by_subject = {str(job.get("subject_key")): job for job in jobs}
    outcomes: dict[str, str] = {}
    details: dict[str, SubjectHealth] = {}
    for subject in subjects:
        due = bool(subject.scheduled_time_ist and subject.scheduled_time_ist <= current_hhmm)
        job = job_by_subject.get(subject.key)
        status = str((job or {}).get("status") or "missing")
        if not due:
            outcome = "not_due"
        elif not job:
            outcome = "missing"
        elif status == "posted":
            outcome = str(RunOutcome.ALREADY_POSTED)
        elif status == "posting_unknown":
            outcome = str(RunOutcome.POSTING_OUTCOME_UNKNOWN)
        elif status in {"due", "claimed", "generating", "ready", "posting", "retry_wait"}:
            outcome = f"retrying:{status}"
        else:
            outcome = f"blocked:{status}"
        outcomes[subject.key] = outcome
        details[subject.key] = SubjectHealth(
            stage=status if due else "not_due",
            category=(job or {}).get("last_error_category"),
            retry_count=int((job or {}).get("retry_count") or 0),
            last_error_at=(job or {}).get("last_error_at"),
            telegram_message_id=(job or {}).get("telegram_message_id"),
        )
    return DailyHealthReport(logical_date, outcomes, details)


def dispatch_due_jobs(
    *,
    dispatcher: Any,
    runner: Callable[..., Any],
    worker_id: str,
    logger: Logger,
    now: datetime | None = None,
) -> Any:
    result = dispatcher.dispatch_due_jobs(runner, now=now, worker_id=worker_id)
    logger.info(
        "DISPATCH_SUMMARY %s",
        json.dumps(
            {
                "date": result.logical_date.isoformat(),
                "ensured": result.ensured,
                "claimed": result.claimed,
                "actionableFailures": result.actionable_failures,
                "outcomes": result.outcomes,
                "globalOutcomes": result.global_outcomes,
            },
            sort_keys=True,
        ),
    )
    return result


def dispatch_due_jobs_with_bounded_retries(
    *,
    dispatcher: Any,
    runner: Callable[..., Any],
    worker_id: str,
    logger: Logger,
    max_passes: int,
    retry_window_seconds: int,
    clock: Callable[[], datetime] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> Any:
    """Retry database-scheduled work inside one heartbeat without busy polling."""
    if max_passes < 1:
        raise ValueError("max_passes must be at least one")
    if retry_window_seconds < 0:
        raise ValueError("retry_window_seconds cannot be negative")

    utcnow = clock or (lambda: datetime.now(timezone.utc))
    started_at = utcnow().astimezone(timezone.utc)
    deadline = started_at + timedelta(seconds=retry_window_seconds)
    result = None

    for pass_number in range(1, max_passes + 1):
        current = utcnow().astimezone(timezone.utc)
        result = dispatch_due_jobs(
            dispatcher=dispatcher,
            runner=runner,
            worker_id=worker_id,
            logger=logger,
            now=current,
        )
        retry_at = result.next_retry_at
        if retry_at is None or pass_number >= max_passes:
            break

        wake_at = retry_at.astimezone(timezone.utc) + timedelta(seconds=2)
        if wake_at > deadline:
            logger.info(
                "DISPATCH_INLINE_RETRY_DEFERRED pass=%s retry_at=%s deadline=%s",
                pass_number,
                retry_at.isoformat(),
                deadline.isoformat(),
            )
            break
        wait_seconds = max(0.0, (wake_at - utcnow().astimezone(timezone.utc)).total_seconds())
        logger.info(
            "DISPATCH_INLINE_RETRY_WAIT pass=%s wait_seconds=%.1f retry_at=%s",
            pass_number,
            wait_seconds,
            retry_at.isoformat(),
        )
        sleeper(wait_seconds)

    if result is None:  # pragma: no cover - max_passes validation guarantees a pass
        raise RuntimeError("dispatcher did not execute")
    return result


def recover_missed_quizzes(
    *,
    timezone_name: str,
    subjects: Iterable[Any],
    get_run: Callable[[str], Mapping[str, Any] | None],
    run_quiz: Callable[..., Any],
    report_health: Callable[..., DailyHealthReport],
    logger: Logger,
    now: datetime | None = None,
    pool: Any = None,
) -> tuple[dict[str, str], bool]:
    timezone = ZoneInfo(timezone_name)
    current = now or datetime.now(timezone)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone)
    localized = current.astimezone(timezone)
    today = localized.date()
    current_hhmm = localized.strftime("%H:%M")
    summary: dict[str, str] = {}
    for subject in subjects:
        if not subject.scheduled_time_ist or subject.scheduled_time_ist > current_hhmm:
            summary[subject.key] = "not_due"
            continue
        quiz_id = build_quiz_id(today, subject.key)
        run = get_run(quiz_id)
        if run and run.get("status") == "posted":
            summary[subject.key] = "already_posted"
            continue
        try:
            summary[subject.key] = str(run_quiz(subject.key, target_date=today, pool=pool))
        except Exception as exc:
            category = str(getattr(exc, "category", type(exc).__name__)).strip() or "unknown_error"
            prefix = "retrying" if bool(getattr(exc, "retryable", True)) else "blocked"
            summary[subject.key] = f"{prefix}:{category}"
    report = report_health(today, current_hhmm=current_hhmm, outcomes=summary)
    logger.info("RECOVERY_SUMMARY %s", " ".join(f"{key}={value}" for key, value in summary.items()))
    logger.info("DAILY_HEALTH_REPORT %s", json.dumps(report.as_dict(), sort_keys=True))
    logger.info("DAILY_HEALTH_REPORT_TEXT\n%s", report.as_text())
    return summary, not report.complete
