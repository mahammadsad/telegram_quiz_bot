"""HTTP API and static Mini App host for the DB-backed quiz pack bot."""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config.settings import (
    CORS_ALLOWED_ORIGINS,
    DEV_ALLOW_UNVERIFIED_TELEGRAM,
    TELEGRAM_INIT_DATA_MAX_AGE_SECONDS,
)
from services import quiz_pack_service
from storage import stats_repo
from telegram.auth import TelegramAuthError, verify_init_data
from utils.local_time import local_today

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("app")

app = FastAPI(title="WB Exam Quiz Pack API", version="2.0.0")

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
    answers: list[int | None] = Field(default_factory=list)
    dev_user: dict | None = Field(default=None, alias="devUser")

    model_config = {"populate_by_name": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "index.html")


@app.get("/dashboard")
@app.get("/dashboard.html")
def dashboard() -> FileResponse:
    return FileResponse(ROOT / "dashboard.html")


@app.get("/quizzes/{quiz_file}")
def legacy_quiz_file(quiz_file: str) -> FileResponse:
    if not quiz_file.endswith(".json"):
        raise HTTPException(status_code=404, detail="Legacy quiz file not found.")
    quiz_id = _clean_quiz_id(quiz_file[:-5])
    path = ROOT / "quizzes" / f"{quiz_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Legacy quiz file not found.")
    return FileResponse(path, media_type="application/json")


@app.get("/api/health")
def health() -> dict:
    today = local_today()
    return {
        "ok": True,
        "today_quiz_id": today.strftime("%Y%m%d"),
        "supabase_configured": bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")),
        "gemini_configured": bool(os.environ.get("GEMINI_API_KEY")),
        "telegram_configured": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
    }


@app.get("/api/quiz/{quiz_id}")
def get_quiz(quiz_id: str) -> dict:
    pack, legacy_payload = _ensure_quiz_pack(
        _clean_quiz_id(quiz_id),
        allow_readonly_legacy=True,
        allow_generate_today=True,
    )
    if not pack:
        if legacy_payload:
            return _public_legacy_payload(legacy_payload)
        raise HTTPException(status_code=404, detail="Quiz pack not found.")
    return quiz_pack_service.public_quiz_payload(pack)


@app.post("/api/quiz/{quiz_id}/submit")
def submit_quiz(quiz_id: str, payload: SubmitQuizRequest) -> dict:
    try:
        clean_quiz_id = _clean_quiz_id(quiz_id)
        _ensure_quiz_pack(clean_quiz_id, allow_readonly_legacy=False)
        telegram_user = _telegram_user_from_payload(payload)
        return quiz_pack_service.submit_quiz_attempts(clean_quiz_id, telegram_user, payload.answers)
    except HTTPException:
        raise
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (Exception, SystemExit) as exc:
        raise HTTPException(
            status_code=503,
            detail="স্কোর জমা করা যায়নি। একটু পরে আবার চেষ্টা করুন।",
        ) from exc


@app.get("/api/leaderboard")
def leaderboard(limit: int = 20) -> dict:
    limit = max(1, min(limit, 100))
    try:
        return {"rows": stats_repo.leaderboard(limit=limit), "unavailable": False}
    except (Exception, SystemExit):
        return {"rows": [], "unavailable": True}


def _telegram_user_from_payload(payload: SubmitQuizRequest) -> dict:
    if payload.init_data:
        return verify_init_data(
            payload.init_data,
            os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            TELEGRAM_INIT_DATA_MAX_AGE_SECONDS,
        )
    if DEV_ALLOW_UNVERIFIED_TELEGRAM:
        return payload.dev_user or {
            "id": 999999001,
            "username": "local_tester",
            "first_name": "Local",
            "last_name": "Tester",
        }
    raise TelegramAuthError("Open this quiz inside Telegram to submit your score.")


def _clean_quiz_id(value: str) -> str:
    quiz_id = "".join(ch for ch in value.strip() if ch.isalnum() or ch in ("_", "-"))
    if not quiz_id:
        raise HTTPException(status_code=400, detail="Invalid quiz id.")
    return quiz_id[:64]


def _ensure_quiz_pack(
    quiz_id: str,
    allow_readonly_legacy: bool,
    allow_generate_today: bool = False,
) -> tuple[dict | None, dict | None]:
    """Find a DB pack, generate today's missing pack, or import legacy JSON."""
    try:
        pack = quiz_pack_service.get_quiz_pack(quiz_id)
    except (Exception, SystemExit) as exc:
        if allow_generate_today and _is_today_quiz_id(quiz_id):
            return _generate_today_pack(quiz_id), None
        legacy_payload = _load_legacy_payload(quiz_id)
        if allow_readonly_legacy and legacy_payload:
            return None, legacy_payload
        raise HTTPException(
            status_code=503,
            detail="কুইজটি এখন খোলা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।",
        ) from exc

    if pack:
        return pack, None

    if allow_generate_today and _is_today_quiz_id(quiz_id):
        return _generate_today_pack(quiz_id), None

    legacy_payload = _load_legacy_payload(quiz_id)
    if not legacy_payload:
        return None, None

    try:
        pack = quiz_pack_service.record_quiz_pack(
            quiz_id,
            legacy_payload.get("qs") or [],
            legacy_payload.get("meta") or {"quiz_id": quiz_id},
            chat_id=0,
        )
        return pack, None
    except (Exception, SystemExit) as exc:
        if allow_readonly_legacy:
            return None, legacy_payload
        raise HTTPException(
            status_code=503,
            detail="কুইজটি এখন খোলা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।",
        ) from exc


def _is_today_quiz_id(quiz_id: str) -> bool:
    parsed = _quiz_date_from_id(quiz_id)
    return bool(parsed and parsed == local_today() and parsed.weekday() != 6)


def _quiz_date_from_id(quiz_id: str) -> date | None:
    if len(quiz_id) != 8 or not quiz_id.isdigit():
        return None
    try:
        return date(int(quiz_id[:4]), int(quiz_id[4:6]), int(quiz_id[6:8]))
    except ValueError:
        return None


def _generate_today_pack(quiz_id: str) -> dict:
    missing = [
        name
        for name in ("GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY")
        if not os.environ.get(name)
    ]
    if missing:
        raise HTTPException(
            status_code=503,
            detail="Server setup incomplete. Missing: " + ", ".join(missing),
        )

    target_date = _quiz_date_from_id(quiz_id)
    if not target_date:
        raise HTTPException(status_code=400, detail="Invalid quiz id.")

    try:
        from bot import ensure_quiz_pack_for_date

        return ensure_quiz_pack_for_date(target_date, chat_id=0)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (Exception, SystemExit) as exc:
        LOG.exception("Failed to auto-generate quiz pack %s.", quiz_id)
        raise HTTPException(
            status_code=503,
            detail="আজকের কুইজ তৈরি করা যায়নি। Gemini/Supabase সেটিংস ঠিক আছে কি না দেখে আবার চেষ্টা করুন।",
        ) from exc


def _load_legacy_payload(quiz_id: str) -> dict | None:
    path = ROOT / "quizzes" / f"{quiz_id}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload.get("qs"), list) or not payload["qs"]:
        return None
    payload.setdefault("meta", {})["quiz_id"] = quiz_id
    return payload


def _public_legacy_payload(payload: dict) -> dict:
    meta = payload.get("meta") or {}
    return {
        "meta": meta,
        "legacy": True,
        "qs": [
            {"q": item.get("q") or item.get("question"), "o": item.get("o") or item.get("options")}
            for item in payload.get("qs", [])
        ],
    }
