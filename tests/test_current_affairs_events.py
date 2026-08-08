from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.import_source_documents import import_source_bundle, validate_source_bundle
from services.current_affairs_pipeline import (
    EVENT_POLICY_VERSION,
    authoritative_source_domain,
    build_event_bundle,
    cluster_current_affairs_rows,
    practice_pool,
)
from services.question_validation import QuizValidationError
from services.source_grounding import _validated_document
from storage import source_documents_repo

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260808103500_phase_d_current_affairs_events.sql"
)


def _body(marker: str, *, correction: bool = False) -> str:
    prefix = "Correction: " if correction else ""
    return (
        f"{prefix}On 5 August 2026, the official authority launched {marker} "
        "with a published implementation schedule and named responsible institution. "
        "The programme covers eligible participants across India and states the exact "
        "public objective, delivery mechanism, reporting period, and review date."
    )


def _event(title: str, body: str | None = None) -> dict[str, object]:
    return build_event_bundle(
        title=title,
        body=body or _body(title),
        ministry="Ministry of Science and Technology",
        source_url="https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2290999",
        published_at=datetime(2026, 8, 6, 12, tzinfo=timezone.utc),
    )


def test_event_date_is_separate_from_publication_and_claims_are_exact_spans() -> None:
    event = _event("National quantum research programme")

    assert event["event_date"] == "2026-08-05"
    assert event["publication_date"] == "2026-08-06"
    assert event["event_date_precision"] == "explicit"
    assert event["verification_policy"] == EVENT_POLICY_VERSION
    assert event["verification_status"] == "verified"
    claims = event["claims"]
    assert isinstance(claims, list) and claims
    assert all(claim["canonical_claim"] == claim["evidence_span"] for claim in claims)
    assert all(claim["verification_status"] == "verified" for claim in claims)


def test_correction_like_release_is_quarantined_for_review() -> None:
    event = _event(
        "Correction to national quantum research programme",
        _body("the national quantum research programme", correction=True),
    )

    assert event["correction_state"] == "suspected"
    assert event["review_required"] is True
    assert event["verification_status"] == "review_required"
    assert all(claim["review_required"] is True for claim in event["claims"])


def test_same_event_releases_share_one_cluster_but_keep_atomic_claims() -> None:
    first = {"current_affairs_event": _event("ISRO launches national satellite mission")}
    second = {
        "current_affairs_event": _event(
            "National satellite mission launched by ISRO",
            _body("the national satellite mission with a second official detail"),
        )
    }

    clustered = cluster_current_affairs_rows([first, second])
    left = clustered[0]["current_affairs_event"]
    right = clustered[1]["current_affairs_event"]
    assert left["cluster_key"] == right["cluster_key"]
    assert {
        claim["claim_key"] for event in (left, right) for claim in event["claims"]
    }


@pytest.mark.parametrize(
    ("age", "importance", "expected"),
    [
        (0, 3, "daily"),
        (8, 3, "weekly"),
        (31, 3, "monthly"),
        (91, 4, "six_month"),
        (91, 3, None),
        (181, 5, None),
    ],
)
def test_practice_pool_windows(age: int, importance: int, expected: str | None) -> None:
    target = date(2026, 8, 8)
    assert practice_pool(
        target.fromordinal(target.toordinal() - age),
        target_date=target,
        importance=importance,
    ) == expected


def test_current_affairs_domains_are_explicitly_allowlisted() -> None:
    assert authoritative_source_domain("https://www.rbi.org.in/Scripts/Test.aspx") == (
        "rbi.org.in"
    )
    assert authoritative_source_domain("https://cmo.wb.gov.in/") == "cmo.wb.gov.in"
    with pytest.raises(ValueError, match="authoritative registry"):
        authoritative_source_domain("https://news.example/current-affairs")


def test_current_affairs_source_bundle_requires_event_level_evidence() -> None:
    row = {
        "subject_key": "current-affairs",
        "chapter": "জাতীয় সাম্প্রতিক ঘটনা",
        "micro_topic_name": "জাতীয় নীতি ও গুরুত্বপূর্ণ ঘটনা",
        "source_url": "https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2290999",
        "source_title": "Official national programme release",
        "source_domain": "pib.gov.in",
        "source_kind": "official",
        "source_published_at": "2026-08-06T12:00:00+00:00",
        "source_accessed_at": "2026-08-06T13:00:00+00:00",
        "fact_summary": _body("the official national programme"),
        "fact_version": "pib-2290999-2026-08-06-test",
        "expires_at": "2026-09-20T23:59:59+00:00",
    }
    with pytest.raises(ValueError, match="requires current_affairs_event"):
        validate_source_bundle([row])

    row["current_affairs_event"] = _event("Official national programme release")
    assert validate_source_bundle([row])[0]["current_affairs_event"][
        "verification_policy"
    ] == EVENT_POLICY_VERSION


