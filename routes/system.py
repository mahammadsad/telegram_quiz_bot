"""Liveness, readiness, and release-identity routes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse


def build_system_router(
    *,
    application_version: str,
    app_timezone: str,
    release_value: Callable[..., str],
    readiness_service: Any,
    production_config_version: str,
    production_config_hash: str,
) -> APIRouter:
    """Build probe routes while injecting application-specific dependencies."""
    router = APIRouter()

    @router.get("/health/live")
    def health_live() -> dict:
        return {
            "ok": True,
            "status": "live",
            "applicationVersion": application_version,
            "commitSha": release_value("RENDER_GIT_COMMIT", "GITHUB_SHA", default="unknown"),
            "environment": release_value("APP_ENVIRONMENT", "RENDER_SERVICE_NAME", default="local"),
            "buildTime": release_value("BUILD_TIME", default="unknown"),
            "timezone": app_timezone,
            "productionConfigVersion": production_config_version,
            "productionConfigHash": production_config_hash,
        }

    @router.get("/version")
    def release_version() -> dict:
        return {
            "applicationVersion": application_version,
            "commitSha": release_value("RENDER_GIT_COMMIT", "GITHUB_SHA", default="unknown"),
            "environment": release_value("APP_ENVIRONMENT", "RENDER_SERVICE_NAME", default="local"),
            "buildTime": release_value("BUILD_TIME", default="unknown"),
            "serverTime": datetime.now(timezone.utc).isoformat(),
        }

    def readiness_response() -> JSONResponse:
        readiness = readiness_service.assess()
        return JSONResponse(readiness.public_payload(), status_code=200 if readiness.ready else 503)

    router.add_api_route("/health/ready", readiness_response, methods=["GET"])
    router.add_api_route("/api/health", readiness_response, methods=["GET"])
    return router
