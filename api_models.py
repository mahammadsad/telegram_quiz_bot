"""Pydantic request contracts for the mock-test learning API.

Keeping these schemas separate from route registration makes the public request
contract easier to review and lets test-attempt routes evolve independently of
the application bootstrap module.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from services import quiz_pack_service


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
            if answer is not None and (
                isinstance(answer, bool) or not isinstance(answer, int) or answer not in range(4)
            ):
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
                isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 <= seconds <= 3600
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


class StartQuizRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    attempt_id: uuid.UUID = Field(alias="attemptId")
    dev_user: dict | None = Field(default=None, alias="devUser")
    model_config = {"populate_by_name": True}


class PrivacyActionRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    dev_user: dict | None = Field(default=None, alias="devUser")
    model_config = {"populate_by_name": True}


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
    response_time_seconds: float | None = Field(default=None, alias="responseTimeSeconds", ge=0, le=3600)
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


class QuestionReviewRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    decision: str = Field(min_length=1, max_length=40)
    resolution: str = Field(min_length=1, max_length=2000)
    superseding_question_id: uuid.UUID | None = Field(default=None, alias="supersedingQuestionId")
    dev_user: dict | None = Field(default=None, alias="devUser")
    model_config = {"populate_by_name": True}


class AuthoritativeQuarantineRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    trigger: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=2000)
    superseding_question_id: uuid.UUID | None = Field(default=None, alias="supersedingQuestionId")
    dev_user: dict | None = Field(default=None, alias="devUser")
    model_config = {"populate_by_name": True}


class StartTestAttemptRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    client_attempt_id: uuid.UUID = Field(alias="clientAttemptId")
    dev_user: dict | None = Field(default=None, alias="devUser")

    model_config = {"populate_by_name": True}


class TestResponseInput(BaseModel):
    question_id: uuid.UUID = Field(alias="questionId")
    selected_index: int | None = Field(default=None, alias="selectedIndex", ge=0, le=3)
    response_time_seconds: float | None = Field(
        default=None,
        alias="responseTimeSeconds",
        ge=0,
        le=86400,
    )
    marked_for_review: bool = Field(default=False, alias="markedForReview")

    model_config = {"populate_by_name": True}

    @field_validator("selected_index", mode="before")
    @classmethod
    def reject_boolean_answer(cls, value: Any):
        if isinstance(value, bool):
            raise ValueError("selectedIndex must be between 0 and 3 or null")
        return value


class SaveTestProgressRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    responses: list[TestResponseInput] = Field(max_length=500)
    dev_user: dict | None = Field(default=None, alias="devUser")

    model_config = {"populate_by_name": True}


class AdvanceTestSectionRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    next_section_instance_id: uuid.UUID = Field(alias="nextSectionInstanceId")
    dev_user: dict | None = Field(default=None, alias="devUser")

    model_config = {"populate_by_name": True}


class SubmitTestAttemptRequest(BaseModel):
    init_data: str = Field(default="", alias="initData")
    auto_submit: bool = Field(default=False, alias="autoSubmit")
    dev_user: dict | None = Field(default=None, alias="devUser")

    model_config = {"populate_by_name": True}
