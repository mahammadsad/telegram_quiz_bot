"""One authoritative interpretation of quiz-run and recovery outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class RunOutcome(StrEnum):
    ALREADY_POSTED = "already_posted"
    GENERATED_AND_POSTED = "generated_and_posted"
    POSTED_FROM_SAVED_QUIZ = "posted_from_saved_quiz"
    SOURCE_NOT_READY = "source_not_ready"
    ALREADY_CLAIMED = "already_claimed"
    POSTING_OUTCOME_UNKNOWN = "posting_outcome_unknown"


SUCCESSFUL_OUTCOMES = frozenset(
    {
        RunOutcome.ALREADY_POSTED,
        RunOutcome.GENERATED_AND_POSTED,
        RunOutcome.POSTED_FROM_SAVED_QUIZ,
    }
)


def is_successful_outcome(value: str | RunOutcome) -> bool:
    try:
        return RunOutcome(value) in SUCCESSFUL_OUTCOMES
    except ValueError:
        return False


def recovery_state(value: str | RunOutcome) -> str:
    """Map detailed outcomes to stable operational buckets."""
    text = str(value)
    if is_successful_outcome(text):
        return "posted"
    if text == "not_due":
        return "not_due"
    if text == RunOutcome.POSTING_OUTCOME_UNKNOWN or text.startswith("unknown:"):
        return "unknown"
    if text == RunOutcome.ALREADY_CLAIMED or text.startswith("retrying:"):
        return "retrying"
    if text == "missing":
        return "missing"
    return "blocked"


@dataclass(frozen=True, slots=True)
class SubjectHealth:
    stage: str
    category: str | None = None
    retry_count: int = 0
    last_error_at: str | None = None
    telegram_message_id: int | None = None

    def as_dict(self, outcome: str) -> dict[str, object]:
        return {
            "state": recovery_state(outcome),
            "outcome": outcome,
            "stage": self.stage,
            "category": self.category,
            "retryCount": self.retry_count,
            "lastErrorAt": self.last_error_at,
            "telegramMessageId": self.telegram_message_id,
        }


@dataclass(frozen=True, slots=True)
class DailyHealthReport:
    logical_date: date
    subjects: dict[str, str]
    details: dict[str, SubjectHealth] = field(default_factory=dict)

    @property
    def counts(self) -> dict[str, int]:
        buckets = {
            "expected": len(self.subjects),
            "posted": 0,
            "already_posted": 0,
            "newly_posted": 0,
            "retrying": 0,
            "blocked": 0,
            "unknown": 0,
            "not_due": 0,
            "missing": 0,
        }
        for outcome in self.subjects.values():
            state = recovery_state(outcome)
            if state in buckets:
                buckets[state] += 1
            else:
                buckets["missing"] += 1
            if state == "posted":
                if outcome == RunOutcome.ALREADY_POSTED:
                    buckets["already_posted"] += 1
                else:
                    buckets["newly_posted"] += 1
        return buckets

    @property
    def complete(self) -> bool:
        counts = self.counts
        due = counts["expected"] - counts["not_due"]
        return counts["posted"] == due

    def as_dict(self) -> dict[str, object]:
        return {
            "date": self.logical_date.isoformat(),
            **self.counts,
            "complete": self.complete,
            "subjects": {
                subject: self.details.get(subject, SubjectHealth(stage="unknown")).as_dict(
                    outcome
                )
                for subject, outcome in self.subjects.items()
            },
        }

    def as_text(self) -> str:
        counts = self.counts
        lines = [
            f"Date: {self.logical_date.isoformat()} IST",
            f"Expected: {counts['expected']}",
            f"Posted: {counts['posted']}",
            f"Already posted: {counts['already_posted']}",
            f"Newly posted: {counts['newly_posted']}",
            f"Retrying: {counts['retrying']}",
            f"Blocked: {counts['blocked']}",
            f"Unknown delivery: {counts['unknown']}",
            f"Not due: {counts['not_due']}",
            f"Missing: {counts['missing']}",
            "",
        ]
        for subject, outcome in self.subjects.items():
            detail = self.details.get(subject, SubjectHealth(stage="unknown"))
            category = detail.category or "none"
            last_error = detail.last_error_at or "none"
            message = (
                f" / message_id={detail.telegram_message_id}"
                if detail.telegram_message_id is not None
                else ""
            )
            lines.append(
                f"{subject}: {recovery_state(outcome)} / {detail.stage} / "
                f"{category} / attempts={detail.retry_count} / "
                f"last_error={last_error}{message}"
            )
        return "\n".join(lines)
