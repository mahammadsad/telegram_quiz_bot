"""Quiz delivery, authenticated learning workflows, and safe leaderboards."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api_models import (
    AdvanceTestSectionRequest,
    AuthoritativeQuarantineRequest,
    BookmarkRequest,
    PracticeAnswerRequest,
    PracticeQuestionReportRequest,
    PrivacyActionRequest,
    QuestionReviewRequest,
    ReportQuestionRequest,
    ResourceFeedbackRequest,
    ResourceReviewRequest,
    SaveTestProgressRequest,
    StartQuizRequest,
    StartTestAttemptRequest,
    SubmitQuizRequest,
    SubmitTestAttemptRequest,
    UserPreferencesRequest,
)
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
from routes.admin import build_admin_router
from routes.catalog import build_catalog_router
from routes.leaderboards import build_leaderboard_router
from routes.learner import build_learner_router
from routes.static_pages import build_static_router
from routes.system import build_system_router
from services import (
    exam_config_service,
    leaderboard_privacy,
    learning_resources_service,
    personal_learning_service,
    privacy_service,
    question_moderation_service,
    quiz_pack_service,
    rate_limit,
    readiness_service,
    resource_quality_service,
    test_attempts_service,
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
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://telegram.org; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "manifest-src 'self'; worker-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors https://web.telegram.org https://*.telegram.org"
    )
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if request.url.scheme == "https" or forwarded_proto == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if _is_leaderboard_path(request.url.path):
        response.headers["Cache-Control"] = "no-store, private, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["Surrogate-Control"] = "no-store"
        _merge_vary_header(response.headers, "X-Telegram-Init-Data")
    elif (
        request.url.path.startswith("/api/me/")
        or request.url.path.startswith("/api/admin/")
        or bool(request.headers.get("x-telegram-init-data"))
        or request.method not in {"GET", "HEAD", "OPTIONS"}
    ):
        response.headers["Cache-Control"] = "no-store, private"
    return response


def _is_leaderboard_path(path: str) -> bool:
    return bool(
        path == "/api/leaderboard"
        or path.startswith("/api/leaderboards/")
        or (path.startswith("/api/quiz/") and path.endswith("/leaderboard"))
    )


def _merge_vary_header(headers: Any, value: str) -> None:
    existing = [part.strip() for part in headers.get("Vary", "").split(",")]
    values = [part for part in existing if part]
    if value.casefold() not in {part.casefold() for part in values}:
        values.append(value)
    headers["Vary"] = ", ".join(values)


def _mark_answer_free(response: Response, payload: object) -> None:
    """Permit CDN/browser caching only for public answer-free projections."""
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    response.headers["X-Answer-Free-Payload"] = "1"
    response.headers["Cache-Control"] = "public, max-age=300, s-maxage=3600, stale-while-revalidate=60"
    response.headers["ETag"] = '"' + hashlib.sha256(serialized.encode("utf-8")).hexdigest() + '"'
    _merge_vary_header(response.headers, "Accept-Encoding")


def _value_error_status(exc: ValueError) -> int:
    return 429 if "rate limit" in str(exc).casefold() else 400


app.include_router(build_static_router(ROOT))


@app.get("/quizzes/{quiz_file}")
def legacy_quiz_file(quiz_file: str) -> JSONResponse:
    if not quiz_file.endswith(".json"):
        raise HTTPException(status_code=404, detail="Quiz file not found.")
    quiz_id = _clean_quiz_id(quiz_file[:-5])
    payload = _load_public_fallback(quiz_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Quiz file not found.")
    return JSONResponse(payload)


def _release_value(*names: str, default: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value[:120]
    return default


app.include_router(
    build_system_router(
        application_version=app.version,
        app_timezone=APP_TIMEZONE,
        release_value=_release_value,
        readiness_service=readiness_service,
        production_config_version=readiness_service.PRODUCTION_CONFIG_VERSION,
        production_config_hash=readiness_service.PRODUCTION_CONFIG_HASH,
    )
)
app.include_router(
    build_catalog_router(
        exam_service=exam_config_service,
        quiz_service=quiz_pack_service,
        attempts_service=test_attempts_service,
        mark_answer_free=_mark_answer_free,
    )
)


@app.post("/api/tests/instances/{test_instance_id}/attempts/start")
def start_test_attempt(
    test_instance_id: uuid.UUID,
    payload: StartTestAttemptRequest,
) -> dict:
    try:
        return test_attempts_service.start(
            _write_user_from_payload(payload, "test-attempt-start", str(test_instance_id)),
            test_instance_id=test_instance_id,
            client_attempt_id=payload.client_attempt_id,
        )
    except HTTPException:
        raise
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=_value_error_status(exc), detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Test attempt could not be started.") from exc


@app.put("/api/tests/attempts/{attempt_id}/progress")
def save_test_attempt_progress(
    attempt_id: uuid.UUID,
    payload: SaveTestProgressRequest,
) -> dict:
    try:
        responses = [item.model_dump() for item in payload.responses]
        return test_attempts_service.save_progress(
            _write_user_from_payload(payload, "test-attempt-progress", str(attempt_id)),
            attempt_id=attempt_id,
            responses=responses,
        )
    except HTTPException:
        raise
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=_value_error_status(exc), detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Test progress could not be saved.") from exc


@app.post("/api/tests/attempts/{attempt_id}/sections/advance")
def advance_test_attempt_section(
    attempt_id: uuid.UUID,
    payload: AdvanceTestSectionRequest,
) -> dict:
    try:
        return test_attempts_service.advance_section(
            _write_user_from_payload(payload, "test-attempt-section", str(attempt_id)),
            attempt_id=attempt_id,
            next_section_instance_id=payload.next_section_instance_id,
        )
    except HTTPException:
        raise
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=_value_error_status(exc), detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Test section could not be advanced.") from exc


@app.post("/api/tests/attempts/{attempt_id}/submit")
def submit_test_attempt(
    attempt_id: uuid.UUID,
    payload: SubmitTestAttemptRequest,
) -> dict:
    try:
        return test_attempts_service.submit(
            _write_user_from_payload(payload, "test-attempt-submit", str(attempt_id)),
            attempt_id=attempt_id,
            auto_submit=payload.auto_submit,
        )
    except HTTPException:
        raise
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=_value_error_status(exc), detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Test attempt could not be submitted.") from exc


@app.get("/api/tests/attempts/{attempt_id}")
def get_test_attempt(
    attempt_id: uuid.UUID,
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict:
    try:
        payload = test_attempts_service.get(
            _telegram_user_from_init_data(init_data),
            attempt_id=attempt_id,
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="Test attempt not found.")
        return payload
    except HTTPException:
        raise
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Test attempt is temporarily unavailable.") from exc


@app.get("/api/quiz/{quiz_id}")
def get_quiz(quiz_id: str, response: Response) -> dict:
    clean_quiz_id = _clean_quiz_id(quiz_id)
    try:
        pack = quiz_pack_service.get_ready_quiz_pack(clean_quiz_id)
    except Exception as exc:
        legacy = _load_public_fallback(clean_quiz_id)
        if legacy:
            _mark_answer_free(response, legacy)
            return legacy
        raise HTTPException(status_code=503, detail="কুইজটি এখন খোলা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।") from exc
    if pack:
        if len(pack.get("items") or []) != 10:
            raise HTTPException(status_code=503, detail="কুইজের তথ্য অসম্পূর্ণ। পরে আবার চেষ্টা করুন।")
        payload = quiz_pack_service.public_quiz_payload(pack)
        _mark_answer_free(response, payload)
        return payload
    legacy = _load_public_fallback(clean_quiz_id)
    if legacy:
        _mark_answer_free(response, legacy)
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
        raise HTTPException(status_code=_value_error_status(exc), detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="রিসোর্স মতামত সংরক্ষণ করা যায়নি।") from exc


@app.post("/api/quiz/{quiz_id}/attempts/start")
def start_quiz_attempt(quiz_id: str, payload: StartQuizRequest) -> dict:
    try:
        clean_quiz_id = _clean_quiz_id(quiz_id)
        telegram_user = _write_user_from_payload(
            payload,
            "quiz-start",
            f"{clean_quiz_id}:{payload.attempt_id}",
        )
        return quiz_pack_service.start_quiz_attempt(
            quiz_id=clean_quiz_id,
            telegram_user=telegram_user,
            attempt_id=payload.attempt_id,
        )
    except HTTPException:
        raise
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=_value_error_status(exc), detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="কুইজের সময় শুরু করা যায়নি। আবার চেষ্টা করুন।") from exc


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
            client_duration_seconds=payload.duration_seconds,
            response_times=payload.response_times,
            marked_for_review=payload.marked_for_review,
        )
    except HTTPException:
        raise
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=_value_error_status(exc), detail=str(exc)) from exc
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
        raise HTTPException(status_code=_value_error_status(exc), detail=str(exc)) from exc
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


def _write_user_from_payload(
    payload: (
        SubmitQuizRequest
        | StartQuizRequest
        | PrivacyActionRequest
        | ReportQuestionRequest
        | BookmarkRequest
        | UserPreferencesRequest
        | PracticeAnswerRequest
        | PracticeQuestionReportRequest
        | ResourceFeedbackRequest
        | ResourceReviewRequest
        | QuestionReviewRequest
        | AuthoritativeQuarantineRequest
        | StartTestAttemptRequest
        | SaveTestProgressRequest
        | AdvanceTestSectionRequest
        | SubmitTestAttemptRequest
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
        "quiz-start": (30, 3600),
        "privacy-export": (3, 3600),
        "privacy-delete": (3, 3600),
        "privacy-delete-cancel": (3, 3600),
        "practice-answer": (120, 3600),
        "bookmark": (60, 3600),
        "question-report": (10, 3600),
        "preferences": (20, 3600),
        "resource-feedback": (20, 3600),
        "resource-review": (60, 3600),
        "question-moderation": (60, 3600),
        "test-attempt-start": (30, 3600),
        "test-attempt-progress": (600, 3600),
        "test-attempt-section": (100, 3600),
        "test-attempt-submit": (30, 3600),
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
        "qs": [
            {"q": item.get("q") or item.get("question"), "o": item.get("o") or item.get("options")}
            for item in questions
        ],
    }


app.include_router(
    build_admin_router(
        resource_service=resource_quality_service,
        moderation_service=question_moderation_service,
        read_user=_telegram_user_from_init_data,
        write_user=_write_user_from_payload,
        value_error_status=_value_error_status,
    )
)
app.include_router(
    build_leaderboard_router(
        stats_repo=stats_repo,
        users_repo=users_repo,
        privacy_service=leaderboard_privacy,
        subjects=SUBJECTS,
        read_user=_telegram_user_from_init_data,
        clean_quiz_id=_clean_quiz_id,
    )
)
app.include_router(
    build_learner_router(
        learning_service=personal_learning_service,
        moderation_service=question_moderation_service,
        privacy_service=privacy_service,
        read_user=_telegram_user_from_init_data,
        write_user=_write_user_from_payload,
        value_error_status=_value_error_status,
    )
)
