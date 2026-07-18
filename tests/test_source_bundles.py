from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.syllabus import SYLLABUS
from scripts.import_source_documents import validate_source_bundle

ROOT = Path(__file__).resolve().parents[1]
COMPUTER_EXPANSION = ROOT / "sources" / "computer_education_expansion_v2.json"
POLITY_EXPANSION = ROOT / "sources" / "polity_expansion_v2.json"
ENGLISH_EXPANSION = ROOT / "sources" / "english_expansion_v2.json"
MATHEMATICS_EXPANSION = ROOT / "sources" / "mathematics_expansion_v2.json"
EXPANSION_CHAPTER_KEYS = {
    "computer:number-systems",
    "computer:architecture-memory",
    "computer:programming",
    "computer:cloud-emerging",
    "computer:digital-services",
}
POLITY_EXPANSION_CHAPTER_KEYS = {
    "polity:making-preamble-citizenship",
    "polity:pm-council",
    "polity:state-government",
    "polity:federal-emergency",
    "polity:local-government",
    "polity:amendments-elections",
}
ENGLISH_EXPANSION_CHAPTER_KEYS = {
    "english:parts-tense",
    "english:error-correction",
    "english:spelling-usage",
    "english:cloze-comprehension",
    "english:sentence-order",
}
MATHEMATICS_EXPANSION_CHAPTER_KEYS = {
    "mathematics:simplification",
    "mathematics:average-age",
    "mathematics:partnership",
    "mathematics:mixture",
    "mathematics:algebra",
    "mathematics:geometry",
    "mathematics:mensuration",
    "mathematics:trigonometry",
    "mathematics:data-statistics",
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
POLITY_TRUSTED_DOMAINS = {
    "sansad.in",
    "legislative.gov.in",
    "mha.gov.in",
    "cabsec.gov.in",
    "jalshakti-dowr.gov.in",
    "panchayat.gov.in",
    "mohua.gov.in",
    "udma.wb.gov.in",
    "wbsec.gov.in",
    "eci.gov.in",
}
ENGLISH_TRUSTED_DOMAINS = {
    "nios.ac.in",
    "cbseacademic.nic.in",
    "dictionary.cambridge.org",
    "stylemanual.gov.au",
    "writingcenter.unc.edu",
}
MATHEMATICS_TRUSTED_DOMAINS = {
    "nios.ac.in",
    "openstax.org",
}


def _bundle_rows() -> list[dict]:
    rows = json.loads(COMPUTER_EXPANSION.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    return rows


def _polity_bundle_rows() -> list[dict]:
    rows = json.loads(POLITY_EXPANSION.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    return rows


def _english_bundle_rows() -> list[dict]:
    rows = json.loads(ENGLISH_EXPANSION.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    return rows


def _mathematics_bundle_rows() -> list[dict]:
    rows = json.loads(MATHEMATICS_EXPANSION.read_text(encoding="utf-8"))
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


def test_polity_expansion_covers_every_gated_micro_topic_exactly():
    chapters = [
        chapter for chapter in SYLLABUS["polity"]
        if chapter.key in POLITY_EXPANSION_CHAPTER_KEYS
    ]
    assert {chapter.key for chapter in chapters} == POLITY_EXPANSION_CHAPTER_KEYS
    assert all(not chapter.rotation_enabled and chapter.priority == 3 for chapter in chapters)

    expected = {
        topic.key: (chapter.name, topic.name)
        for chapter in chapters
        for topic in chapter.micro_topics
    }
    rows = _polity_bundle_rows()
    assert len(expected) == 24
    assert {row["micro_topic_key"] for row in rows} == set(expected)
    for row in rows:
        assert (row["chapter"], row["micro_topic_name"]) == expected[row["micro_topic_key"]]


def test_polity_expansion_uses_current_reviewed_official_sources():
    rows = validate_source_bundle(_polity_bundle_rows())
    assert len(rows) == 30
    assert all(row["source_kind"] == "official" for row in rows)
    assert {row["source_domain"] for row in rows} <= POLITY_TRUSTED_DOMAINS
    assert all(row["source_accessed_at"].startswith("2026-07-19T") for row in rows)
    assert all(row["expires_at"] is None for row in rows)
    assert all(len(row["fact_summary"]) >= 200 for row in rows)

    constitution_rows = [
        row for row in rows
        if row["source_domain"] == "legislative.gov.in"
    ]
    assert len(constitution_rows) == 18
    assert all(row["source_published_at"] is not None for row in constitution_rows)
    assert {
        row["source_title"] for row in constitution_rows
    } == {"The Constitution of India [As on 1st May, 2026]"}


def test_polity_composite_topics_keep_independent_sources():
    rows = _polity_bundle_rows()
    source_counts: dict[str, int] = {}
    for row in rows:
        key = row["micro_topic_key"]
        source_counts[key] = source_counts.get(key, 0) + 1
    assert source_counts["polity:making-preamble-citizenship:t04"] == 2
    assert source_counts["polity:pm-council:t04"] == 2
    assert source_counts["polity:federal-emergency:t02"] == 2
    assert source_counts["polity:local-government:t04"] == 3
    assert source_counts["polity:amendments-elections:t04"] == 2


def test_english_expansion_covers_every_gated_micro_topic_exactly():
    chapters = [
        chapter for chapter in SYLLABUS["english"]
        if chapter.key in ENGLISH_EXPANSION_CHAPTER_KEYS
    ]
    assert {chapter.key for chapter in chapters} == ENGLISH_EXPANSION_CHAPTER_KEYS
    assert all(not chapter.rotation_enabled and chapter.priority == 3 for chapter in chapters)

    expected = {
        topic.key: (chapter.name, topic.name)
        for chapter in chapters
        for topic in chapter.micro_topics
    }
    rows = _english_bundle_rows()
    assert len(expected) == 20
    assert {row["micro_topic_key"] for row in rows} == set(expected)
    for row in rows:
        assert (row["chapter"], row["micro_topic_name"]) == expected[row["micro_topic_key"]]


def test_english_expansion_uses_reviewed_official_or_primary_sources():
    rows = validate_source_bundle(_english_bundle_rows())
    assert len(rows) == 31
    assert all(row["source_kind"] in {"official", "primary"} for row in rows)
    assert {row["source_domain"] for row in rows} <= ENGLISH_TRUSTED_DOMAINS
    assert all(row["source_accessed_at"].startswith("2026-07-19T") for row in rows)
    assert all(row["expires_at"] is None for row in rows)
    assert all(len(row["fact_summary"]) >= 200 for row in rows)


def test_english_composite_topics_keep_independent_sources():
    rows = _english_bundle_rows()
    source_counts: dict[str, int] = {}
    for row in rows:
        key = row["micro_topic_key"]
        source_counts[key] = source_counts.get(key, 0) + 1
    assert source_counts["english:parts-tense:t04"] == 2
    assert source_counts["english:error-correction:t03"] == 2
    assert source_counts["english:error-correction:t04"] == 2
    assert source_counts["english:spelling-usage:t01"] == 2
    assert source_counts["english:spelling-usage:t02"] == 3
    assert source_counts["english:spelling-usage:t03"] == 4
    assert source_counts["english:spelling-usage:t04"] == 2
    assert source_counts["english:sentence-order:t04"] == 2


def test_mathematics_expansion_covers_every_gated_micro_topic_exactly():
    chapters = [
        chapter for chapter in SYLLABUS["mathematics"]
        if chapter.key in MATHEMATICS_EXPANSION_CHAPTER_KEYS
    ]
    assert {chapter.key for chapter in chapters} == MATHEMATICS_EXPANSION_CHAPTER_KEYS
    assert all(not chapter.rotation_enabled for chapter in chapters)
    assert {chapter.priority for chapter in chapters} == {2, 3}

    expected = {
        topic.key: (chapter.name, topic.name)
        for chapter in chapters
        for topic in chapter.micro_topics
    }
    rows = _mathematics_bundle_rows()
    assert len(expected) == 36
    assert {row["micro_topic_key"] for row in rows} == set(expected)
    for row in rows:
        assert (row["chapter"], row["micro_topic_name"]) == expected[row["micro_topic_key"]]


def test_mathematics_expansion_uses_reviewed_official_or_primary_sources():
    rows = validate_source_bundle(_mathematics_bundle_rows())
    assert len(rows) == 47
    assert all(row["source_kind"] in {"official", "primary"} for row in rows)
    assert {row["source_domain"] for row in rows} <= MATHEMATICS_TRUSTED_DOMAINS
    assert all(row["source_accessed_at"].startswith("2026-07-19T") for row in rows)
    assert all(row["expires_at"] is None for row in rows)
    assert all(len(row["fact_summary"]) >= 200 for row in rows)


def test_mathematics_composite_topics_keep_independent_sources():
    rows = _mathematics_bundle_rows()
    source_counts: dict[str, int] = {}
    for row in rows:
        key = row["micro_topic_key"]
        source_counts[key] = source_counts.get(key, 0) + 1
    assert source_counts["mathematics:average-age:t01"] == 2
    assert source_counts["mathematics:partnership:t02"] == 2
    assert source_counts["mathematics:partnership:t03"] == 2
    assert source_counts["mathematics:mixture:t02"] == 2
    assert source_counts["mathematics:mixture:t04"] == 2
    assert source_counts["mathematics:algebra:t01"] == 2
    assert source_counts["mathematics:algebra:t04"] == 2
    assert source_counts["mathematics:geometry:t01"] == 2
    assert source_counts["mathematics:geometry:t03"] == 2
    assert source_counts["mathematics:geometry:t04"] == 2
    assert source_counts["mathematics:trigonometry:t02"] == 2


def test_bundle_validator_rejects_duplicate_source_versions():
    rows = _bundle_rows()
    with pytest.raises(ValueError, match="duplicates a micro-topic, URL, and fact version"):
        validate_source_bundle([rows[0], dict(rows[0])])
