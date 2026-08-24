"""Answer-free public catalogue routes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response


def build_catalog_router(
    *,
    exam_service: Any,
    quiz_service: Any,
    attempts_service: Any,
    syllabus_service: Any,
    mark_answer_free: Callable[[Response, object], None],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/syllabus")
    def syllabus(
        response: Response,
        exam: str | None = None,
        subject: str | None = None,
    ) -> dict:
        try:
            payload = syllabus_service.syllabus_catalog(exam_key=exam, subject_key=subject)
            mark_answer_free(response, payload)
            return payload
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Syllabus catalog is temporarily unavailable.") from exc

    @router.get("/api/exams")
    def exams(as_of: date | None = None, exam: str | None = None, limit: int = 20, offset: int = 0) -> dict:
        try:
            return exam_service.exam_catalog(as_of=as_of, exam_key=exam, limit=limit, offset=offset)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Exam configuration is temporarily unavailable.") from exc

    @router.get("/api/quizzes/recent")
    def recent_quizzes(response: Response, limit: int = 26) -> dict:
        try:
            payload = quiz_service.recent_quizzes(limit=limit)
            mark_answer_free(response, payload)
            return payload
        except Exception as exc:
            raise HTTPException(status_code=503, detail="সাম্প্রতিক কুইজের তালিকা এখন পাওয়া যাচ্ছে না।") from exc

    @router.get("/api/tests/definitions")
    def definitions(as_of: date | None = None, test_type: str | None = None, limit: int = 20, offset: int = 0) -> dict:
        try:
            return exam_service.test_definition_catalog(as_of=as_of, test_type=test_type, limit=limit, offset=offset)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Test definitions are temporarily unavailable.") from exc

    @router.get("/api/tests/catalog")
    def tests(
        exam: str | None = None,
        test_type: str | None = None,
        subject: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        try:
            return exam_service.learning_test_catalog(
                exam_key=exam, test_type=test_type, subject_key=subject, limit=limit, offset=offset
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Test catalog is temporarily unavailable.") from exc

    @router.get("/api/tests/instances/{test_instance_id}")
    def test_instance(test_instance_id: UUID, response: Response) -> dict:
        try:
            payload = exam_service.public_test_instance(test_instance_id)
            if payload is None:
                raise HTTPException(status_code=404, detail="Test instance not found.")
            mark_answer_free(response, payload)
            return payload
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Test instance is temporarily unavailable.") from exc

    @router.get("/api/previous-year")
    def previous_year(
        response: Response,
        exam: str | None = None,
        year: int | None = None,
        language: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        try:
            payload = attempts_service.previous_year_catalog(
                exam_key=exam, exam_year=year, language=language, limit=limit, offset=offset
            )
            mark_answer_free(response, payload)
            return payload
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Previous-year questions are temporarily unavailable.") from exc

    return router
