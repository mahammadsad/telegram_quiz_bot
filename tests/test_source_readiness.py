from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from scripts.check_source_readiness import check_source_readiness


def test_static_readiness_checks_exactly_29_selected_chapters() -> None:
    calls = []

    def loader(subject_key, chapter, target_date):
        calls.append((subject_key, chapter, target_date))
        return SimpleNamespace(documents=(object(),))

    result = check_source_readiness(
        target_date=date(2026, 7, 28),
        scope="static",
        loader=loader,
    )

    assert result == {"scope": "static", "chapters": 29, "documents": 29}
    assert len(calls) == 29
    assert all(subject_key != "current-affairs" for subject_key, _, _ in calls)


def test_full_readiness_checks_all_31_chapters_without_returning_facts() -> None:
    result = check_source_readiness(
        target_date=date(2026, 7, 28),
        scope="all",
        loader=lambda *_: SimpleNamespace(documents=(object(), object())),
    )

    assert result == {"scope": "all", "chapters": 31, "documents": 62}


def test_readiness_fails_with_only_safe_chapter_keys() -> None:
    def loader(subject_key, chapter, target_date):
        if subject_key == "economics":
            raise RuntimeError("database secret-shaped detail")
        return SimpleNamespace(documents=(object(),))

    with pytest.raises(RuntimeError) as captured:
        check_source_readiness(
            target_date=date(2026, 7, 28),
            scope="all",
            loader=loader,
        )

    assert "economics:banking-rbi" in str(captured.value)
    assert "database secret-shaped detail" not in str(captured.value)
