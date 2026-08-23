"""Public quiz delivery and authenticated quiz interaction routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import JSONResponse

from api_models import ReportQuestionRequest, ResourceFeedbackRequest, StartQuizRequest, SubmitQuizRequest
from telegram.auth import TelegramAuthError


def build_quiz_router(
    *,
    quiz_service: Any,
    learning_resources_service: Any,
    resource_quality_service: Any,
    read_user: Callable[[str], dict],
    write_user: Callable[[Any, str, str], dict],
    clean_quiz_id: Callable[[str], str],
    load_public_fallback: Callable[[str], dict | None],
    mark_answer_free: Callable[[Response, object], None],
    value_error_status: Callable[[ValueError], int],
) -> APIRouter:
    router = APIRouter()

    def write_failure(exc: Exception, detail: str) -> HTTPException:
        if isinstance(exc, TelegramAuthError):
            return HTTPException(status_code=401, detail=str(exc))
        if isinstance(exc, ValueError):
            return HTTPException(status_code=value_error_status(exc), detail=str(exc))
        return HTTPException(status_code=503, detail=detail)

    @router.get("/quizzes/{quiz_file}")
    def legacy_quiz_file(quiz_file: str) -> JSONResponse:
        if not quiz_file.endswith(".json"):
            raise HTTPException(status_code=404, detail="Quiz file not found.")
        payload = load_public_fallback(clean_quiz_id(quiz_file[:-5]))
        if not payload:
            raise HTTPException(status_code=404, detail="Quiz file not found.")
        return JSONResponse(payload)

    @router.get("/api/quiz/{quiz_id}")
    def get_quiz(quiz_id: str, response: Response) -> dict:
        normalized_id = clean_quiz_id(quiz_id)
        try:
            pack = quiz_service.get_ready_quiz_pack(normalized_id)
        except Exception as exc:
            legacy = load_public_fallback(normalized_id)
            if legacy:
                mark_answer_free(response, legacy)
                return legacy
            raise HTTPException(
                status_code=503,
                detail="কুইজটি এখন খোলা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।",
            ) from exc
        if pack:
            if len(pack.get("items") or []) != 10:
                raise HTTPException(status_code=503, detail="কুইজের তথ্য অসম্পূর্ণ। পরে আবার চেষ্টা করুন।")
            payload = quiz_service.public_quiz_payload(pack)
            mark_answer_free(response, payload)
            return payload
        legacy = load_public_fallback(normalized_id)
        if legacy:
            mark_answer_free(response, legacy)
            return legacy
        raise HTTPException(status_code=404, detail="Quiz pack not found.")

    @router.get("/api/quiz/{quiz_id}/resources")
    def quiz_learning_resources(quiz_id: str) -> dict:
        normalized_id = clean_quiz_id(quiz_id)
        try:
            if not quiz_service.get_ready_quiz_pack(normalized_id):
                raise HTTPException(status_code=404, detail="Quiz pack not found.")
            return learning_resources_service.public_resources_for_quiz(normalized_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="প্রস্তুতির রিসোর্স এখন খোলা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।",
            ) from exc

    @router.post("/api/resources/{resource_id}/feedback")
    def submit_resource_feedback(resource_id: UUID, payload: ResourceFeedbackRequest) -> dict:
        try:
            return resource_quality_service.submit_feedback(
                write_user(payload, "resource-feedback", str(resource_id)),
                resource_id=str(resource_id),
                feedback_type=payload.feedback_type,
                rating=payload.rating,
                details=payload.details,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise write_failure(exc, "রিসোর্স মতামত সংরক্ষণ করা যায়নি।") from exc

    @router.post("/api/quiz/{quiz_id}/attempts/start")
    def start_quiz_attempt(quiz_id: str, payload: StartQuizRequest) -> dict:
        try:
            normalized_id = clean_quiz_id(quiz_id)
            return quiz_service.start_quiz_attempt(
                quiz_id=normalized_id,
                telegram_user=write_user(payload, "quiz-start", f"{normalized_id}:{payload.attempt_id}"),
                attempt_id=payload.attempt_id,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise write_failure(exc, "কুইজের সময় শুরু করা যায়নি। আবার চেষ্টা করুন।") from exc

    @router.post("/api/quiz/{quiz_id}/submit")
    def submit_quiz(quiz_id: str, payload: SubmitQuizRequest) -> dict:
        try:
            normalized_id = clean_quiz_id(quiz_id)
            return quiz_service.submit_quiz_attempts(
                quiz_id=normalized_id,
                telegram_user=write_user(payload, "quiz-submit", f"{normalized_id}:{payload.attempt_id}"),
                answers=payload.answers,
                attempt_id=payload.attempt_id,
                client_duration_seconds=payload.duration_seconds,
                response_times=payload.response_times,
                marked_for_review=payload.marked_for_review,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise write_failure(exc, "স্কোর জমা করা যায়নি। একটু পরে আবার চেষ্টা করুন।") from exc

    @router.get("/api/quiz/{quiz_id}/attempt/{attempt_id}")
    def get_quiz_attempt_result(
        quiz_id: str,
        attempt_id: UUID,
        init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> dict:
        try:
            result = quiz_service.get_quiz_attempt_result(
                quiz_id=clean_quiz_id(quiz_id),
                telegram_user=read_user(init_data),
                client_attempt_id=attempt_id,
            )
            if result is None:
                raise HTTPException(status_code=404, detail="এই চেষ্টার ফল পাওয়া যায়নি।")
            return result
        except HTTPException:
            raise
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=value_error_status(exc), detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="ফলাফল এখন খোলা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।",
            ) from exc

    @router.post("/api/questions/{question_id}/report")
    def report_question(question_id: UUID, payload: ReportQuestionRequest) -> dict:
        try:
            normalized_id = clean_quiz_id(payload.quiz_id)
            return quiz_service.submit_question_report(
                question_id=str(question_id),
                quiz_id=normalized_id,
                telegram_user=write_user(
                    payload,
                    "question-report",
                    f"{normalized_id}:{payload.attempt_id}",
                ),
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
            status = 409 if "already reported" in message else value_error_status(exc)
            raise HTTPException(status_code=status, detail=message) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="রিপোর্ট জমা করা যায়নি। একটু পরে আবার চেষ্টা করুন।",
            ) from exc

    return router
