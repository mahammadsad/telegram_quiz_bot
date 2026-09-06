import pytest

from config import syllabus
from services import syllabus_catalog_service


def test_full_catalogue_exposes_reviewed_hierarchy_without_assessment_answers() -> None:
    payload = syllabus_catalog_service.syllabus_catalog(exam_key=None, subject_key=None)

    assert payload["version"] == 2
    assert payload["summary"]["subjectCount"] == 13
    assert payload["summary"]["chapterCount"] == 162
    assert payload["summary"]["microTopicCount"] == 648
    assert len(payload["exams"]) == 11
    assert "correctIndex" not in str(payload)
    assert all(subject["chapters"] for subject in payload["subjects"])


def test_catalogue_filters_exam_and_subject_with_stable_topic_keys() -> None:
    payload = syllabus_catalog_service.syllabus_catalog(
        exam_key=" wbcs ",
        subject_key=" HISTORY ",
    )

    assert [subject["key"] for subject in payload["subjects"]] == ["history"]
    assert payload["subjects"][0]["chapters"][0]["microTopics"][0]["key"].startswith(
        "history:"
    )


@pytest.mark.parametrize(
    ("exam_key", "subject_key"),
    [("unknown", None), (None, "unknown")],
)
def test_catalogue_rejects_unknown_filters(exam_key: str | None, subject_key: str | None) -> None:
    with pytest.raises(ValueError):
        syllabus_catalog_service.syllabus_catalog(
            exam_key=exam_key,
            subject_key=subject_key,
        )


@pytest.mark.parametrize("stable_source_optional", [False, True])
def test_daily_availability_tracks_generation_gates(monkeypatch, stable_source_optional) -> None:
    monkeypatch.setattr(syllabus, "SOURCE_OPTIONAL_STABLE_SUBJECTS_ENABLED", stable_source_optional)
    monkeypatch.setattr(syllabus_catalog_service, "SYLLABUS", syllabus._build_catalogue())
    payload = syllabus_catalog_service.syllabus_catalog(exam_key=None, subject_key=None)
    by_subject = {subject["key"]: subject for subject in payload["subjects"]}
    current = by_subject["current-affairs"]
    assert {chapter["key"] for chapter in current["chapters"] if chapter["availableInDailyRotation"]} == {
        "current-affairs:national",
        "current-affairs:science-technology",
        "current-affairs:economy-reports",
    }
    assert current["availableChapterCount"] == 3
    history = by_subject["history"]
    assert history["availableChapterCount"] == (history["chapterCount"] if stable_source_optional else 2)
    assert payload["summary"]["availableChapterCount"] == sum(
        chapter["availableInDailyRotation"]
        for subject in payload["subjects"] for chapter in subject["chapters"]
    )
