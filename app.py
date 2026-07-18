"""Read-only quiz API, authenticated submissions, and quiz leaderboards."""


from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from config.settings import (
    APP_TIMEZONE,
    CORS_ALLOWED_ORIGINS,
    DEV_ALLOW_UNVERIFIED_TELEGRAM,
    GEMINI_FAILOVER_ENABLED,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_FORUM_TOPICS_JSON,
    TELEGRAM_GENERAL_THREAD_ID,
    TELEGRAM_INIT_DATA_MAX_AGE_SECONDS,
)
from config.subjects import QUIZ_SUBJECTS
from services import learning_resources_service, quiz_pack_service
from storage import stats_repo
from telegram.auth import TelegramAuthError, verify_init_data
from telegram.routing import ForumRouter, ForumRoutingError
from utils.quiz_ids import parse_quiz_id

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="WB Exam Quiz Pack API", version="3.2.0")
MIGRATION_VERSION = "20260718174844"

if CORS_ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )


class SubmitQuizRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    answers: list[int | None]
    dev_user: dict | None = Field(default=None, alias="devUser")
    attempt_id: str = Field(default="", alias="attemptId", max_length=80)

    model_config = {"populate_by_name": True}

    @field_validator("answers", mode="before")
    @classmethod
    def validate_answer_shape(cls, value: Any):
        if not isinstance(value, list) or len(value) != 10:
            raise ValueError("answers must contain exactly 10 entries")
        for answer in value:
            if answer is not None and (isinstance(answer, bool) or not isinstance(answer, int) or answer not in range(4)):
                raise ValueError("answers may contain only 0, 1, 2, 3, or null")
        return value


class ReportQuestionRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    quiz_id: str = Field(alias="quizId", min_length=1, max_length=80)
    attempt_id: str = Field(alias="attemptId", min_length=1, max_length=80)
    reason: str
    details: str = Field(default="", max_length=1000)
    dev_user: dict | None = Field(default=None, alias="devUser")

    model_config = {"populate_by_name": True}

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        clean = value.strip()
        if clean not in quiz_pack_service.REPORT_REASONS:
            raise ValueError("invalid report reason")
        return clean


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "index.html")


@app.get("/dashboard")
@app.get("/dashboard.html")
def dashboard() -> FileResponse:
    return FileResponse(ROOT / "dashboard.html")


@app.get("/quizzes/{quiz_file}")
def legacy_quiz_file(quiz_file: str) -> JSONResponse:
    if not quiz_file.endswith(".json"):
        raise HTTPException(status_code=404, detail="Quiz file not found.")
    quiz_id = _clean_quiz_id(quiz_file[:-5])
    payload = _load_public_fallback(quiz_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Quiz file not found.")
    return JSONResponse(payload)


@app.get("/api/health")
def health() -> dict:
    topics_error = None
    try:
        ForumRouter.from_values(TELEGRAM_FORUM_TOPICS_JSON, TELEGRAM_GENERAL_THREAD_ID)
        topics_configured = True
    except ForumRoutingError as exc:
        topics_configured = False
        topics_error = _forum_topics_error_code(exc)
    return {
        "ok": True,
        "application_version": app.version,
        "migration_version": MIGRATION_VERSION,
        "timezone": APP_TIMEZONE,
        "supabase_configured": bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")),
        "gemini_primary_configured": bool(os.environ.get("GEMINI_API_KEY_PRIMARY") or os.environ.get("GEMINI_API_KEY")),
        "gemini_secondary_configured": bool(os.environ.get("GEMINI_API_KEY_SECONDARY")),
        "gemini_failover_enabled": GEMINI_FAILOVER_ENABLED,
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN),
        "forum_topics_configured": topics_configured,
        "forum_topics_error": topics_error,
        "quiz_subject_count": len(QUIZ_SUBJECTS),
    }


@app.get("/api/quiz/{quiz_id}")
def get_quiz(quiz_id: str) -> dict:
    clean_quiz_id = _clean_quiz_id(quiz_id)
    try:
        pack = quiz_pack_service.get_quiz_pack(clean_quiz_id)
    except Exception as exc:
        legacy = _load_public_fallback(clean_quiz_id)
        if legacy:
            return legacy
        raise HTTPException(status_code=503, detail="কুইজটি এখন খোলা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।") from exc
    if pack:
        if len(pack.get("items") or []) != 10:
            raise HTTPException(status_code=503, detail="কুইজের তথ্য অসম্পূর্ণ। পরে আবার চেষ্টা করুন।")
        return quiz_pack_service.public_quiz_payload(pack)
    legacy = _load_public_fallback(clean_quiz_id)
    if legacy:
        return legacy
    raise HTTPException(status_code=404, detail="Quiz pack not found.")


