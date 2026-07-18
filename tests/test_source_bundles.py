from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.syllabus import SYLLABUS
from scripts.import_source_documents import validate_source_bundle

ROOT = Path(__file__).resolve().parents[1]
COMPUTER_EXPANSION = ROOT / "sources" / "computer_education_expansion_v2.json"
EXPANSION_CHAPTER_KEYS = {
    "computer:number-systems",
    "computer:architecture-memory",
    "computer:programming",
    "computer:cloud-emerging",
    "computer:digital-services",
}
TRUSTED_DOMAINS = {
    "nios.ac.in",
    "cbseacademic.nic.in",
    "nist.gov",
    "meity.gov.in",
    "cca.gov.in",
    "npci.org.in",
    "uidai.gov.in",
    "cybercrime.gov.in",
}


def _bundle_rows() -> list[dict]:
    rows = json.loads(COMPUTER_EXPANSION.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    return rows


def test_computer_expansion_covers_every_gated_micro_topic_exactly():
    chapters = [chapter for chapter in SYLLABUS["computer"] if chapter.key in EXPANSION_CHAPTER_KEYS]
    assert {chapter.key for chapter in chapters} == EXPANSION_CHAPTER_KEYS
    assert all(not chapter.rotation_enabled for chapter in chapters)

    expected = {
        topic.key: (chapter.name, topic.name)
        for chapter in chapters
        for topic in chapter.micro_topics
    }
    rows = _bundle_rows()
    assert len(expected) == 20
    assert {row["micro_topic_key"] for row in rows} == set(expected)
    for row in rows:
        assert (row["chapter"], row["micro_topic_name"]) == expected[row["micro_topic_key"]]


def test_computer_expansion_uses_reviewed_primary_or_official_sources():
    rows = validate_source_bundle(_bundle_rows())
    assert len(rows) == 26
    assert all(row["source_kind"] in {"official", "primary"} for row in rows)
    assert {row["source_domain"] for row in rows} <= TRUSTED_DOMAINS
    assert all(row["source_accessed_at"].startswith("2026-07-19T") for row in rows)
    assert all(row["expires_at"] is None for row in rows)
    assert all(len(row["fact_summary"]) >= 160 for row in rows)


def test_composite_topics_have_independent_fact_sources():
    rows = _bundle_rows()
    source_counts: dict[str, int] = {}
    for row in rows:
        key = row["micro_topic_key"]
        source_counts[key] = source_counts.get(key, 0) + 1
    assert source_counts["computer:number-systems:t04"] == 2
    assert source_counts["computer:programming:t04"] == 2
    assert source_counts["computer:cloud-emerging:t04"] == 3
    assert source_counts["computer:digital-services:t03"] == 2
    assert source_counts["computer:digital-services:t04"] == 2


def test_bundle_validator_rejects_duplicate_source_versions():
    rows = _bundle_rows()
    with pytest.raises(ValueError, match="duplicates a micro-topic, URL, and fact version"):
        validate_source_bundle([rows[0], dict(rows[0])])
