"""Public projection of the reviewed syllabus-v2 catalogue."""

from __future__ import annotations

from config.subjects import SUBJECTS
from config.syllabus_catalog import CATALOGUE_ROWS, EXAM_TAGS, SUBJECT_EXAM_TAGS

EXAM_NAMES: dict[str, str] = {
    "WBCS": "WBCS",
    "WBPSC_CLERKSHIP": "WBPSC Clerkship",
    "WBPSC_MISC": "WBPSC Miscellaneous",
    "WBP_CONSTABLE": "WBP Constable",
    "WBP_SI": "WBP SI",
    "KOLKATA_POLICE": "Kolkata Police",
    "PRIMARY_TET": "Primary TET",
    "UPPER_PRIMARY_TET": "Upper Primary TET",
    "SSC": "SSC",
    "RAILWAY": "Railway",
    "BANKING": "Banking",
}


def syllabus_catalog(*, exam_key: str | None, subject_key: str | None) -> dict:
    """Return bounded, answer-free syllabus metadata for learner discovery."""
    clean_exam = exam_key.strip().upper() if exam_key else None
    clean_subject = subject_key.strip().lower() if subject_key else None
    if clean_exam and clean_exam not in EXAM_TAGS:
        raise ValueError("Unknown exam key.")
    if clean_subject and clean_subject not in CATALOGUE_ROWS:
        raise ValueError("Unknown subject key.")

    subjects: list[dict] = []
    for key, chapters in CATALOGUE_ROWS.items():
        exam_keys = SUBJECT_EXAM_TAGS[key]
        if clean_subject and key != clean_subject:
            continue
        if clean_exam and clean_exam not in exam_keys:
            continue
        projected_chapters = [
            {
                "key": f"{key}:{chapter_key}",
                "name": chapter_name,
                "priority": priority,
                "availableInDailyRotation": rotation_enabled,
                "microTopics": [
                    {
                        "key": f"{key}:{chapter_key}:t{index:02d}",
                        "name": micro_topic,
                    }
                    for index, micro_topic in enumerate(micro_topics, start=1)
                ],
            }
            for chapter_key, chapter_name, priority, rotation_enabled, micro_topics in chapters
        ]
        subjects.append(
            {
                "key": key,
                "name": SUBJECTS[key].telegram_display_name,
                "examKeys": list(exam_keys),
                "chapterCount": len(projected_chapters),
                "microTopicCount": sum(len(chapter[4]) for chapter in chapters),
                "availableChapterCount": sum(1 for chapter in chapters if chapter[3]),
                "chapters": projected_chapters,
            }
        )

    return {
        "version": 2,
        "exams": [{"key": key, "name": EXAM_NAMES[key]} for key in EXAM_TAGS],
        "summary": {
            "subjectCount": len(subjects),
            "chapterCount": sum(subject["chapterCount"] for subject in subjects),
            "microTopicCount": sum(subject["microTopicCount"] for subject in subjects),
            "availableChapterCount": sum(subject["availableChapterCount"] for subject in subjects),
        },
        "subjects": subjects,
    }
