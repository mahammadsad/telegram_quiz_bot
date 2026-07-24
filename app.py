"""Quiz delivery, authenticated learning workflows, and safe leaderboards."""


from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from config.settings import (
    APP_TIMEZONE,
    CORS_ALLOWED_ORIGINS,
    DEV_ALLOW_UNVERIFIED_TELEGRAM,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_INIT_DATA_MAX_AGE_SECONDS,
    TELEGRAM_WRITE_INIT_DATA_MAX_AGE_SECONDS,
)
from config.subjects import SUBJECTS
from database.contract import APPLICATION_VERSION, REQUIRED_MIGRATION_VERSION
from models.user import User
from services import (
    learning_resources_service,
    personal_learning_service,
    quiz_pack_service,
    rate_limit,
    readiness_service,
    resource_quality_service,
)
from storage import stats_repo, users_repo
from telegram.auth import TelegramAuthError, verify_init_data
from utils.quiz_ids import parse_quiz_id

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="WB Exam Quiz Pack API", version=APPLICATION_VERSION)
# Backward-compatible import for older tests/operators; the value has one source.
MIGRATION_VERSION = REQUIRED_MIGRATION_VERSION

if CORS_ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def security_and_privacy_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://telegram.org; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors https://web.telegram.org https://*.telegram.org"
    )
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if request.url.scheme == "https" or forwarded_proto == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if (
        request.url.path.startswith("/api/me/")
        or request.url.path.startswith("/api/admin/")
        or bool(request.headers.get("x-telegram-init-data"))
        or request.method not in {"GET", "HEAD", "OPTIONS"}
    ):
        response.headers["Cache-Control"] = "no-store, private"
    return response


class SubmitQuizRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    answers: list[int | None]
    dev_user: dict | None = Field(default=None, alias="devUser")
    attempt_id: uuid.UUID = Field(alias="attemptId")
    duration_seconds: int | None = Field(default=None, alias="durationSeconds", ge=0, le=86400)
    response_times: list[float | None] | None = Field(default=None, alias="responseTimes")
    marked_for_review: list[bool] | None = Field(default=None, alias="markedForReview")

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

    @field_validator("response_times", mode="before")
    @classmethod
    def validate_response_times(cls, value: Any):
        if value is None:
            return None
        if not isinstance(value, list) or len(value) != 10:
            raise ValueError("responseTimes must contain exactly 10 entries")
        for seconds in value:
            if seconds is not None and (
                isinstance(seconds, bool)
                or not isinstance(seconds, (int, float))
                or not 0 <= seconds <= 3600
            ):
                raise ValueError("responseTimes entries must be between 0 and 3600 seconds")
        return value

    @field_validator("marked_for_review", mode="before")
    @classmethod
    def validate_marked_for_review(cls, value: Any):
        if value is None:
            return None
        if not isinstance(value, list) or len(value) != 10 or any(type(item) is not bool for item in value):
            raise ValueError("markedForReview must contain exactly 10 booleans")
        return value


class ReportQuestionRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    quiz_id: str = Field(alias="quizId", min_length=1, max_length=80)
    attempt_id: uuid.UUID = Field(alias="attemptId")
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


class BookmarkRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    item_type: str = Field(alias="itemType")
    item_id: uuid.UUID = Field(alias="itemId")
    active: bool = True
    dev_user: dict | None = Field(default=None, alias="devUser")

    model_config = {"populate_by_name": True}


class UserPreferencesRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    target_exams: list[str] = Field(default_factory=list, alias="targetExams", max_length=11)
    preferred_subjects: list[str] = Field(default_factory=list, alias="preferredSubjects", max_length=13)
    daily_question_target: int = Field(default=30, alias="dailyQuestionTarget", ge=1, le=130)
    preferred_language: str = Field(default="bn", alias="preferredLanguage")
    difficulty_preference: str = Field(default="adaptive", alias="difficultyPreference")
    quiz_mode: str = Field(default="timed", alias="quizMode")
    leaderboard_visible: bool = Field(default=True, alias="leaderboardVisible")
    public_display_name: str | None = Field(default=None, alias="publicDisplayName", max_length=40)
    username_visible: bool = Field(default=False, alias="usernameVisible")
    daily_reminder_enabled: bool = Field(default=False, alias="dailyReminderEnabled")
    revision_sound_enabled: bool = Field(default=True, alias="revisionSoundEnabled")
    revision_vibration_enabled: bool = Field(default=False, alias="revisionVibrationEnabled")
    dev_user: dict | None = Field(default=None, alias="devUser")

    model_config = {"populate_by_name": True}


class PracticeAnswerRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    selected_option: int = Field(alias="selectedIndex", ge=0, le=3)
    source_type: str = Field(default="wrong", alias="sourceType")
    mode: str = Field(alias="mode")
    response_time_seconds: float | None = Field(
        default=None,
        alias="responseTimeSeconds",
        ge=0,
        le=3600,
    )
    marked_for_review: bool = Field(default=False, alias="markedForReview")
    attempt_id: uuid.UUID = Field(alias="attemptId")
    dev_user: dict | None = Field(default=None, alias="devUser")

    model_config = {"populate_by_name": True}


class PracticeQuestionReportRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    attempt_id: uuid.UUID = Field(alias="attemptId")
    reason: str = Field(min_length=1, max_length=50)
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


class ResourceFeedbackRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    feedback_type: str = Field(alias="feedbackType")
    rating: int | None = Field(default=None, ge=1, le=5)
    details: str | None = Field(default=None, max_length=500)
    dev_user: dict | None = Field(default=None, alias="devUser")

    model_config = {"populate_by_name": True}


class ResourceReviewRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    decision: str
    dev_user: dict | None = Field(default=None, alias="devUser")

    model_config = {"populate_by_name": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "index.html")


@app.get("/dashboard")
@app.get("/dashboard.html")
def dashboard() -> FileResponse:
    return FileResponse(ROOT / "dashboard.html")


@app.get("/practice")
@app.get("/practice.html")
def practice() -> FileResponse:
    return FileResponse(ROOT / "practice.html")


@app.get("/quizzes/{quiz_file}")
def legacy_quiz_file(quiz_file: str) -> JSONResponse:
    if not quiz_file.endswith(".json"):
        raise HTTPException(status_code=404, detail="Quiz file not found.")
    quiz_id = _clean_quiz_id(quiz_file[:-5])
    payload = _load_public_fallback(quiz_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Quiz file not found.")
    return JSONResponse(payload)


@app.get("/health/live")
def health_live() -> dict:
    """Process-only liveness probe; it deliberately performs no network I/O."""
    return {
        "ok": True,
        "status": "live",
        "applicationVersion": app.version,
        "timezone": APP_TIMEZONE,
    }


@app.get("/health/ready")
def health_ready() -> JSONResponse:
    readiness = readiness_service.assess()
    return JSONResponse(
        readiness.public_payload(),
        status_code=200 if readiness.ready else 503,
    )


@app.get("/api/health")
def health() -> JSONResponse:
    """Compatibility alias with the same strict semantics as readiness."""
    return health_ready()


@app.get("/api/quiz/{quiz_id}")
def get_quiz(quiz_id: str) -> dict:
    clean_quiz_id = _clean_quiz_id(quiz_id)
    try:
        pack = quiz_pack_service.get_ready_quiz_pack(clean_quiz_id)
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
        pack = quiz_pack_service.get_ready_quiz_pack(clean_quiz_id)
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


@app.post("/api/resources/{resource_id}/feedback")
def submit_resource_feedback(resource_id: uuid.UUID, payload: ResourceFeedbackRequest) -> dict:
    try:
        return resource_quality_service.submit_feedback(
            _write_user_from_payload(payload, "resource-feedback", str(resource_id)),
            resource_id=str(resource_id),
            feedback_type=payload.feedback_type,
            rating=payload.rating,
            details=payload.details,
        )
    except HTTPException:
        raise
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="রিসোর্স মতামত সংরক্ষণ করা যায়নি।") from exc


