from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import bot
from config.subjects import QUIZ_SUBJECTS
from services.gemini_provider_pool import GeminiGenerationError
from telegram.routing import ForumRouter
from utils.quiz_ids import build_quiz_id


def pack_from_questions(questions, subject_key="history", chapter="আধুনিক ভারত"):
    items = []
    for index, row in enumerate(questions):
        items.append({
            "poll": {"id": f"poll-{index}"},
            "question": {
                "id": f"q-{index}",
                "question_text": row["question"],
                "option_a": row["options"][0], "option_b": row["options"][1],
                "option_c": row["options"][2], "option_d": row["options"][3],
                "correct_option": "ABCD"[row["correct_index"]],
                "explanation": row["explanation"],
                "detailed_explanation": row["detailed_explanation"],
                "difficulty": row["difficulty"],
                "subject": subject_key,
                "topic": chapter,
            },
        })
    return {"quiz_id": "20260710-history", "meta": {"quiz_id": "20260710-history", "subject_key": subject_key, "subject": "ইতিহাস", "chapter": chapter}, "items": items}


def router():
    return ForumRouter({row.key: 100 + index for index, row in enumerate(QUIZ_SUBJECTS)})


def setup_run(monkeypatch, valid_questions, existing_run=None):
    events = []
    generated_pack = pack_from_questions(valid_questions)
    monkeypatch.setattr(bot, "validate_runtime_config", lambda **kwargs: router())
    monkeypatch.setattr(bot, "_require_gemini_provider", lambda: None)
    monkeypatch.setattr(bot.quiz_runs_repo, "get", lambda quiz_id: existing_run)
    monkeypatch.setattr(bot.quiz_runs_repo, "claim", lambda *args, **kwargs: {"worker_id": "test"})
    monkeypatch.setattr(bot, "valid_saved_pack", lambda quiz_id, run: None)
    monkeypatch.setattr(bot.quiz_runs_repo, "upsert", lambda payload: events.append(("run_upsert", payload)) or payload)
    monkeypatch.setattr(bot.quiz_runs_repo, "update_status", lambda quiz_id, status, **fields: events.append(("status", status)) or {"status": status, **fields})
    monkeypatch.setattr(bot.chapter_selector, "select_chapter", lambda *args: "আধুনিক ভারত")
    monkeypatch.setattr(bot.chapter_history_repo, "record", lambda *args: events.append(("chapter", args)))
    monkeypatch.setattr(bot, "generate_mcqs", lambda *args, **kwargs: (valid_questions, {"provider": "primary", "model": "model", "attempts": 1}))
    monkeypatch.setattr(bot.quiz_pack_service, "record_quiz_pack", lambda *args, **kwargs: events.append(("save_pack", None)) or generated_pack)
    monkeypatch.setattr(bot, "export_static_quiz_json", lambda pack: events.append(("export", None)))
    monkeypatch.setattr(bot.quiz_pack_service, "mark_pack_posted", lambda pack: events.append(("mark_used", None)))
    monkeypatch.setattr(bot, "telegram_api", lambda method, payload: events.append(("telegram", payload)) or {"ok": True, "result": {"message_id": 55, "message_thread_id": payload["message_thread_id"], "chat": {"id": -100}}})
    return events, generated_pack


def test_save_export_and_generated_state_precede_telegram(monkeypatch, valid_questions):
    events, _ = setup_run(monkeypatch, valid_questions)
    result = bot.run_subject_quiz("history", target_date=date(2026, 7, 10))
    labels = [event[0] if event[0] != "status" else event[1] for event in events]
    assert result == "generated_and_posted"
    assert labels.index("save_pack") < labels.index("generated") < labels.index("export") < labels.index("telegram") < labels.index("posted")
    telegram_payload = next(event[1] for event in events if event[0] == "telegram")
    assert isinstance(telegram_payload["message_thread_id"], int)
    assert telegram_payload["message_thread_id"] == router().for_subject("history")


def test_force_post_reuses_saved_pack_without_gemini(monkeypatch, valid_questions):
    existing = {"status": "posting_failed", "content_checksum": "checksum"}
    events, saved = setup_run(monkeypatch, valid_questions, existing_run=existing)
    monkeypatch.setattr(bot, "valid_saved_pack", lambda quiz_id, run: saved)
    monkeypatch.setattr(bot, "generate_mcqs", lambda *args, **kwargs: pytest.fail("Gemini was called"))
    assert bot.run_subject_quiz("history", target_date=date(2026, 7, 10), force_post=True) == "posted_from_saved_quiz"
    assert any(event[0] == "telegram" for event in events)


def test_force_regenerate_uses_explicit_replacement_path(monkeypatch, valid_questions):
    existing = {"status": "generated", "content_checksum": "old"}
    events, _ = setup_run(monkeypatch, valid_questions, existing_run=existing)
    replacements = []
    generated_pack = pack_from_questions(valid_questions)
    monkeypatch.setattr(
        bot.quiz_pack_service,
        "record_quiz_pack",
        lambda *args, **kwargs: replacements.append(kwargs["replace"]) or generated_pack,
    )
    result = bot.run_subject_quiz("history", target_date=date(2026, 7, 10), force_regenerate=True)
    assert result == "generated_and_posted"
    assert replacements == [True]
    assert not any(event[0] == "run_upsert" for event in events)


