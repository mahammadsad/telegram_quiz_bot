"""Privacy-projected public and viewer-aware leaderboard routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from models.user import User
from telegram.auth import TelegramAuthError


def build_leaderboard_router(
    *,
    stats_repo: Any,
    users_repo: Any,
    privacy_service: Any,
    subjects: Any,
    read_user: Callable[[str], dict],
    clean_quiz_id: Callable[[str], str],
) -> APIRouter:
    router = APIRouter()

    def viewer_id(init_data: str) -> str | None:
        if not init_data:
            return None
        telegram_user = read_user(init_data)
        return str(users_repo.upsert_user(User.from_telegram(telegram_user))["id"])

    @router.get("/api/quiz/{quiz_id}/leaderboard")
    def quiz_leaderboard(
        quiz_id: str,
        limit: int = 10,
        offset: int = 0,
        init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> dict:
        clean_id = clean_quiz_id(quiz_id)
        try:
            result = stats_repo.quiz_leaderboard_for_user(
                clean_id,
                user_id=viewer_id(init_data),
                limit=max(1, min(limit, 50)),
                offset=max(0, offset),
            )
            return privacy_service.project_quiz_leaderboard(result)
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=privacy_service.PRIVACY_MAINTENANCE_MESSAGE) from exc

    def typed_result(
        board_type: str,
        subject: str | None,
        limit: int,
        offset: int,
        init_data: str,
    ) -> dict:
        result = stats_repo.typed_leaderboard_for_user(
            board_type,
            subject_key=subject,
            user_id=viewer_id(init_data),
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
        )
        return {**privacy_service.project_typed_leaderboard(result), "unavailable": False}

    @router.get("/api/leaderboard")
    def overall(
        limit: int = 20,
        offset: int = 0,
        init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> dict:
        try:
            return typed_result("overall_rank", None, limit, offset, init_data)
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=privacy_service.PRIVACY_MAINTENANCE_MESSAGE) from exc

    @router.get("/api/leaderboards/{board_type}")
    def typed(
        board_type: str,
        subject: str | None = None,
        limit: int = 20,
        offset: int = 0,
        init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> dict:
        try:
            if subject and subject not in subjects:
                raise ValueError("Unknown subject key.")
            return typed_result(board_type, subject, limit, offset, init_data)
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=privacy_service.PRIVACY_MAINTENANCE_MESSAGE) from exc

    return router
