from datetime import date

import pytest

from config.schedule import CRON_TO_SUBJECT, HOURLY_CRON, RECOVERY_CRON, scheduled_action
from config.subjects import QUIZ_SUBJECTS, SUBJECTS
from telegram.routing import ForumRouter, ForumRoutingError
from utils.quiz_ids import build_quiz_id, parse_quiz_id


def routing(**changes):
    values = {subject.key: index + 100 for index, subject in enumerate(QUIZ_SUBJECTS)}
    values.update(changes)
    return values


def test_exactly_thirteen_subjects_and_general_excluded():
    assert len(QUIZ_SUBJECTS) == 13
    assert not SUBJECTS["general"].quiz_enabled
    assert "general" not in {subject.key for subject in QUIZ_SUBJECTS}


def test_subject_keys_names_and_times_are_unique():
    assert len({row.key for row in QUIZ_SUBJECTS}) == 13
    assert len({row.telegram_display_name for row in SUBJECTS.values()}) == 14
    assert len({row.scheduled_time_ist for row in QUIZ_SUBJECTS}) == 13
    assert SUBJECTS["history"].telegram_display_name == "ইতিহাস"
    assert SUBJECTS["current-affairs"].telegram_display_name == "কারেন্ট অ্যাফেয়ার্স"


def test_router_accepts_numeric_complete_map():
    router = ForumRouter.from_values(__import__("json").dumps(routing()), "999")
    assert router.for_subject("history") == routing()["history"]
    assert router.general_thread_id == 999


def test_invalid_optional_general_thread_is_omitted():
    router = ForumRouter.from_values(__import__("json").dumps(routing()), "not-an-id")
    assert router.general_thread_id is None


@pytest.mark.parametrize("bad", [0, -1, True, "101", None])
def test_router_rejects_non_positive_or_non_integer(bad):
    values = routing(history=bad)
    with pytest.raises(ForumRoutingError):
        ForumRouter.from_values(__import__("json").dumps(values))


def test_router_rejects_missing_unknown_and_duplicate():
    values = routing()
    values.pop("history")
    with pytest.raises(ForumRoutingError, match="Missing"):
        ForumRouter.from_values(__import__("json").dumps(values))
    values = routing(extra=999)
    with pytest.raises(ForumRoutingError, match="Unknown"):
        ForumRouter.from_values(__import__("json").dumps(values))
    values = routing(history=100)
    with pytest.raises(ForumRoutingError, match="unique"):
        ForumRouter.from_values(__import__("json").dumps(values))


def test_router_rejects_documentation_placeholder_mapping():
    values = {subject.key: 101 + index for index, subject in enumerate(QUIZ_SUBJECTS)}
    with pytest.raises(ForumRoutingError, match="documentation-only"):
        ForumRouter.from_values(__import__("json").dumps(values))


def test_display_name_change_cannot_change_routing():
    router = ForumRouter(routing())
    assert router.for_subject("history") == 110


def test_quiz_ids_are_subject_scoped_and_legacy_readable():
    day = date(2026, 7, 10)
    ids = {build_quiz_id(day, row.key) for row in QUIZ_SUBJECTS}
    assert len(ids) == 13
    assert "20260710-history" in ids
    assert parse_quiz_id("20260710-current-affairs") == (day, "current-affairs")
    assert parse_quiz_id("20260710") == (day, None)
    with pytest.raises(ValueError):
        parse_quiz_id("20260710-general")


def test_every_cron_maps_to_immutable_subject_and_recovery_only():
    assert len(CRON_TO_SUBJECT) == 13
    for cron, subject in CRON_TO_SUBJECT.items():
        assert scheduled_action(cron) == ("subject-quiz", subject)
    assert scheduled_action(RECOVERY_CRON) == ("recover-missed-quizzes", None)
    assert scheduled_action(HOURLY_CRON) == ("recover-missed-quizzes", None)
    expected = {
        f"{(int(row.scheduled_time_ist.split(':')[1]) + 30) % 60} "
        f"{(int(row.scheduled_time_ist.split(':')[0]) - 6) % 24} * * *": row.key
        for row in QUIZ_SUBJECTS
    }
    assert CRON_TO_SUBJECT == expected
