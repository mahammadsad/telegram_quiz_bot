"""UTC GitHub cron mapping derived from the canonical IST subject schedule."""

from config.subjects import QUIZ_SUBJECTS

CRON_TO_SUBJECT = {
    "30 1 * * *": "computer",
    "30 2 * * *": "bengali",
    "30 3 * * *": "reasoning",
    "30 4 * * *": "mathematics",
    "30 5 * * *": "english",
    "30 6 * * *": "miscellaneous",
    "30 7 * * *": "polity",
    "30 8 * * *": "geography",
    "30 9 * * *": "science",
    "30 10 * * *": "economics",
    "30 11 * * *": "history",
    "30 12 * * *": "environment",
    "30 13 * * *": "current-affairs",
}
RECOVERY_CRON = "0 15 * * *"

if set(CRON_TO_SUBJECT.values()) != {subject.key for subject in QUIZ_SUBJECTS}:
    raise RuntimeError("Cron mapping must cover every quiz subject exactly once.")


def scheduled_action(cron: str) -> tuple[str, str | None]:
    if cron == RECOVERY_CRON:
        return "recover-missed-quizzes", None
    try:
        return "subject-quiz", CRON_TO_SUBJECT[cron]
    except KeyError as exc:
        raise ValueError(f"Unknown scheduled cron expression: {cron}") from exc