@app.get("/api/admin/operations")
def admin_operations(
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict:
    try:
        return resource_quality_service.admin_operational_status(
            _telegram_user_from_init_data(init_data)
        )
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Operations status is unavailable.") from exc


@app.get("/api/admin/resources/reviews")
def admin_resource_reviews(
    limit: int = 50,
    offset: int = 0,
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict:
    try:
        return resource_quality_service.admin_review_queue(
            _telegram_user_from_init_data(init_data),
            limit=limit,
            offset=offset,
        )
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Resource review queue is unavailable.") from exc


@app.post("/api/admin/resources/{resource_id}/review")
def review_resource(
    resource_id: uuid.UUID,
    payload: ResourceReviewRequest,
) -> dict:
    try:
        return resource_quality_service.review_candidate(
            _write_user_from_payload(payload, "resource-review", str(resource_id)),
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Resource review could not be saved.") from exc


@app.post("/api/quiz/{quiz_id}/submit")
def submit_quiz(quiz_id: str, payload: SubmitQuizRequest) -> dict:
    try:
        clean_quiz_id = _clean_quiz_id(quiz_id)
        telegram_user = _write_user_from_payload(
            payload,
            "quiz-submit",
            f"{clean_quiz_id}:{payload.attempt_id}",
        )
        return quiz_pack_service.submit_quiz_attempts(
            quiz_id=clean_quiz_id,
            telegram_user=telegram_user,
            answers=payload.answers,
            attempt_id=payload.attempt_id,
            duration_seconds=payload.duration_seconds,
            response_times=payload.response_times,
            marked_for_review=payload.marked_for_review,
        )
    except HTTPException:
        raise
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="স্কোর জমা করা যায়নি। একটু পরে আবার চেষ্টা করুন।") from exc


@app.get("/api/quiz/{quiz_id}/attempt/{attempt_id}")
def get_quiz_attempt_result(
    quiz_id: str,
    attempt_id: uuid.UUID,
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict:
    try:
        result = quiz_pack_service.get_quiz_attempt_result(
            quiz_id=_clean_quiz_id(quiz_id),
            telegram_user=_telegram_user_from_init_data(init_data),
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="ফলাফল এখন খোলা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।",
        ) from exc


@app.post("/api/questions/{question_id}/report")
def report_question(question_id: uuid.UUID, payload: ReportQuestionRequest) -> dict:
    try:
        clean_quiz_id = _clean_quiz_id(payload.quiz_id)
        telegram_user = _write_user_from_payload(
            payload,
            "question-report",
            f"{clean_quiz_id}:{payload.attempt_id}",
        )
        return quiz_pack_service.submit_question_report(
            question_id=str(question_id),
            quiz_id=clean_quiz_id,
            telegram_user=telegram_user,
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


@app.get("/api/me/dashboard")
def my_learning_dashboard(
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict:
    try:
        return personal_learning_service.dashboard(_telegram_user_from_init_data(init_data))
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="ব্যক্তিগত ড্যাশবোর্ড এখন খোলা যাচ্ছে না।") from exc


@app.get("/api/me/reviews/due")
def my_due_reviews(
    limit: int = 20,
    offset: int = 0,
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict:
    try:
        return personal_learning_service.due_reviews(
            _telegram_user_from_init_data(init_data),
            limit=limit,
            offset=offset,
        )
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="রিভিশনের প্রশ্ন এখন লোড করা যাচ্ছে না।") from exc


@app.get("/api/me/wrong-questions")
def my_wrong_questions(
    subject: str | None = None,
    limit: int = 20,
    offset: int = 0,
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict:
    try:
        return personal_learning_service.wrong_questions(
            _telegram_user_from_init_data(init_data),
            subject_key=subject,
            limit=limit,
            offset=offset,
        )
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="ভুল প্রশ্ন এখন লোড করা যাচ্ছে না।") from exc


@app.post("/api/me/practice/{question_id}")
def submit_my_practice_answer(question_id: uuid.UUID, payload: PracticeAnswerRequest) -> dict:
    try:
        return personal_learning_service.submit_practice_answer(
            _write_user_from_payload(
                payload,
                "practice-answer",
                str(payload.attempt_id),
            ),
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="অনুশীলনের উত্তর সংরক্ষণ করা যায়নি।") from exc


@app.post("/api/me/practice/{question_id}/report")
def report_my_practice_question(
    question_id: uuid.UUID,
    payload: PracticeQuestionReportRequest,
) -> dict:
    try:
        return personal_learning_service.report_practice_question(
            _write_user_from_payload(
                payload,
                "question-report",
                str(payload.attempt_id),
            ),
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
        raise HTTPException(
            status_code=503,
            detail="রিপোর্ট জমা করা যায়নি। একটু পরে আবার চেষ্টা করুন।",
        ) from exc


@app.get("/api/me/bookmarks")
def my_bookmarks(
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict:
    try:
        return personal_learning_service.bookmarks(_telegram_user_from_init_data(init_data))
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="বুকমার্ক এখন লোড করা যাচ্ছে না।") from exc


@app.post("/api/me/bookmarks")
def set_my_bookmark(payload: BookmarkRequest) -> dict:
    try:
        return personal_learning_service.set_bookmark(
            _write_user_from_payload(
                payload,
                "bookmark",
                f"{payload.item_type}:{payload.item_id}",
            ),
            item_type=payload.item_type,
            item_id=str(payload.item_id),
            active=payload.active,
        )
    except HTTPException:
        raise
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="বুকমার্ক সংরক্ষণ করা যায়নি।") from exc


@app.get("/api/me/preferences")
def my_preferences(
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict:
    try:
        return personal_learning_service.preferences(_telegram_user_from_init_data(init_data))
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="পছন্দের সেটিং এখন লোড করা যাচ্ছে না।") from exc


@app.put("/api/me/preferences")
def save_my_preferences(payload: UserPreferencesRequest) -> dict:
    try:
        return personal_learning_service.save_preferences(
            _write_user_from_payload(payload, "preferences"),
            payload.model_dump(exclude={"init_data", "dev_user"}),
        )
    except HTTPException:
        raise
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="পছন্দের সেটিং সংরক্ষণ করা যায়নি।") from exc


@app.get("/api/quiz/{quiz_id}/leaderboard")
def quiz_leaderboard(
    quiz_id: str,
    limit: int = 10,
    offset: int = 0,
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict:
    clean_quiz_id = _clean_quiz_id(quiz_id)
    try:
        user_id = None
        if init_data:
            telegram_user = _telegram_user_from_init_data(init_data)
            user_id = str(users_repo.upsert_user(User.from_telegram(telegram_user))["id"])
        result = stats_repo.quiz_leaderboard_for_user(
            clean_quiz_id,
            user_id=user_id,
            limit=max(1, min(limit, 50)),
        )
        result["requestedOffset"] = max(0, offset)
        return result
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Leaderboard সাময়িকভাবে পাওয়া যাচ্ছে না।") from exc


@app.get("/api/leaderboard")
def leaderboard(limit: int = 20, offset: int = 0) -> dict:
    try:
        return {
            **stats_repo.typed_leaderboard_for_user(
                "overall_rank",
                subject_key=None,
                user_id=None,
                limit=max(1, min(limit, 100)),
                offset=max(0, offset),
            ),
            "unavailable": False,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="সামগ্রিক র‍্যাঙ্কিং সাময়িকভাবে পাওয়া যাচ্ছে না।",
        ) from exc


@app.get("/api/leaderboards/{board_type}")
def typed_leaderboard(
    board_type: str,
    subject: str | None = None,
    limit: int = 20,
    offset: int = 0,
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict:
    try:
        if subject and subject not in SUBJECTS:
            raise ValueError("Unknown subject key.")
        user_id = None
        if init_data:
            telegram_user = _telegram_user_from_init_data(init_data)
            user_id = str(users_repo.upsert_user(User.from_telegram(telegram_user))["id"])
        return {
            **stats_repo.typed_leaderboard_for_user(
                board_type,
                subject_key=subject,
                user_id=user_id,
                limit=max(1, min(limit, 100)),
                offset=max(0, offset),
            ),
            "unavailable": False,
        }
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Leaderboard সাময়িকভাবে পাওয়া যাচ্ছে না।") from exc


def _write_user_from_payload(
    payload: (
        SubmitQuizRequest
        | ReportQuestionRequest
        | BookmarkRequest
        | UserPreferencesRequest
        | PracticeAnswerRequest
        | PracticeQuestionReportRequest
        | ResourceFeedbackRequest
        | ResourceReviewRequest
    ),
    scope: str,
    suffix: str = "",
) -> dict:
    user = _telegram_user_from_init_data(
        payload.init_data,
        payload.dev_user,
        max_age_seconds=TELEGRAM_WRITE_INIT_DATA_MAX_AGE_SECONDS,
    )
    user_key = str(user.get("id") or "unknown")
    limits = {
        "quiz-submit": (30, 3600),
        "practice-answer": (120, 3600),
        "bookmark": (60, 3600),
        "question-report": (10, 3600),
        "preferences": (20, 3600),
        "resource-feedback": (20, 3600),
        "resource-review": (60, 3600),
    }
    limit, window = limits.get(scope, (30, 3600))
    try:
        rate_limit.check(f"{scope}:{user_key}", limit=limit, window_seconds=window)
        if suffix:
            rate_limit.check(
                f"{scope}:{user_key}:{suffix}",
                limit=5,
                window_seconds=60,
            )
    except rate_limit.RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    return user


def _telegram_user_from_init_data(
    init_data: str,
    dev_user: dict | None = None,
    *,
    max_age_seconds: int = TELEGRAM_INIT_DATA_MAX_AGE_SECONDS,
) -> dict:
    if init_data:
        return verify_init_data(init_data, TELEGRAM_BOT_TOKEN, max_age_seconds)
    if DEV_ALLOW_UNVERIFIED_TELEGRAM:
        return dev_user or {
            "id": 999999001,
            "username": "local_tester",
            "first_name": "Local",
            "last_name": "Tester",
        }
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