@app.get("/api/quiz/{quiz_id}/resources")
def quiz_learning_resources(quiz_id: str) -> dict:
    clean_quiz_id = _clean_quiz_id(quiz_id)
    try:
        pack = quiz_pack_service.get_quiz_pack(clean_quiz_id)
        if not pack:
            raise HTTPException(status_code=404, detail="Quiz pack not found.")
        return learning_resources_service.public_resources_for_quiz(clean_quiz_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="প্রস্তুতির রিসোর্স এখন খোলা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।",
        ) from exc


@app.post("/api/quiz/{quiz_id}/submit")
def submit_quiz(quiz_id: str, payload: SubmitQuizRequest) -> dict:
    try:
        clean_quiz_id = _clean_quiz_id(quiz_id)
        telegram_user = _telegram_user_from_payload(payload)
        return quiz_pack_service.submit_quiz_attempts(
            quiz_id=clean_quiz_id,
            telegram_user=telegram_user,
            answers=payload.answers,
            attempt_id=payload.attempt_id,
        )
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="স্কোর জমা করা যায়নি। একটু পরে আবার চেষ্টা করুন।") from exc


@app.post("/api/questions/{question_id}/report")
def report_question(question_id: uuid.UUID, payload: ReportQuestionRequest) -> dict:
    try:
        clean_quiz_id = _clean_quiz_id(payload.quiz_id)
        telegram_user = _telegram_user_from_payload(payload)
        return quiz_pack_service.submit_question_report(
            question_id=str(question_id),
            quiz_id=clean_quiz_id,
            telegram_user=telegram_user,
            client_attempt_id=payload.attempt_id,
            reason=payload.reason,
            details=payload.details,
        )
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        status = 409 if "already reported" in message else 429 if "rate limit" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="রিপোর্ট জমা করা যায়নি। একটু পরে আবার চেষ্টা করুন।") from exc


@app.get("/api/quiz/{quiz_id}/leaderboard")
def quiz_leaderboard(quiz_id: str, limit: int = 20, offset: int = 0) -> dict:
    clean_quiz_id = _clean_quiz_id(quiz_id)
    try:
        return stats_repo.quiz_leaderboard(
            clean_quiz_id,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Leaderboard সাময়িকভাবে পাওয়া যাচ্ছে না।") from exc


@app.get("/api/leaderboard")
def leaderboard(limit: int = 20, offset: int = 0) -> dict:
    try:
        return {
            **stats_repo.leaderboard(
                limit=max(1, min(limit, 100)),
                offset=max(0, offset),
            ),
            "unavailable": False,
        }
    except Exception:
        return {"rows": [], "unavailable": True}


def _telegram_user_from_payload(payload: SubmitQuizRequest | ReportQuestionRequest) -> dict:
    if payload.init_data:
        return verify_init_data(payload.init_data, TELEGRAM_BOT_TOKEN, TELEGRAM_INIT_DATA_MAX_AGE_SECONDS)
    if DEV_ALLOW_UNVERIFIED_TELEGRAM:
        return payload.dev_user or {"id": 999999001, "username": "local_tester", "first_name": "Local", "last_name": "Tester"}
    raise TelegramAuthError("Open this quiz inside Telegram to submit your score.")


def _clean_quiz_id(value: str) -> str:
    quiz_id = value.strip()
    try:
        parse_quiz_id(quiz_id, allow_legacy=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid quiz id.") from exc
    return quiz_id


def _load_public_fallback(quiz_id: str) -> dict | None:
    path = ROOT / "quizzes" / f"{quiz_id}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    questions = payload.get("qs")
    if not isinstance(questions, list) or not questions:
        return None
    # Project old answer-bearing files into a public shape as an additional
    # defense while historical deployments are being migrated.
    return {
        "meta": payload.get("meta") or {"quiz_id": quiz_id},
        "capabilities": {"submission": False, "source": "static_fallback"},
        "legacy": len(quiz_id) == 8,
        "qs": [{"q": item.get("q") or item.get("question"), "o": item.get("o") or item.get("options")} for item in questions],
    }


def _forum_topics_error_code(exc: ForumRoutingError) -> str:
    """Convert routing errors to safe health codes without exposing IDs."""
    if not TELEGRAM_FORUM_TOPICS_JSON:
        return "missing"
    message = str(exc).lower()
    if "documentation-only" in message:
        return "placeholder_mapping"
    if "missing forum" in message:
        return "missing_keys"
    if "unknown subject" in message:
        return "unknown_keys"
    if "must be unique" in message:
        return "duplicate_ids"
    if "positive integer" in message:
        return "invalid_id"
    return "invalid_json"
