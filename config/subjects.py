"""Canonical subject catalogue and daily IST schedule."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubjectConfig:
    key: str
    telegram_display_name: str
    internal_subject: str | None
    quiz_enabled: bool
    scheduled_time_ist: str | None = None
    announcement_only: bool = False


_ROWS = (
    ("general", "জেনারেল তথ্য", None, False, None, True),
    ("computer", "কম্পিউটার শিক্ষা", "Computer Education", True, "07:00", False),
    ("bengali", "বাংলা", "Bengali", True, "08:00", False),
    ("reasoning", "রিজনিং", "Reasoning", True, "09:00", False),
    ("mathematics", "গণিত", "Mathematics", True, "10:00", False),
    ("english", "ইংরেজি", "English", True, "11:00", False),
    ("miscellaneous", "বিবিধ", "Miscellaneous General Knowledge", True, "12:00", False),
    ("polity", "সংবিধান ও প্রশাসন", "Indian Constitution, Polity and Governance", True, "13:00", False),
    ("geography", "ভূগোল", "Geography", True, "14:00", False),
    ("science", "বিজ্ঞান", "General Science", True, "15:00", False),
    ("economics", "অর্থনীতি", "Economics", True, "16:00", False),
    ("history", "ইতিহাস", "History", True, "17:00", False),
    ("environment", "পরিবেশ", "Environment and Ecology", True, "18:00", False),
    ("current-affairs", "কারেন্ট অ্যাফেয়ার্স", "Current Affairs", True, "19:00", False),
)

SUBJECTS: dict[str, SubjectConfig] = {
    row[0]: SubjectConfig(*row) for row in _ROWS
}
QUIZ_SUBJECTS: tuple[SubjectConfig, ...] = tuple(
    subject for subject in SUBJECTS.values() if subject.quiz_enabled
)
QUIZ_SUBJECT_KEYS: tuple[str, ...] = tuple(subject.key for subject in QUIZ_SUBJECTS)


def get_subject(subject_key: str, *, require_quiz_enabled: bool = False) -> SubjectConfig:
    try:
        subject = SUBJECTS[subject_key]
    except KeyError as exc:
        raise ValueError(f"Unknown canonical subject key: {subject_key}") from exc
    if require_quiz_enabled and not subject.quiz_enabled:
        raise ValueError(f"Subject is not quiz-enabled: {subject_key}")
    return subject


def validate_subject_catalogue() -> None:
    if len(QUIZ_SUBJECTS) != 13:
        raise RuntimeError("Subject configuration must contain exactly 13 quiz subjects.")
    keys = [row.key for row in SUBJECTS.values()]
    times = [row.scheduled_time_ist for row in QUIZ_SUBJECTS]
    names = [row.telegram_display_name for row in SUBJECTS.values()]
    if len(keys) != len(set(keys)) or len(times) != len(set(times)) or len(names) != len(set(names)):
        raise RuntimeError("Subject keys, schedule times, and Bengali display names must be unique.")
    general = SUBJECTS["general"]
    if general.quiz_enabled or not general.announcement_only:
        raise RuntimeError("general must be announcement-only.")


validate_subject_catalogue()
