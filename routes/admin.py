"""Telegram-admin-only operational and moderation routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException

from api_models import (
    AuthoritativeQuarantineRequest,
    QuestionReviewRequest,
    ResourceReviewRequest,
)
from telegram.auth import TelegramAuthError


def build_admin_router(
    *,
    resource_service: Any,
    moderation_service: Any,
    read_user: Callable[[str], dict],
    write_user: Callable[[Any, str, str], dict],
    value_error_status: Callable[[ValueError], int],
) -> APIRouter:
    router = APIRouter(prefix="/api/admin")

    @router.get("/operations")
    def operations(init_data: str = Header(default="", alias="X-Telegram-Init-Data")) -> dict:
        try:
            return resource_service.admin_operational_status(read_user(init_data))
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Operations status is unavailable.") from exc

    @router.get("/resources/reviews")
    def resource_reviews(
        limit: int = 50,
        offset: int = 0,
        init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> dict:
        try:
            return resource_service.admin_review_queue(read_user(init_data), limit=limit, offset=offset)
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Resource review queue is unavailable.") from exc

    @router.post("/resources/{resource_id}/review")
    def review_resource(resource_id: UUID, payload: ResourceReviewRequest) -> dict:
        try:
            return resource_service.review_candidate(
                write_user(payload, "resource-review", str(resource_id)),
                resource_id=str(resource_id),
                decision=payload.decision,
            )
        except HTTPException:
            raise
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status(exc), detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Resource review could not be saved.") from exc

    @router.get("/questions/reviews")
    def question_reviews(
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> dict:
        try:
            return moderation_service.admin_review_queue(
                read_user(init_data), status=status, limit=limit, offset=offset
            )
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Question review queue is unavailable.") from exc

    @router.post("/questions/reviews/{case_id}")
    def review_question(case_id: UUID, payload: QuestionReviewRequest) -> dict:
        try:
            return moderation_service.review_case(
                write_user(payload, "question-moderation", str(case_id)),
                case_id=str(case_id),
                decision=payload.decision,
                resolution=payload.resolution,
                superseding_question_id=(
                    str(payload.superseding_question_id) if payload.superseding_question_id else None
                ),
            )
        except HTTPException:
            raise
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status(exc), detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Question review could not be saved.") from exc

    @router.post("/questions/{question_id}/quarantine")
    def quarantine(question_id: UUID, payload: AuthoritativeQuarantineRequest) -> dict:
        try:
            return moderation_service.authoritative_quarantine(
                write_user(payload, "question-moderation", str(question_id)),
                question_id=str(question_id),
                trigger=payload.trigger,
                reason=payload.reason,
                superseding_question_id=(
                    str(payload.superseding_question_id) if payload.superseding_question_id else None
                ),
            )
        except HTTPException:
            raise
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status(exc), detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Question quarantine could not be saved.") from exc

    return router
