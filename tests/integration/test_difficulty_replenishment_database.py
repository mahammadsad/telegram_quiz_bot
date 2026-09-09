"""Synthetic content in rollback-only transactions; never run against live data."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.database_integration


@pytest.fixture
def inventory(request):
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        chapter = conn.execute("""
            insert into public.quiz_chapters
                (subject_key, name, normalized_name, display_order)
            values ('computer', 'Difficulty test', 'difficulty test', 99001) returning id
        """).fetchone()["id"]
        topic = conn.execute(
            """
            insert into public.quiz_micro_topics (chapter_id, key, name, normalized_name)
            values (%s, 'computer:difficulty-test', 'Difficulty test', 'difficulty test') returning id
        """,
            (chapter,),
        ).fetchone()["id"]
        source = conn.execute(
            """
            insert into public.source_documents (micro_topic_id, source_url, source_title,
                source_domain, source_accessed_at, fact_summary, fact_version,
                verification_status, review_required, verified_at)
            values (%s, 'https://example.test/difficulty', 'Synthetic source', 'example.test',
                now() - interval '2 days', repeat('Synthetic test evidence. ', 4), 'test',
                'verified', false, now()) returning id
        """,
            (topic,),
        ).fetchone()["id"]
        fact = conn.execute(
            """
            insert into public.source_facts (source_document_id, fact_checksum, canonical_fact,
                evidence_span, document_version, verification_status, review_required, verified_at)
            values (%s, repeat('a', 64), 'Synthetic fact', 'Synthetic evidence', 'test',
                'verified', false, now()) returning id
        """,
            (source,),
        ).fetchone()["id"]
        for index in range(20):
            identity = f"{index:064x}"
            knowledge = conn.execute(
                """
                insert into public.knowledge_points (knowledge_key, subject_key, micro_topic_id,
                    canonical_claim, entity_key, relation_key, answer_value)
                values (%s, 'computer', %s, 'Synthetic claim', 'test', 'test', 'test') returning id
            """,
                (identity, topic),
            ).fetchone()["id"]
            conn.execute(
                """
                insert into public.knowledge_point_evidence
                    (knowledge_point_id, source_fact_id, confidence) values (%s, %s, 1)
            """,
                (knowledge, fact),
            )
            conn.execute(
                """
                insert into public.questions (question_text, option_a, option_b, option_c,
                    option_d, correct_option, subject, topic, difficulty, question_hash,
                    normalized_text, micro_topic_id, source_document_id, knowledge_point_id,
                    variant_fingerprint, stem_hash, content_hash, content_version,
                    verification_status, inventory_status, review_required)
                values (%s, 'A', 'B', 'C', 'D', 'A', 'computer', 'Difficulty test', %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, 1, 'verified', 'verified', false)
            """,
                (
                    f"Synthetic difficulty question {index}",
                    "hard"
                    if getattr(request, "param", "gap") == "balanced" and index >= 18
                    else "easy"
                    if index < 10
                    else "medium",
                    identity,
                    identity,
                    topic,
                    source,
                    knowledge,
                    identity,
                    identity,
                    identity,
                ),
            )
        try:
            yield conn, chapter, topic, source, fact
        finally:
            conn.rollback()


def _counts(conn, chapter):
    return conn.execute(
        "select * from public.get_verified_chapter_difficulty_counts() where chapter_id = %s", (chapter,)
    ).fetchone()


def test_full_total_without_hard_questions_ensures_and_returns_one_job(inventory):
    conn, chapter, topic, _, _ = inventory
    assert _counts(conn, chapter)["hard"] == 0
    assert _counts(conn, chapter)["total"] == 20
    now = datetime.now(timezone.utc)
    for _ in range(2):
        jobs = conn.execute("select * from public.ensure_due_content_replenishment_jobs(%s)", (now,)).fetchall()
        matching = [job for job in jobs if job["micro_topic_id"] == topic]
        assert len(matching) == 1
        job = matching[0]
        assert job["target_candidate_count"] == 15
        assert job["generation_batch_size"] == 5
        bundle = conn.execute("select public.get_content_replenishment_bundle(%s) as bundle", (job["id"],)).fetchone()[
            "bundle"
        ]
        assert bundle["difficulty_counts"] == {"easy": 10, "medium": 10, "hard": 0}
    assert (
        conn.execute(
            "select count(*) as n from public.content_replenishment_jobs where micro_topic_id = %s", (topic,)
        ).fetchone()["n"]
        == 1
    )


@pytest.mark.parametrize("inventory", ["balanced"], indirect=True)
def test_sufficient_difficulty_mix_does_not_create_surplus_job(inventory):
    conn, _, topic, _, _ = inventory
    jobs = conn.execute("select * from public.ensure_due_content_replenishment_jobs()").fetchall()
    assert not any(job["micro_topic_id"] == topic for job in jobs)


@pytest.mark.parametrize("gate", ["inactive_topic", "inactive_chapter", "unapproved_current_affairs", "source_review"])
def test_difficulty_gap_never_bypasses_activation_or_source_review(inventory, gate):
    conn, chapter, topic, source, _ = inventory
    if gate == "inactive_topic":
        conn.execute("update public.quiz_micro_topics set active = false where id = %s", (topic,))
    elif gate == "inactive_chapter":
        conn.execute("update public.quiz_chapters set active = false where id = %s", (chapter,))
    elif gate == "unapproved_current_affairs":
        conn.execute(
            """update public.quiz_chapters set subject_key = 'current-affairs',
            rotation_enabled = false where id = %s""",
            (chapter,),
        )
    else:
        conn.execute("update public.source_documents set review_required = true where id = %s", (source,))
    jobs = conn.execute("select * from public.ensure_due_content_replenishment_jobs()").fetchall()
    assert not any(job["micro_topic_id"] == topic for job in jobs)


@pytest.mark.parametrize("invalid", ["question", "source", "fact", "expired_fact", "expired_question", "contradicts"])
def test_capacity_excludes_unsafe_inventory(inventory, invalid):
    conn, chapter, topic, source, fact = inventory
    if invalid == "question":
        conn.execute("update public.questions set review_required = true where micro_topic_id = %s", (topic,))
    elif invalid == "source":
        conn.execute("update public.source_documents set review_required = true where id = %s", (source,))
    elif invalid == "fact":
        conn.execute("update public.source_facts set review_required = true where id = %s", (fact,))
    elif invalid == "expired_fact":
        conn.execute("update public.source_facts set effective_until = now() - interval '1 day' where id = %s", (fact,))
    elif invalid == "expired_question":
        conn.execute(
            "update public.questions set expires_at = now() - interval '1 day' where micro_topic_id = %s", (topic,)
        )
    else:
        conn.execute(
            "update public.knowledge_point_evidence set support_type = 'contradicts' where source_fact_id = %s", (fact,)
        )
    assert _counts(conn, chapter) is None


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_difficulty_counts_are_not_a_public_content_endpoint(inventory, role):
    conn, _, _, _, _ = inventory
    for signature in (
        "get_verified_chapter_difficulty_counts(timestamptz)",
        "get_content_replenishment_bundle_source_base(uuid,timestamptz,integer)",
        "get_content_replenishment_bundle(uuid,timestamptz,integer)",
    ):
        assert not conn.execute(
            "select has_function_privilege(%s, %s, 'EXECUTE') as allowed", (role, f"public.{signature}")
        ).fetchone()["allowed"]
