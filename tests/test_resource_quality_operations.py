from __future__ import annotations

from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

import app as api_module
from scripts import check_learning_resources, discover_learning_resources
from services import resource_quality_service

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260718194113_resource_quality_operations.sql"
RESOURCE_WORKFLOW = ROOT / ".github" / "workflows" / "resource-quality.yml"
SCHEDULE_WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"
CLIENT = TestClient(api_module.app)
RESOURCE_ID = "11111111-1111-4111-8111-111111111111"


def test_resource_quality_schema_is_private_and_service_role_only():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for table in (
        "resource_feedback",
        "resource_link_checks",
        "resource_discovery_queue",
        "resource_channel_policies",
    ):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table} from public, anon, authenticated" in sql
    assert "security definer" not in sql
    for function in (
        "submit_resource_feedback",
        "get_resource_link_check_batch",
        "record_resource_link_check",
        "queue_missing_resource_discovery",
        "get_resource_discovery_batch",
        "save_youtube_resource_candidate",
        "complete_resource_discovery",
        "get_resource_review_queue",
        "review_resource_candidate",
        "get_operational_status",
    ):
        assert f"function public.{function}" in sql
    assert "v_failures >= 3" in sql
    assert "verification_status = case when v_deactivated then 'stale'" in sql
    assert "p_outcome = 'hard_failure'" in sql
    assert "'pending_review'" in sql
    assert "never" not in sql  # policy is enforced by state, not an unenforced comment


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _LinkRequester:
    def __init__(self, *, head_status: int = 200, get_status: int = 200, timeout: bool = False):
        self.head_status = head_status
        self.get_status = get_status
        self.timeout = timeout

    def head(self, *args, **kwargs):
        if self.timeout:
            raise requests.Timeout
        return _Response(self.head_status)

    def get(self, *args, **kwargs):
        if self.timeout:
            raise requests.Timeout
        return _Response(self.get_status)


@pytest.mark.parametrize(
    ("row", "requester", "outcome", "category"),
    [
        ({"url": "https://example.org", "resource_type": "article"}, _LinkRequester(), "available", "ok"),
        (
            {"url": "https://example.org/missing", "resource_type": "article"},
            _LinkRequester(head_status=404),
            "hard_failure",
            "not_found",
        ),
        (
            {"url": "https://youtube.com/watch?v=abcdefghijk", "resource_type": "youtube", "youtube_video_id": "abcdefghijk"},
            _LinkRequester(get_status=404),
            "hard_failure",
            "video_unavailable",
        ),
        (
            {"url": "https://example.org", "resource_type": "article"},
            _LinkRequester(timeout=True),
            "transient_error",
            "timeout",
        ),
    ],
)
def test_link_checker_uses_safe_failure_categories(row, requester, outcome, category):
    result = check_learning_resources.check_resource(row, requester)
    assert (result.outcome, result.error_category) == (outcome, category)


class _DiscoverySession:
    def get(self, url, **kwargs):
        if url.endswith("/search"):
            return _Response(200, {"items": [{"id": {"videoId": "abcdefghijk"}}]})
        return _Response(
            200,
            {
                "items": [
                    {
                        "id": "abcdefghijk",
                        "snippet": {
                            "title": "Database Normalization Competitive Exam",
                            "description": "A focused lesson",
                            "channelId": "trusted-channel",
                            "channelTitle": "Trusted Teacher",
                            "publishedAt": "2026-06-01T00:00:00Z",
                            "thumbnails": {"high": {"url": "https://img.example/video.jpg"}},
                        },
                        "contentDetails": {"duration": "PT12M5S"},
                        "status": {"privacyStatus": "public", "embeddable": True},
                    }
                ]
            },
        )


def test_discovery_creates_moderated_candidate_payload():
    item = {"language": "bn", "micro_topic_name": "Database Normalization"}
    candidate = discover_learning_resources.discover_candidate(
        item,
        api_key="test-key",
        policies={"trusted-channel": "preferred"},
        session=_DiscoverySession(),
    )
    assert candidate is not None
    assert candidate["p_video_id"] == "abcdefghijk"
    assert candidate["p_duration_seconds"] == 725
    assert candidate["p_quality_score"] == pytest.approx(0.9)
    assert candidate["p_relevance_score"] > 0.8


