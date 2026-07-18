from __future__ import annotations

from pathlib import Path

from services import learning_resources_service as service

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260718171256_learning_resources_foundation.sql"
INDEX_MIGRATION = ROOT / "supabase" / "migrations" / "20260718172756_learning_resources_fk_indexes.sql"
LEGACY_MIGRATION = ROOT / "supabase" / "migrations" / "20260718174844_learning_resources_legacy_pack_compatibility.sql"
INDEX = ROOT / "index.html"


def test_learning_resource_migration_is_cached_verified_and_server_only():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "create table if not exists public.learning_resources" in sql
    for field in (
        "subject_key", "chapter_key", "micro_topic_id", "micro_topic_key",
        "language", "resource_type", "quality_score", "relevance_score",
        "verification_status", "is_active", "approved_by", "failure_count",
    ):
        assert field in sql
    assert "alter table public.learning_resources enable row level security" in sql
    assert "revoke all on table public.learning_resources from public, anon, authenticated" in sql
    assert "grant select, insert, update, delete on table public.learning_resources to service_role" in sql
    assert "security definer" not in sql


def test_public_resource_rpc_fails_closed_and_limits_each_language():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    rpc = sql.split("function public.get_quiz_learning_resources", 1)[1]
    assert "lr.verified" in rpc
    assert "lr.verification_status = 'verified'" in rpc
    assert "lr.is_active" in rpc
    assert "partition by lr.micro_topic_id, lr.language" in rpc
    assert "least(coalesce(p_limit_per_language, 3), 3)" in rpc
    assert "left join ranked" in rpc
    assert "from public, anon, authenticated" in rpc
    assert "to service_role" in rpc


def test_every_learning_resource_foreign_key_has_a_covering_index():
    sql = (MIGRATION.read_text(encoding="utf-8") + INDEX_MIGRATION.read_text(encoding="utf-8")).lower()
    for index in (
        "idx_learning_resources_quiz_lookup",
        "idx_learning_resources_source_document",
        "idx_learning_resources_subject_key",
        "idx_learning_resources_micro_topic_key",
    ):
        assert f"create index if not exists {index}" in sql


def test_source_mirror_uses_only_operator_approved_metadata():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    cache = sql.split("function public.cache_verified_source_resources", 1)[1]
    assert "sd.verification_status = 'verified'" in cache
    assert "not sd.review_required" in cache
    assert "sd.fact_summary" not in cache
    assert "operator-approved reference used to ground this quiz topic" in cache


def test_legacy_pack_compatibility_is_exact_and_does_not_rewrite_questions():
    sql = LEGACY_MIGRATION.read_text(encoding="utf-8").lower()
    assert "legacy_c.subject_key = q.subject" in sql
    assert "legacy_c.name = q.topic" in sql
    assert "right(legacy_mt.key, 5) = ':core'" in sql
    assert "coalesce(q.micro_topic_id, keyed_mt.id, legacy_mt.id)" in sql
    assert "update public.questions" not in sql
    assert "insert into public.questions" not in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_public_projection_groups_topics_and_hides_moderation_metadata(monkeypatch):
    rows = [
        {
            "subject_key": "computer",
            "subject_name": "কম্পিউটার শিক্ষা",
            "chapter_key": "computer:cyber-security",
            "chapter_name": "সাইবার নিরাপত্তা",
            "micro_topic_key": "computer:b6d7ad7943ff:core",
            "micro_topic_name": "সাইবার নিরাপত্তা — মূল ধারণা",
            "resource_id": "resource-1",
            "language": "en",
            "resource_type": "pdf",
            "title": "Cyber Security Awareness Booklet",
            "url": "https://cybercrime.gov.in/booklet.pdf",
            "source_name": "Ministry of Home Affairs",
            "source_domain": "cybercrime.gov.in",
            "quality_score": 1,
            "relevance_score": 0.9,
            "approved_by": "operator-id",
        },
        {
            "subject_key": "computer",
            "subject_name": "কম্পিউটার শিক্ষা",
            "chapter_key": "computer:databases",
            "chapter_name": "ডেটাবেস",
            "micro_topic_key": "computer:fca3b7cc9e3c:core",
            "micro_topic_name": "ডেটাবেস — মূল ধারণা",
            "resource_id": None,
        },
    ]
    monkeypatch.setattr(service.learning_resources_repo, "list_for_quiz", lambda *args, **kwargs: rows)
    payload = service.public_resources_for_quiz("20260718-computer")
    assert payload["available"] is True
    assert payload["policy"] == {
        "cachedOnly": True,
        "verifiedOnly": True,
        "maxPerLanguagePerTopic": 3,
    }
    assert len(payload["topics"]) == 2
    assert payload["topics"][1]["resources"] == []
    public_text = str(payload).lower()
    assert "approved_by" not in public_text
    assert "quality_score" not in public_text
    assert "operator-id" not in public_text


def test_preparation_ui_uses_only_the_cached_api():
    html = INDEX.read_text(encoding="utf-8")
    assert "📚 আগে প্রস্তুতি নিন" in html
    assert "▶ মক টেস্ট শুরু করুন" in html
    assert '"/api/quiz/" + encodeURIComponent(quizId) + "/resources"' in html
    assert "কোনো লাইভ সার্চ" in html
    assert "youtube.googleapis.com" not in html.lower()
    assert "customsearch.googleapis.com" not in html.lower()
