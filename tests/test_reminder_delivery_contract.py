from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260824033823_durable_reminder_consent_delivery.sql"
)


def test_reminder_contract_is_private_answer_free_and_bounded() -> None:
    source = MIGRATION.read_text(encoding="utf-8").lower()
    for table in ("learner_reminder_consents", "learner_reminder_deliveries"):
        assert f"alter table public.{table} enable row level security" in source
        assert f"alter table public.{table} force row level security" in source
    assert "from public, anon, authenticated" in source
    assert "to service_role" in source
    assert "unique (user_id, logical_date, reminder_kind, consent_version)" in source
    assert "attempt_count between 0 and 5" in source
    assert "max_attempts between 1 and 5" in source
    assert "least(coalesce(p_limit, 25), 100)" in source
    assert "for update of delivery skip locked" in source
    assert "deliveryenabled', false" in source
    assert "answerfreepayload', true" in source
    for forbidden in ("message_body", "question_text", "correct_option", "selected_option"):
        assert forbidden not in source


def test_reminder_contract_requires_versioned_consent_and_safe_suppression() -> None:
    source = MIGRATION.read_text(encoding="utf-8").lower()
    assert source.count("reminder-consent-v1") >= 4
    assert "preferred reminder time falls within quiet hours" in source
    assert "consent_withdrawn" in source
    assert "retry_exhausted" in source
    assert "lease_expired" in source
    assert "p_retry_after_seconds not between 30 and 86400" in source
    for permanent in ("telegram_blocked", "chat_not_found", "user_deactivated"):
        assert permanent in source


def test_reminder_product_surface_stays_disabled() -> None:
    settings_html = (ROOT / "settings.html").read_text(encoding="utf-8")
    settings_js = (ROOT / "settings.js").read_text(encoding="utf-8")
    service = (ROOT / "services" / "personal_learning_service.py").read_text(encoding="utf-8")
    assert '<input id="reminder" type="checkbox" disabled' in settings_html
    assert "dailyReminderEnabled:false" in settings_js
    assert "Daily reminders are not available until consented delivery is complete." in service