def test_discovery_helpers_are_quota_bounded_and_language_specific():
    assert discover_learning_resources.parse_duration("PT2H3M4S") == 7384
    assert discover_learning_resources.parse_duration("bad") is None
    assert "Bengali" in discover_learning_resources.build_query("bn", "Operating Systems")
    assert "Hindi" in discover_learning_resources.build_query("hi", "Operating Systems")


def test_feedback_service_validates_and_resolves_user(monkeypatch):
    monkeypatch.setattr(resource_quality_service.users_repo, "upsert_user", lambda user: {"id": "user-1"})
    captured = {}
    monkeypatch.setattr(
        resource_quality_service.resource_quality_repo,
        "submit_feedback",
        lambda user_id, **kwargs: captured.update(user_id=user_id, **kwargs) or {"accepted": True},
    )
    result = resource_quality_service.submit_feedback(
        {"id": 123, "first_name": "Test"},
        resource_id=RESOURCE_ID,
        feedback_type="low_quality",
        rating=2,
        details="  needs a clearer explanation  ",
    )
    assert result == {"accepted": True}
    assert captured["user_id"] == "user-1"
    assert captured["details"] == "needs a clearer explanation"
    with pytest.raises(ValueError):
        resource_quality_service.submit_feedback(
            {"id": 123}, resource_id=RESOURCE_ID, feedback_type="spam", rating=None, details=None
        )


def test_feedback_api_requires_telegram_auth_and_delegates(monkeypatch):
    monkeypatch.setattr(api_module, "DEV_ALLOW_UNVERIFIED_TELEGRAM", False)
    unauthenticated = CLIENT.post(
        f"/api/resources/{RESOURCE_ID}/feedback",
        json={"feedbackType": "low_quality"},
    )
    assert unauthenticated.status_code == 401

    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123})
    captured = {}
    monkeypatch.setattr(
        api_module.resource_quality_service,
        "submit_feedback",
        lambda telegram_user, **kwargs: captured.update(user=telegram_user, **kwargs) or {"accepted": True},
    )
    response = CLIENT.post(
        f"/api/resources/{RESOURCE_ID}/feedback",
        json={"initData": "signed", "feedbackType": "wrong_language", "rating": 2},
    )
    assert response.status_code == 200
    assert captured["user"] == {"id": 123}
    assert captured["resource_id"] == RESOURCE_ID


def test_admin_apis_require_auth_and_delegate_to_guarded_service(monkeypatch):
    monkeypatch.setattr(api_module, "DEV_ALLOW_UNVERIFIED_TELEGRAM", False)
    assert CLIENT.get("/api/admin/operations").status_code == 401
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 999})
    monkeypatch.setattr(
        api_module.resource_quality_service,
        "admin_operational_status",
        lambda user: {"schemaReady": True, "admin": user["id"]},
    )
    response = CLIENT.get("/api/admin/operations", headers={"X-Telegram-Init-Data": "signed"})
    assert response.status_code == 200
    assert response.json() == {"schemaReady": True, "admin": 999}


def test_resource_feedback_ui_and_maintenance_workflows_are_bounded():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    resource_workflow = RESOURCE_WORKFLOW.read_text(encoding="utf-8")
    schedule_workflow = SCHEDULE_WORKFLOW.read_text(encoding="utf-8")
    assert '"/api/resources/" + encodeURIComponent(resource.id) + "/feedback"' in html
    assert "resourceFeedbackControl(resource)" in html
    assert "youtube.googleapis.com" not in html.lower()
    assert "permissions:\n  contents: read" in resource_workflow
    assert "YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}" in resource_workflow
    assert "--limit \"$LIMIT\"" in resource_workflow
    assert schedule_workflow.count("- cron:") == 2
    assert 'cron: "30 1-13 * * *"' in schedule_workflow
    assert "python bot.py --mode export-static-fallbacks" in schedule_workflow
    assert "if: always() && needs.resolve_job.outputs.commit_fallbacks == 'true'" in schedule_workflow
    assert 'python bot.py "${args[@]}" || status=$?' in schedule_workflow
