"""Pydantic request contracts for the mock-test learning API.

Keeping these schemas separate from route registration makes the public request
contract easier to review and lets test-attempt routes evolve independently of
the application bootstrap module.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator


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
