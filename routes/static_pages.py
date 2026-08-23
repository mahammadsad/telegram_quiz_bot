"""Public HTML, static-asset, and progressive-web-app routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


def build_static_router(root: Path) -> APIRouter:
    """Return the immutable public-file routes without application dependencies."""
    router = APIRouter()

    def page(filename: str) -> FileResponse:
        return FileResponse(root / filename)

    def asset(filename: str, media_type: str, cache_control: str) -> FileResponse:
        return FileResponse(root / filename, media_type=media_type, headers={"Cache-Control": cache_control})

    @router.get("/")
    @router.get("/index.html")
    def index() -> FileResponse:
        return page("index.html")

    for path, filename in (
        ("/dashboard", "dashboard.html"),
        ("/dashboard.html", "dashboard.html"),
        ("/practice", "practice.html"),
        ("/practice.html", "practice.html"),
        ("/settings", "settings.html"),
        ("/settings.html", "settings.html"),
        ("/privacy", "privacy.html"),
        ("/privacy.html", "privacy.html"),
        ("/terms", "terms.html"),
        ("/terms.html", "terms.html"),
        ("/mock", "mock.html"),
        ("/mock.html", "mock.html"),
    ):
        router.add_api_route(path, lambda filename=filename: page(filename), methods=["GET"])

    for path, filename, media_type, cache_control in (
        ("/miniapp-shell.js", "miniapp-shell.js", "text/javascript", "public, max-age=3600"),
        ("/miniapp-shell.css", "miniapp-shell.css", "text/css", "public, max-age=300"),
        ("/index.css", "index.css", "text/css", "public, max-age=300"),
        ("/index.js", "index.js", "text/javascript", "public, max-age=3600"),
        ("/mock.css", "mock.css", "text/css", "public, max-age=300"),
        ("/mock.js", "mock.js", "text/javascript", "public, max-age=3600"),
        ("/practice.css", "practice.css", "text/css", "public, max-age=300"),
        ("/practice.js", "practice.js", "text/javascript", "public, max-age=3600"),
        ("/dashboard.css", "dashboard.css", "text/css", "public, max-age=300"),
        ("/dashboard.js", "dashboard.js", "text/javascript", "public, max-age=3600"),
        ("/settings.css", "settings.css", "text/css", "public, max-age=300"),
        ("/settings.js", "settings.js", "text/javascript", "public, max-age=3600"),
        ("/legal.css", "legal.css", "text/css", "public, max-age=300"),
        ("/manifest.webmanifest", "manifest.webmanifest", "application/manifest+json", "public, max-age=3600"),
        ("/pwa-icon.svg", "pwa-icon.svg", "image/svg+xml", "public, max-age=86400"),
    ):
        router.add_api_route(
            path,
            lambda filename=filename, media_type=media_type, cache_control=cache_control: asset(
                filename, media_type, cache_control
            ),
            methods=["GET"],
        )

    @router.get("/service-worker.js")
    def service_worker() -> FileResponse:
        return FileResponse(
            root / "service-worker.js",
            media_type="text/javascript",
            headers={"Cache-Control": "no-cache, max-age=0", "Service-Worker-Allowed": "/"},
        )

    return router
