"""HTTP API and static Mini App host for the DB-backed quiz pack bot."""

from __future__ import annotations

import os
import json
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

ROOT = Path(__file__).resolve().parent

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
    return {"ok": True}


@app.get("/api/quiz/{quiz_id}")
def get_quiz(quiz_id: str) -> dict:
    pack, legacy_payload = _ensure_quiz_pack(_clean_quiz_id(quiz_id), allow_readonly_legacy=True)
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
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/leaderboard")
def leaderboard(limit: int = 20) -> dict:
    limit = max(1, min(limit, 100))
    return {"rows": stats_repo.leaderboard(limit=limit)}


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


def _ensure_quiz_pack(quiz_id: str, allow_readonly_legacy: bool) -> tuple[dict | None, dict | None]:
    """Find a DB pack, or import a legacy JSON pack into the DB if present."""
    try:
        pack = quiz_pack_service.get_quiz_pack(quiz_id)
    except (Exception, SystemExit) as exc:
        legacy_payload = _load_legacy_payload(quiz_id)
        if allow_readonly_legacy and legacy_payload:
            return None, legacy_payload
        raise HTTPException(status_code=503, detail=f"Database is not reachable: {exc}") from exc

    if pack:
        return pack, None

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
            detail=f"Legacy quiz exists, but it could not be imported into Supabase: {exc}",
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
