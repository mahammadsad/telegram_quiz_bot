from __future__ import annotations

import json
from pathlib import Path

from config.subjects import QUIZ_SUBJECT_KEYS
from config.syllabus import ALL_CHAPTERS, CHAPTERS, SYLLABUS
from config.syllabus_catalog import EXAM_TAGS
from scripts.render_syllabus_v2_migration import render_sql

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260718160722_syllabus_v2_catalogue.sql"
SOURCE_PILOT = ROOT / "sources" / "computer_education_pilot.json"


def test_catalogue_has_subject_specific_depth_instead_of_fixed_seven_chapters():
    assert tuple(SYLLABUS) == QUIZ_SUBJECT_KEYS
    chapter_counts = {key: len(chapters) for key, chapters in SYLLABUS.items()}
    assert sum(chapter_counts.values()) == 162
    assert len(set(chapter_counts.values())) >= 5
    assert min(chapter_counts.values()) >= 10
    assert max(chapter_counts.values()) >= 16
    assert sum(len(chapter.micro_topics) for chapters in SYLLABUS.values() for chapter in chapters) == 648


def test_legacy_rotation_is_preserved_while_new_coverage_is_source_gated():
    assert all(len(CHAPTERS[key]) == 7 for key in QUIZ_SUBJECT_KEYS)
    assert all(len(ALL_CHAPTERS[key]) > len(CHAPTERS[key]) for key in QUIZ_SUBJECT_KEYS)
    assert CHAPTERS["computer"] == (
        "কম্পিউটারের মৌলিক ধারণা",
        "হার্ডওয়্যার ও সফটওয়্যার",
        "অপারেটিং সিস্টেম",
        "ইন্টারনেট ও নেটওয়ার্ক",
        "MS Office",
        "ডেটাবেস",
        "সাইবার নিরাপত্তা",
    )
    assert "সংখ্যা পদ্ধতি ও ডেটা উপস্থাপন" in ALL_CHAPTERS["computer"]
    assert "সংখ্যা পদ্ধতি ও ডেটা উপস্থাপন" not in CHAPTERS["computer"]


def test_every_micro_topic_has_stable_identity_exam_mapping_and_targets():
    allowed = set(EXAM_TAGS)
    keys = set()
    for subject_key, chapters in SYLLABUS.items():
        for chapter in chapters:
            assert chapter.key.startswith(f"{subject_key}:")
            assert chapter.exam_relevance
            assert set(chapter.exam_relevance) <= allowed
            assert chapter.priority in {1, 2, 3}
            for topic in chapter.micro_topics:
                assert topic.key.startswith(f"{chapter.key}:t")
                assert topic.key not in keys
                assert set(topic.exam_relevance) <= allowed
                assert sum(topic.difficulty_targets.values()) == 10
                assert topic.target_coverage in {8, 12, 20}
                assert topic.mastery_relevance in {1.0, 1.5, 2.0}
                keys.add(topic.key)


def test_approved_computer_pilot_remains_mapped_to_legacy_core_topics():
    rows = json.loads(SOURCE_PILOT.read_text(encoding="utf-8"))
    assert len(rows) == 12
    assert {row["chapter"] for row in rows} == set(CHAPTERS["computer"])
    assert all(row["micro_topic_key"].startswith("computer:") for row in rows)
    assert all(row["micro_topic_key"].endswith(":core") for row in rows)


def test_committed_migration_is_deterministically_rendered_from_catalogue():
    assert MIGRATION.read_text(encoding="utf-8") == render_sql()


def test_migration_is_idempotent_non_destructive_and_server_only():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "13 subjects, 162 chapters, 648 new micro-topics" in sql
    assert "add column if not exists key text" in sql
    assert "on conflict (subject_key, name) do update" in sql
    assert "on conflict (key) do update" in sql
    assert "enable row level security" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert "delete from" not in sql
    assert "truncate " not in sql
    assert "drop table" not in sql
