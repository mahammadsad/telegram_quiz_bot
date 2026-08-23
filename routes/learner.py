"""Authenticated learner dashboard, practice, privacy, and preference routes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException

from api_models import (
    BookmarkRequest,
    PracticeAnswerRequest,
    PracticeQuestionReportRequest,
    PrivacyActionRequest,
    UserPreferencesRequest,
)
from telegram.auth import TelegramAuthError


def build_learner_router(
    *,
    learning_service: Any,
    moderation_service: Any,
    privacy_service: Any,
    read_user: Callable[[str], dict],
    write_user: Callable[[Any, str, str], dict],
    value_error_status: Callable[[ValueError], int],
) -> APIRouter:
    router = APIRouter(prefix="/api/me")

    def read(call: Callable[..., dict], init_data: str, detail: str, **kwargs: Any) -> dict:
        try:
            return call(read_user(init_data), **kwargs)
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=detail) from exc

    def read_validated(call: Callable[..., dict], init_data: str, detail: str, **kwargs: Any) -> dict:
        try:
            return call(read_user(init_data), **kwargs)
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status(exc), detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=detail) from exc

    @router.get("/dashboard")
    def dashboard(init_data: str = Header(default="", alias="X-Telegram-Init-Data")) -> dict:
        return read(learning_service.dashboard, init_data, "ব্যক্তিগত ড্যাশবোর্ড এখন খোলা যাচ্ছে না।")

    @router.get("/question-reports")
    def report_statuses(
        limit: int = 50,
        offset: int = 0,
        init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> dict:
        return read_validated(
            moderation_service.my_report_statuses,
            init_data,
            "রিপোর্টের অবস্থা এখন লোড করা যাচ্ছে না।",
            limit=limit,
            offset=offset,
        )

    @router.get("/reviews/due")
    def due_reviews(
        limit: int = 20, offset: int = 0, init_data: str = Header(default="", alias="X-Telegram-Init-Data")
    ) -> dict:
        return read(
            learning_service.due_reviews, init_data, "রিভিশনের প্রশ্ন এখন লোড করা যাচ্ছে না।", limit=limit, offset=offset
        )

    @router.get("/reviews/knowledge")
    def knowledge_reviews(
        limit: int = 20, offset: int = 0, init_data: str = Header(default="", alias="X-Telegram-Init-Data")
    ) -> dict:
        return read(
            learning_service.knowledge_reviews,
            init_data,
            "জ্ঞানভিত্তিক রিভিশন এখন লোড করা যাচ্ছে না।",
            limit=limit,
            offset=offset,
        )

    @router.get("/learning/daily")
    def daily_rollups(
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 30,
        offset: int = 0,
        init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> dict:
        return read_validated(
            learning_service.daily_rollups,
            init_data,
            "দৈনিক শেখার অগ্রগতি এখন লোড করা যাচ্ছে না।",
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )

    @router.get("/learning/knowledge-points")
    def knowledge_mastery(
        subject: str | None = None,
        strength: str = "all",
        limit: int = 30,
        offset: int = 0,
        init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> dict:
        return read_validated(
            learning_service.knowledge_mastery,
            init_data,
            "জ্ঞানভিত্তিক অগ্রগতি এখন লোড করা যাচ্ছে না।",
            subject_key=subject,
            strength=strength,
            limit=limit,
            offset=offset,
        )

    @router.get("/wrong-questions")
    def wrong_questions(
        subject: str | None = None,
        limit: int = 20,
        offset: int = 0,
        init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> dict:
        return read_validated(
            learning_service.wrong_questions,
            init_data,
            "ভুল প্রশ্ন এখন লোড করা যাচ্ছে না।",
            subject_key=subject,
            limit=limit,
            offset=offset,
        )

    @router.post("/practice/{question_id}")
    def submit_practice(question_id: UUID, payload: PracticeAnswerRequest) -> dict:
        try:
            return learning_service.submit_practice_answer(
                write_user(payload, "practice-answer", str(payload.attempt_id)),
                question_id=str(question_id),
                client_attempt_id=payload.attempt_id,
                selected_option=payload.selected_option,
                source_type=payload.source_type,
                mode=payload.mode,
                response_time_seconds=payload.response_time_seconds,
                marked_for_review=payload.marked_for_review,
            )
        except HTTPException:
            raise
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status(exc), detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="অনুশীলনের উত্তর সংরক্ষণ করা যায়নি।") from exc

    @router.post("/practice/{question_id}/report")
    def report_practice(question_id: UUID, payload: PracticeQuestionReportRequest) -> dict:
        try:
            return learning_service.report_practice_question(
                write_user(payload, "question-report", str(payload.attempt_id)),
                question_id=str(question_id),
                client_attempt_id=payload.attempt_id,
                reason=payload.reason,
                details=payload.details,
            )
        except HTTPException:
            raise
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ValueError as exc:
            message = str(exc)
            status = 409 if "already reported" in message else 429 if "rate limit" in message else 400
            raise HTTPException(status_code=status, detail=message) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="রিপোর্ট জমা করা যায়নি। একটু পরে আবার চেষ্টা করুন।") from exc

    @router.get("/bookmarks")
    def bookmarks(init_data: str = Header(default="", alias="X-Telegram-Init-Data")) -> dict:
        return read(learning_service.bookmarks, init_data, "বুকমার্ক এখন লোড করা যাচ্ছে না।")

    @router.post("/bookmarks")
    def set_bookmark(payload: BookmarkRequest) -> dict:
        try:
            return learning_service.set_bookmark(
                write_user(payload, "bookmark", f"{payload.item_type}:{payload.item_id}"),
                item_type=payload.item_type,
                item_id=str(payload.item_id),
                active=payload.active,
            )
        except HTTPException:
            raise
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status(exc), detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="বুকমার্ক সংরক্ষণ করা যায়নি।") from exc

    @router.get("/preferences")
    def preferences(init_data: str = Header(default="", alias="X-Telegram-Init-Data")) -> dict:
        return read(learning_service.preferences, init_data, "পছন্দের সেটিং এখন লোড করা যাচ্ছে না।")

    def privacy_action(call: Callable[[dict], dict], payload: PrivacyActionRequest, scope: str, detail: str) -> dict:
        try:
            return call(write_user(payload, scope, ""))
        except HTTPException:
            raise
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=detail) from exc

    @router.post("/data-export")
    def export_data(payload: PrivacyActionRequest) -> dict:
        return privacy_action(
            privacy_service.export_my_data, payload, "privacy-export", "আপনার ডেটা এখন এক্সপোর্ট করা যাচ্ছে না।"
        )

    @router.post("/account-deletion")
    def request_deletion(payload: PrivacyActionRequest) -> dict:
        return privacy_action(
            privacy_service.request_delete_my_account, payload, "privacy-delete", "অ্যাকাউন্ট মুছে ফেলার অনুরোধ রাখা যায়নি।"
        )

    @router.post("/account-deletion/cancel")
    def cancel_deletion(payload: PrivacyActionRequest) -> dict:
        return privacy_action(
            privacy_service.cancel_delete_my_account, payload, "privacy-delete-cancel", "অনুরোধটি বাতিল করা যায়নি।"
        )

    @router.put("/preferences")
    def save_preferences(payload: UserPreferencesRequest) -> dict:
        try:
            return learning_service.save_preferences(
                write_user(payload, "preferences", ""),
                payload.model_dump(exclude={"init_data", "dev_user"}),
            )
        except HTTPException:
            raise
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status(exc), detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="পছন্দের সেটিং সংরক্ষণ করা যায়নি।") from exc

    return router