def test_unknown_post_outcome_requires_review_and_never_reposts(monkeypatch, valid_questions):
    existing = {"status": "posting_unknown", "content_checksum": "checksum"}
    events, saved = setup_run(monkeypatch, valid_questions, existing_run=existing)
    monkeypatch.setattr(bot, "valid_saved_pack", lambda quiz_id, run: saved)
    result = bot.run_subject_quiz("history", target_date=date(2026, 7, 10))
    assert result == "posting_outcome_unknown"
    assert not any(event[0] == "telegram" for event in events)


def test_ambiguous_telegram_failure_is_not_automatically_retryable(monkeypatch, valid_questions):
    events, _ = setup_run(monkeypatch, valid_questions)
    monkeypatch.setattr(
        bot,
        "telegram_api",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            bot.TelegramPostingError("timeout", delivery_uncertain=True)
        ),
    )
    with pytest.raises(bot.TelegramPostingError):
        bot.run_subject_quiz("history", target_date=date(2026, 7, 10))
    assert ("status", "posting_unknown") in events


def test_both_providers_failing_never_posts_quiz(monkeypatch, valid_questions):
    events, _ = setup_run(monkeypatch, valid_questions)
    error = GeminiGenerationError("transient", [{"provider": "primary"}, {"provider": "secondary"}], retryable=True)
    monkeypatch.setattr(bot, "generate_mcqs", lambda *args, **kwargs: (_ for _ in ()).throw(error))
    monkeypatch.setattr(bot, "send_failure_alert", lambda *args: events.append(("alert", None)))
    with pytest.raises(GeminiGenerationError):
        bot.run_subject_quiz("history", target_date=date(2026, 7, 10))
    assert not any(event[0] == "telegram" for event in events)
    assert ("status", "generation_failed") in events
    assert ("alert", None) in events


def test_public_static_export_contains_no_answer_key(monkeypatch, tmp_path, valid_questions):
    saved = pack_from_questions(valid_questions)
    monkeypatch.setattr(bot, "ROOT", tmp_path)
    monkeypatch.setattr(bot, "WRITE_STATIC_QUIZ_JSON", True)
    path = bot.export_static_quiz_json(saved)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["qs"]) == 10
    assert all(set(row) == {"q", "o"} for row in payload["qs"])
    assert "correct" not in path.read_text(encoding="utf-8")


def test_malformed_json_gets_at_most_one_repair(monkeypatch, valid_questions):
    class Pool:
        def __init__(self): self.calls = 0
        def generate_subject_quiz(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "not-json", {}
            return json.dumps(valid_questions, ensure_ascii=False), {"provider": "secondary", "model": "m", "attempts": 2}
    pool = Pool()
    clean, _ = bot.generate_mcqs("history", "আধুনিক ভারত", pool=pool)
    assert len(clean) == 10 and pool.calls == 2


def test_invalid_repaired_json_is_never_accepted():
    class Pool:
        def __init__(self):
            self.calls = 0

        def generate_subject_quiz(self, **kwargs):
            self.calls += 1
            return "still-bad", {}

    pool = Pool()
    with pytest.raises(bot.QuizValidationError):
        bot.generate_mcqs("history", "আধুনিক ভারত", pool=pool)
    assert pool.calls == 2


def test_recovery_only_processes_due_and_skips_posted(monkeypatch):
    now = datetime(2026, 7, 10, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    posted_id = build_quiz_id(now.date(), "bengali")
    monkeypatch.setattr(bot.quiz_runs_repo, "get", lambda quiz_id: {"status": "posted"} if quiz_id == posted_id else None)
    monkeypatch.setattr(bot, "valid_saved_pack", lambda *args: None)
    called = []
    monkeypatch.setattr(bot, "run_subject_quiz", lambda subject_key, **kwargs: called.append(subject_key) or "generated_and_posted")
    summary, unresolved = bot.recover_missed_quizzes(now=now)
    assert called == ["computer", "reasoning", "mathematics"]
    assert summary["bengali"] == "already_posted"
    assert summary["english"] == "not_due"
    assert not unresolved


def test_recovery_reports_active_or_unknown_post_as_unresolved(monkeypatch):
    now = datetime(2026, 7, 10, 7, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    monkeypatch.setattr(bot.quiz_runs_repo, "get", lambda quiz_id: None)
    monkeypatch.setattr(bot, "valid_saved_pack", lambda *args: None)
    monkeypatch.setattr(bot, "run_subject_quiz", lambda *args, **kwargs: "already_claimed")
    summary, unresolved = bot.recover_missed_quizzes(now=now)
    assert summary["computer"] == "already_claimed"
    assert unresolved


def test_database_preflight_checks_all_migration_tables(monkeypatch):
    checked = []

    class Query:
        def select(self, identifier):
            checked.append((self.table, identifier))
            return self
        def limit(self, _value): return self
        def execute(self): return object()

    class Client:
        def table(self, table):
            query = Query()
            query.table = table
            return query

    monkeypatch.setattr(bot, "get_client", lambda: Client())
    bot.validate_database_schema()
    assert checked == [
        ("quiz_runs", "quiz_id"),
        ("chapter_history", "id"),
        ("quiz_submissions", "id,client_attempt_id"),
        ("quiz_questions", "id,quiz_id,question_order"),
        ("quiz_attempts", "id,client_attempt_id,attempt_number"),
        ("quiz_attempt_answers", "id,attempt_id,question_order"),
    ]