def test_refresh_reuses_immutable_verified_source_and_backfills_event_graph() -> None:
    row = {
        "subject_key": "current-affairs",
        "chapter": "জাতীয় সাম্প্রতিক ঘটনা",
        "micro_topic_name": "জাতীয় নীতি ও গুরুত্বপূর্ণ ঘটনা",
        "micro_topic_key": "current-affairs:national:t01",
        "source_url": "https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2290999",
        "source_title": "Official national programme release",
        "source_domain": "pib.gov.in",
        "source_kind": "official",
        "source_published_at": "2026-08-06T12:00:00+00:00",
        "source_accessed_at": "2026-08-06T13:00:00+00:00",
        "fact_summary": _body("the official national programme"),
        "fact_version": "pib-2290999-2026-08-06-test",
        "expires_at": "2026-09-20T23:59:59+00:00",
        "current_affairs_event": _event("Official national programme release"),
    }
    clean = validate_source_bundle([row])
    chapter_query = MagicMock()
    chapter_query.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "chapter-1", "subject_key": "current-affairs", "name": row["chapter"]}
    ]
    topic_query = MagicMock()
    topic_query.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "topic-1", "key": row["micro_topic_key"], "name": row["micro_topic_name"]}
    ]
    source_query = MagicMock()
    source_query.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "source-1", "verification_status": "verified"}
    ]
    rpc_query = MagicMock()
    rpc_query.execute.return_value.data = []
    client = MagicMock()
    client.table.side_effect = lambda name: {
        "quiz_chapters": chapter_query,
        "quiz_micro_topics": topic_query,
        "source_documents": source_query,
    }[name]
    client.rpc.return_value = rpc_query

    imported = import_source_bundle(clean, approve=True, client=client)

    assert imported == [{"id": "source-1", "verification_status": "verified"}]
    source_query.upsert.assert_not_called()
    assert client.rpc.call_args_list[0].args[0] == "upsert_current_affairs_event_bundle"
    assert client.rpc.call_args_list[-1].args == (
        "cache_verified_source_resources",
        {"p_subject_key": "current-affairs"},
    )


def test_phase_d_migration_has_server_only_event_claim_and_pool_contracts() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for table in (
        "current_affairs_events",
        "current_affairs_event_sources",
        "current_affairs_event_claims",
        "current_affairs_claim_evidence",
        "current_affairs_category_weights",
        "current_affairs_review_events",
    ):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "upsert_current_affairs_event_bundle" in sql
    assert "get_current_affairs_practice_pool" in sql
    assert "get_current_affairs_grounding_bundle" in sql
    assert "official_exact_span_v1" in sql
    assert "between 0 and 7 then 'daily'" in sql
    assert "between 8 and 30 then 'weekly'" in sql
    assert "between 31 and 90 then 'monthly'" in sql
    assert "between 91 and 180" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_current_affairs_grounding_uses_the_verified_event_pool(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    class Query:
        data = [{"source_document_id": "source-1", "fact_summary": "atomic claim"}]

        def execute(self):
            return self

    class Client:
        def rpc(self, name: str, payload: dict):
            calls.append((name, payload))
            return Query()

    monkeypatch.setattr(source_documents_repo, "get_client", lambda: Client())
    rows = source_documents_repo.list_grounding_bundle(
        "current-affairs",
        "জাতীয় সাম্প্রতিক ঘটনা",
        "2026-08-08",
        limit=6,
    )

    assert rows[0]["fact_summary"] == "atomic claim"
    assert calls == [
        (
            "get_current_affairs_grounding_bundle",
            {
                "p_chapter": "জাতীয় সাম্প্রতিক ঘটনা",
                "p_target_date": "2026-08-08",
                "p_limit": 6,
            },
        )
    ]


def test_verified_revision_pool_uses_event_date_not_publication_age() -> None:
    row = {
        "source_document_id": "source-1",
        "micro_topic_id": "topic-1",
        "micro_topic_key": "current-affairs:national:t01",
        "micro_topic_name": "জাতীয় নীতি ও গুরুত্বপূর্ণ ঘটনা",
        "source_url": "https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2290999",
        "source_title": "Official national programme release",
        "source_domain": "pib.gov.in",
        "source_kind": "official",
        "source_published_at": "2026-05-10T12:00:00+00:00",
        "source_accessed_at": "2026-05-10T13:00:00+00:00",
        "fact_summary": _body("the official national programme"),
        "fact_version": "pib-2290999-2026-05-10-test",
        "expires_at": "2026-09-20T23:59:59+00:00",
        "current_affairs_event_date": "2026-05-10",
        "current_affairs_practice_pool": "monthly",
        "current_affairs_verification_policy": EVENT_POLICY_VERSION,
    }

    document = _validated_document(row, "current-affairs", date(2026, 8, 8))
    assert document.current_affairs_practice_pool == "monthly"

    row["current_affairs_verification_policy"] = "unreviewed"
    with pytest.raises(QuizValidationError, match="event evidence contract"):
        _validated_document(row, "current-affairs", date(2026, 8, 8))
