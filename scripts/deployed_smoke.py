"""Fail-closed smoke tests for the canonical deployed Mini App and API."""

from __future__ import annotations

import argparse
import os
import uuid
from urllib.parse import urljoin

import requests

PUBLIC_PATHS = (
    "",
    "miniapp-shell.css",
    "miniapp-shell.js",
    "pwa-icon.svg",
    "manifest.webmanifest",
    "service-worker.js",
    "version",
    "health/live",
    "health/ready",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-commit")
    parser.add_argument("--quiz-id")
    parser.add_argument("--authenticated", action="store_true")
    args = parser.parse_args()
    base = args.base_url.rstrip("/") + "/"
    if not base.startswith("https://"):
        raise SystemExit("Canonical smoke target must use HTTPS.")

    session = requests.Session()
    session.headers["User-Agent"] = "telegram-quiz-deployed-smoke/1.0"
    for path in PUBLIC_PATHS:
        response = session.get(urljoin(base, path), timeout=30)
        if response.status_code != 200:
            raise SystemExit(f"Smoke failed for /{path}: HTTP {response.status_code}")

    version = session.get(urljoin(base, "version"), timeout=30).json()
    if args.expected_commit and version.get("commitSha") != args.expected_commit:
        raise SystemExit("Deployed commit does not match the release candidate.")
    ready = session.get(urljoin(base, "health/ready"), timeout=30).json()
    if ready.get("status") != "ready":
        raise SystemExit("Canonical deployment is not ready.")

    if args.quiz_id:
        quiz = session.get(urljoin(base, f"api/quiz/{args.quiz_id}"), timeout=30)
        if quiz.status_code != 200 or len(quiz.json().get("qs") or []) != 10:
            raise SystemExit("Answer-free quiz load failed.")
        if quiz.headers.get("X-Answer-Free-Payload") != "1":
            raise SystemExit("Quiz response is missing the answer-free contract header.")

    if args.authenticated:
        _authenticated_smoke(session, base, args.quiz_id)
    print("deployed_smoke=passed")
    return 0


def _authenticated_smoke(session: requests.Session, base: str, quiz_id: str | None) -> None:
    init_data = os.environ.get("SMOKE_TELEGRAM_INIT_DATA", "").strip()
    if not init_data or not quiz_id:
        raise SystemExit("Authenticated smoke requires quiz ID and synthetic Telegram initData.")
    attempt_id = str(uuid.uuid4())
    start = session.post(
        urljoin(base, f"api/quiz/{quiz_id}/attempts/start"),
        json={"initData": init_data, "attemptId": attempt_id},
        timeout=30,
    )
    if start.status_code != 200 or start.json().get("timingTrusted") is not True:
        raise SystemExit("Authenticated server-timed attempt start failed.")
    submit = session.post(
        urljoin(base, f"api/quiz/{quiz_id}/submit"),
        json={"initData": init_data, "attemptId": attempt_id, "answers": [None] * 10},
        timeout=30,
    )
    if submit.status_code != 200 or submit.json().get("timingSource") != "server":
        raise SystemExit("Authenticated idempotent submission failed.")
    dashboard = session.get(
        urljoin(base, "api/me/dashboard"),
        headers={"X-Telegram-Init-Data": init_data},
        timeout=30,
    )
    if dashboard.status_code != 200:
        raise SystemExit("Authenticated dashboard smoke failed.")


if __name__ == "__main__":
    raise SystemExit(main())
