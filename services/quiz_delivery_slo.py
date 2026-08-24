"""Privacy-safe delivery SLOs derived from durable subject-quiz jobs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any

from config.subjects import QUIZ_SUBJECTS

_SUBJECT_KEYS = tuple(subject.key for subject in QUIZ_SUBJECTS)
_ACTIVE = frozenset({"due", "claimed", "generating", "ready", "posting", "retry_wait"})
_TERMINAL_FAILURE = frozenset({"blocked", "posting_unknown", "dead_letter"})
SLO_POLICY_VERSION = 1
DELIVERY_COMPLETENESS_TARGET = 0.99
ON_TIME_DELIVERY_TARGET = 0.95
TERMINAL_FAILURE_RATE_LIMIT = 0.01


def quiz_delivery_slo_report(
    rows: Iterable[Mapping[str, Any]],
    *,
    start_date: date,
    end_date: date,
    on_time_grace: timedelta = timedelta(minutes=30),
) -> dict[str, Any]:
    """Aggregate job delivery without exposing content, users, or Telegram IDs."""
    day_count = (end_date - start_date).days + 1
    if day_count not in range(1, 32):
        raise ValueError("SLO window must be between 1 and 31 days")
    if on_time_grace < timedelta(0) or on_time_grace > timedelta(hours=6):
        raise ValueError("on-time grace must be between zero and six hours")

    indexed: dict[tuple[date, str], Mapping[str, Any]] = {}
    for row in rows:
        logical_date = _date(row.get("logical_date"))
        subject = str(row.get("subject_key") or "")
        if logical_date < start_date or logical_date > end_date or subject not in _SUBJECT_KEYS:
            continue
        key = (logical_date, subject)
        if key in indexed:
            raise ValueError("duplicate durable job identity in SLO input")
        indexed[key] = row

    expected = day_count * len(_SUBJECT_KEYS)
    status_counts: Counter[str] = Counter()
    subject_totals: dict[str, Counter[str]] = {
        subject: Counter() for subject in _SUBJECT_KEYS
    }
    posted = 0
    on_time = 0
    terminal = 0
    retrying = 0
    daily: list[dict[str, Any]] = []
    for offset in range(day_count):
        logical_date = start_date + timedelta(days=offset)
        day_statuses: Counter[str] = Counter()
        for subject in _SUBJECT_KEYS:
            job = indexed.get((logical_date, subject))
            status = str((job or {}).get("status") or "missing")
            day_statuses[status] += 1
            status_counts[status] += 1
            subject_totals[subject][status] += 1
            if status == "posted":
                posted += 1
                due_at = _datetime(job.get("due_at")) if job else None
                posted_at = _datetime(job.get("posted_at")) if job else None
                if due_at is not None and posted_at is not None and posted_at <= due_at + on_time_grace:
                    on_time += 1
            elif status in _TERMINAL_FAILURE:
                terminal += 1
            elif status in _ACTIVE:
                retrying += 1
        daily.append({
            "logicalDate": logical_date.isoformat(),
            "posted": day_statuses["posted"],
            "missing": day_statuses["missing"],
            "terminalFailures": sum(day_statuses[value] for value in _TERMINAL_FAILURE),
            "retrying": sum(day_statuses[value] for value in _ACTIVE),
            "complete": day_statuses["posted"] == len(_SUBJECT_KEYS),
        })

    delivery_rate = _rate(posted, expected)
    on_time_rate = _rate(on_time, expected)
    terminal_rate = _rate(terminal, expected)
    evaluation = {
        "deliveryCompletenessMet": delivery_rate >= DELIVERY_COMPLETENESS_TARGET,
        "onTimeDeliveryMet": on_time_rate >= ON_TIME_DELIVERY_TARGET,
        "missingJobsMet": status_counts["missing"] == 0,
        "terminalFailureRateMet": terminal_rate <= TERMINAL_FAILURE_RATE_LIMIT,
        "unknownDeliveryMet": status_counts["posting_unknown"] == 0,
    }
    return {
        "window": {"start": start_date.isoformat(), "end": end_date.isoformat(), "days": day_count},
        "targets": {"dailySubjects": len(_SUBJECT_KEYS), "onTimeGraceMinutes": int(on_time_grace.total_seconds() // 60)},
        "objectives": {
            "policyVersion": SLO_POLICY_VERSION,
            "deliveryCompletenessRate": DELIVERY_COMPLETENESS_TARGET,
            "onTimeDeliveryRate": ON_TIME_DELIVERY_TARGET,
            "terminalFailureRateLimit": TERMINAL_FAILURE_RATE_LIMIT,
            "missingJobs": 0,
            "unknownDeliveryJobs": 0,
        },
        "summary": {
            "expectedJobs": expected,
            "recordedJobs": len(indexed),
            "postedJobs": posted,
            "onTimeJobs": on_time,
            "missingJobs": status_counts["missing"],
            "terminalFailureJobs": terminal,
            "retryingJobs": retrying,
            "completeDays": sum(1 for value in daily if value["complete"]),
            "deliveryCompletenessRate": delivery_rate,
            "onTimeDeliveryRate": on_time_rate,
            "terminalFailureRate": terminal_rate,
        },
        "evaluation": {**evaluation, "overallMet": all(evaluation.values())},
        "statusCounts": dict(sorted(status_counts.items())),
        "subjects": {
            subject: {
                "posted": counts["posted"],
                "missing": counts["missing"],
                "terminalFailures": sum(counts[value] for value in _TERMINAL_FAILURE),
            }
            for subject, counts in subject_totals.items()
        },
        "daily": daily,
    }


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("invalid logical date in SLO input") from exc


def _datetime(value: Any) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid timestamp in SLO input") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0
