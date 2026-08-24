import pytest

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
