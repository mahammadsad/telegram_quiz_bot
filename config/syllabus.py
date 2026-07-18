"""Validated syllabus-v2 catalogue and legacy-safe rotation views."""

from __future__ import annotations

from dataclasses import dataclass

from config.subjects import QUIZ_SUBJECT_KEYS
from config.syllabus_catalog import CATALOGUE_ROWS, EXAM_TAGS, SUBJECT_EXAM_TAGS


@dataclass(frozen=True, slots=True)
class MicroTopicConfig:
    key: str
    name: str
    exam_relevance: tuple[str, ...]
    priority: int
    difficulty_targets: dict[str, int]
    target_coverage: int
    mastery_relevance: float


@dataclass(frozen=True, slots=True)
class ChapterConfig:
    key: str
    name: str
    display_order: int
    exam_relevance: tuple[str, ...]
    priority: int
    rotation_enabled: bool
    micro_topics: tuple[MicroTopicConfig, ...]


_DIFFICULTY_TARGETS = {
    1: {"easy": 4, "medium": 5, "hard": 1},
    2: {"easy": 3, "medium": 5, "hard": 2},
    3: {"easy": 2, "medium": 5, "hard": 3},
}
_TARGET_COVERAGE = {1: 8, 2: 12, 3: 20}
_MASTERY_RELEVANCE = {1: 1.0, 2: 1.5, 3: 2.0}


def _build_catalogue() -> dict[str, tuple[ChapterConfig, ...]]:
    catalogue: dict[str, tuple[ChapterConfig, ...]] = {}
    for subject_key, rows in CATALOGUE_ROWS.items():
        exam_tags = SUBJECT_EXAM_TAGS[subject_key]
        chapters = []
        for display_order, (chapter_key, name, priority, rotation_enabled, topic_names) in enumerate(rows, 1):
            topics = tuple(
                MicroTopicConfig(
                    key=f"{subject_key}:{chapter_key}:t{topic_order:02d}",
                    name=topic_name,
                    exam_relevance=exam_tags,
                    priority=priority,
                    difficulty_targets=dict(_DIFFICULTY_TARGETS[priority]),
                    target_coverage=_TARGET_COVERAGE[priority],
                    mastery_relevance=_MASTERY_RELEVANCE[priority],
                )
                for topic_order, topic_name in enumerate(topic_names, 1)
            )
            chapters.append(ChapterConfig(
                key=f"{subject_key}:{chapter_key}",
                name=name,
                display_order=display_order,
                exam_relevance=exam_tags,
                priority=priority,
                rotation_enabled=rotation_enabled,
                micro_topics=topics,
            ))
        catalogue[subject_key] = tuple(chapters)
    return catalogue


SYLLABUS: dict[str, tuple[ChapterConfig, ...]] = _build_catalogue()

# ALL_CHAPTERS is the full curriculum view. CHAPTERS remains the generation
# view used by the current selector, so newly catalogued material cannot enter
# live rotation before its source bundle is reviewed and explicitly enabled.
ALL_CHAPTERS: dict[str, tuple[str, ...]] = {
    subject_key: tuple(chapter.name for chapter in chapters)
    for subject_key, chapters in SYLLABUS.items()
}
CHAPTERS: dict[str, tuple[str, ...]] = {
    subject_key: tuple(chapter.name for chapter in chapters if chapter.rotation_enabled)
    for subject_key, chapters in SYLLABUS.items()
}


def get_chapter(subject_key: str, chapter_name: str) -> ChapterConfig:
    for chapter in SYLLABUS.get(subject_key, ()):
        if chapter.name == chapter_name:
            return chapter
    raise ValueError(f"Unknown syllabus chapter: {subject_key}/{chapter_name}")


def validate_syllabus_catalogue() -> None:
    if tuple(SYLLABUS) != QUIZ_SUBJECT_KEYS:
        raise RuntimeError("Syllabus-v2 subjects must match the 13 canonical quiz subjects in schedule order.")
    if set(SUBJECT_EXAM_TAGS) != set(QUIZ_SUBJECT_KEYS):
        raise RuntimeError("Every canonical quiz subject must have exam relevance tags.")

    allowed_tags = set(EXAM_TAGS)
    chapter_keys: set[str] = set()
    micro_topic_keys: set[str] = set()
    total_chapters = 0
    total_micro_topics = 0
    chapter_counts = set()

    for subject_key, chapters in SYLLABUS.items():
        chapter_counts.add(len(chapters))
        if len(CHAPTERS[subject_key]) < 2:
            raise RuntimeError(f"{subject_key} must retain at least two source-gated rotation chapters.")
        names: set[str] = set()
        for expected_order, chapter in enumerate(chapters, 1):
            total_chapters += 1
            if chapter.display_order != expected_order or chapter.priority not in _DIFFICULTY_TARGETS:
                raise RuntimeError(f"Invalid chapter order or priority for {chapter.key}.")
            if chapter.key in chapter_keys or chapter.name in names:
                raise RuntimeError(f"Duplicate syllabus chapter key or name: {chapter.key}.")
            if not chapter.exam_relevance or not set(chapter.exam_relevance) <= allowed_tags:
                raise RuntimeError(f"Invalid exam tags for {chapter.key}.")
            chapter_keys.add(chapter.key)
            names.add(chapter.name)
            if len(chapter.micro_topics) != 4:
                raise RuntimeError(f"Every v2 chapter must start with four curated micro-topics: {chapter.key}.")
            topic_names: set[str] = set()
            for topic in chapter.micro_topics:
                total_micro_topics += 1
                if topic.key in micro_topic_keys or topic.name in topic_names:
                    raise RuntimeError(f"Duplicate micro-topic key or name: {topic.key}.")
                if sum(topic.difficulty_targets.values()) != 10:
                    raise RuntimeError(f"Difficulty targets must total ten questions: {topic.key}.")
                if not topic.exam_relevance or not set(topic.exam_relevance) <= allowed_tags:
                    raise RuntimeError(f"Invalid micro-topic exam tags for {topic.key}.")
                micro_topic_keys.add(topic.key)
                topic_names.add(topic.name)

    if not 140 <= total_chapters <= 180:
        raise RuntimeError("Syllabus-v2 must contain 140–180 subject-specific chapters.")
    if not 600 <= total_micro_topics <= 900:
        raise RuntimeError("Syllabus-v2 must contain 600–900 curated micro-topics.")
    if len(chapter_counts) < 3:
        raise RuntimeError("Chapter counts must reflect subject scope rather than a fixed-size template.")


validate_syllabus_catalogue()
