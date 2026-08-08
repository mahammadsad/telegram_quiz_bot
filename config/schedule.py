"""Low-cost heartbeat cadence for the durable PostgreSQL dispatcher."""

from config.subjects import QUIZ_SUBJECTS

DISPATCHER_CRON = "*/15 * * * *"
COMPLETENESS_CRON = "0 15 * * *"
RECOVERY_CRON = COMPLETENESS_CRON


def _utc_cron_for_ist(value: str) -> str:
    hour, minute = (int(part) for part in value.split(":"))
    utc_minutes = (hour * 60 + minute - 330) % (24 * 60)
    return f"{utc_minutes % 60} {utc_minutes // 60} * * *"


CRON_TO_SUBJECT = {
    _utc_cron_for_ist(subject.scheduled_time_ist): subject.key
    for subject in QUIZ_SUBJECTS
    if subject.scheduled_time_ist
}
SUBJECT_CRONS = tuple(CRON_TO_SUBJECT)

if set(CRON_TO_SUBJECT.values()) != {subject.key for subject in QUIZ_SUBJECTS}:
    raise RuntimeError("Cron mapping must cover every quiz subject exactly once.")


def scheduled_action(cron: str) -> tuple[str, str | None]:
    if cron == DISPATCHER_CRON:
        return "dispatch-due-jobs", None
    if cron == COMPLETENESS_CRON:
        return "daily-completeness", None
    raise ValueError(f"Unknown scheduled cron expression: {cron}")
