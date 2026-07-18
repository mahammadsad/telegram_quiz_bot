"""Workflow cadence and UTC reference mapping derived from subject settings."""

from config.subjects import QUIZ_SUBJECTS

HOURLY_CRON = "30 1-13 * * *"
RECOVERY_CRON = "0 15 * * *"


def _utc_cron_for_ist(value: str) -> str:
    hour, minute = (int(part) for part in value.split(":"))
    utc_minutes = (hour * 60 + minute - 330) % (24 * 60)
    return f"{utc_minutes % 60} {utc_minutes // 60} * * *"


CRON_TO_SUBJECT = {
    _utc_cron_for_ist(subject.scheduled_time_ist): subject.key
    for subject in QUIZ_SUBJECTS
    if subject.scheduled_time_ist
}

if set(CRON_TO_SUBJECT.values()) != {subject.key for subject in QUIZ_SUBJECTS}:
    raise RuntimeError("Cron mapping must cover every quiz subject exactly once.")


def scheduled_action(cron: str) -> tuple[str, str | None]:
    if cron in {HOURLY_CRON, RECOVERY_CRON}:
        return "recover-missed-quizzes", None
    try:
        return "subject-quiz", CRON_TO_SUBJECT[cron]
    except KeyError as exc:
        raise ValueError(f"Unknown scheduled cron expression: {cron}") from exc
