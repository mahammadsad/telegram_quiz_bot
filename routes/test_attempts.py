"""Authenticated timed-test attempt lifecycle routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException

from api_models import (
    AdvanceTestSectionRequest,
    SaveTestProgressRequest,
    StartTestAttemptRequest,
    SubmitTestAttemptRequest,
)
from telegram.auth import TelegramAuthError


def build_test_attempt_router(
    *,
    attempt_service: Any,
    read_user: Callable[[str], dict],
    write_user: Callable[[Any, str, str], dict],
    value_error_status: Callable[[ValueError], int],
) -> APIRouter:
    router = APIRouter(prefix="/api/tests")

    def write_failure(exc: Exception, detail: str) -> HTTPException:
        if isinstance(exc, TelegramAuthError):
            return HTTPException(status_code=401, detail=str(exc))
        if isinstance(exc, ValueError):
            return HTTPException(status_code=value_error_status(exc), detail=str(exc))
        return HTTPException(status_code=503, detail=detail)

    @router.post("/instances/{test_instance_id}/attempts/start")
    def start(test_instance_id: UUID, payload: StartTestAttemptRequest) -> dict:
        try:
            return attempt_service.start(
                write_user(payload, "test-attempt-start", str(test_instance_id)),
                test_instance_id=test_instance_id,
                client_attempt_id=payload.client_attempt_id,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise write_failure(exc, "Test attempt could not be started.") from exc

    @router.put("/attempts/{attempt_id}/progress")
    def progress(attempt_id: UUID, payload: SaveTestProgressRequest) -> dict:
        try:
            return attempt_service.save_progress(
                write_user(payload, "test-attempt-progress", str(attempt_id)),
                attempt_id=attempt_id,
                responses=[item.model_dump() for item in payload.responses],
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise write_failure(exc, "Test progress could not be saved.") from exc

    @router.post("/attempts/{attempt_id}/sections/advance")
    def advance(attempt_id: UUID, payload: AdvanceTestSectionRequest) -> dict:
        try:
            return attempt_service.advance_section(
                write_user(payload, "test-attempt-section", str(attempt_id)),
                attempt_id=attempt_id,
                next_section_instance_id=payload.next_section_instance_id,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise write_failure(exc, "Test section could not be advanced.") from exc

    @router.post("/attempts/{attempt_id}/submit")
    def submit(attempt_id: UUID, payload: SubmitTestAttemptRequest) -> dict:
        try:
            return attempt_service.submit(
                write_user(payload, "test-attempt-submit", str(attempt_id)),
                attempt_id=attempt_id,
                auto_submit=payload.auto_submit,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise write_failure(exc, "Test attempt could not be submitted.") from exc

    @router.get("/attempts/recent")
    def recent_attempts(
        limit: int = 100,
        init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> dict:
        try:
            return attempt_service.recent(read_user(init_data), limit=limit)
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Test attempt history is temporarily unavailable.",
            ) from exc

    @router.get("/attempts/{attempt_id}")
    def get_attempt(
        attempt_id: UUID,
        init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> dict:
        try:
            payload = attempt_service.get(read_user(init_data), attempt_id=attempt_id)
            if payload is None:
                raise HTTPException(status_code=404, detail="Test attempt not found.")
            return payload
        except HTTPException:
            raise
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Test attempt is temporarily unavailable.") from exc

    return router
