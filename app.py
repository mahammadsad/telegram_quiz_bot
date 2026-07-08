"""HTTP API and static Mini App host for the DB-backed quiz pack bot."""

from __future__ import annotations

import os
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


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/quiz/{quiz_id}")
def get_quiz(quiz_id: str) -> dict:
    pack = quiz_pack_service.get_quiz_pack(_clean_quiz_id(quiz_id))
    if not pack:
        raise HTTPException(status_code=404, detail="Quiz pack not found.")
    return quiz_pack_service.public_quiz_payload(pack)


@app.post("/api/quiz/{quiz_id}/submit")
def submit_quiz(quiz_id: str, payload: SubmitQuizRequest) -> dict:
    try:
        telegram_user = _telegram_user_from_payload(payload)
        return quiz_pack_service.submit_quiz_attempts(_clean_quiz_id(quiz_id), telegram_user, payload.answers)
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
