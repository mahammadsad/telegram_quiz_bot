"""Fail-closed smoke tests for the canonical deployed Mini App and API."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
import uuid
from urllib.parse import urlencode, urljoin, urlparse

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
STAGING_HOST = "telegram-quiz-bot-staging.onrender.com"
SYNTHETIC_STAGING_USER_ID = 9_007_199_254_740_001


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-commit")
    parser.add_argument("--quiz-id")
    parser.add_argument("--authenticated", action="store_true")
    parser.add_argument("--generate-staging-init-data", action="store_true")
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

    init_data = os.environ.get("SMOKE_TELEGRAM_INIT_DATA", "").strip()
    if args.generate_staging_init_data:
        if not args.authenticated or urlparse(base).hostname != STAGING_HOST:
            raise SystemExit("Synthetic initData generation is restricted to authenticated staging smoke.")
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not bot_token:
            raise SystemExit("Synthetic staging smoke requires TELEGRAM_BOT_TOKEN.")
        init_data = build_synthetic_staging_init_data(bot_token)
    if args.authenticated:
        _authenticated_smoke(session, base, args.quiz_id, init_data)
    print("deployed_smoke=passed")
    return 0


def build_synthetic_staging_init_data(bot_token: str, *, auth_date: int | None = None) -> str:
    """Create short-lived signed initData for the reserved staging-only actor."""

    values = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": f"staging-smoke-{uuid.uuid4()}",
        "user": json.dumps(
            {
                "id": SYNTHETIC_STAGING_USER_ID,
                "first_name": "Citizen Affairs",
                "last_name": "Synthetic QA",
                "username": "citizen_affairs_staging_smoke",
                "language_code": "bn",
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    }
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def _authenticated_smoke(
    session: requests.Session,
    base: str,
    quiz_id: str | None,
    init_data: str,
) -> None:
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
    first_result = submit.json() if submit.status_code == 200 else {}
    if first_result.get("timingSource") != "server":
        raise SystemExit("Authenticated idempotent submission failed.")
    replay = session.post(
        urljoin(base, f"api/quiz/{quiz_id}/submit"),
        json={"initData": init_data, "attemptId": attempt_id, "answers": [None] * 10},
        timeout=30,
    )
    replay_result = replay.json() if replay.status_code == 200 else {}
    first_stable = {key: value for key, value in first_result.items() if key != "idempotentReplay"}
    replay_stable = {key: value for key, value in replay_result.items() if key != "idempotentReplay"}
    if (
        first_result.get("idempotentReplay") is not False
        or replay_result.get("idempotentReplay") is not True
        or replay_stable != first_stable
    ):
        raise SystemExit("Authenticated submission replay was not idempotent.")
    recovered = session.get(
        urljoin(base, f"api/quiz/{quiz_id}/attempt/{attempt_id}"),
        headers={"X-Telegram-Init-Data": init_data},
        timeout=30,
    )
    if recovered.status_code != 200 or recovered.json().get("attemptId") != attempt_id:
        raise SystemExit("Authenticated attempt recovery failed.")

    retake_id = str(uuid.uuid4())
    retake_start = session.post(
        urljoin(base, f"api/quiz/{quiz_id}/attempts/start"),
        json={"initData": init_data, "attemptId": retake_id},
        timeout=30,
    )
    if retake_start.status_code != 200 or retake_start.json().get("timingTrusted") is not True:
        raise SystemExit("Authenticated retake start failed.")
    retake = session.post(
        urljoin(base, f"api/quiz/{quiz_id}/submit"),
        json={"initData": init_data, "attemptId": retake_id, "answers": [None] * 10},
        timeout=30,
    )
    if retake.status_code != 200 or retake.json().get("attemptNumber", 0) < 2:
        raise SystemExit("Authenticated retake submission failed.")

    auth_headers = {"X-Telegram-Init-Data": init_data}
    leaderboard = session.get(
        urljoin(base, f"api/quiz/{quiz_id}/leaderboard?limit=10&offset=0"),
        headers=auth_headers,
        timeout=30,
    )
    current_user = leaderboard.json().get("currentUser") if leaderboard.status_code == 200 else None
    if not isinstance(current_user, dict) or current_user.get("isCurrentUser") is not True:
        raise SystemExit("Authenticated viewer-aware leaderboard failed.")

    review = first_result.get("review")
    question_id = review[0].get("questionId") if isinstance(review, list) and review else None
    if not question_id:
        raise SystemExit("Authenticated result omitted its private review identity.")
    bookmark_url = urljoin(base, "api/me/bookmarks")
    bookmark_payload = {
        "initData": init_data,
        "itemType": "question",
        "itemId": question_id,
        "active": True,
    }
    bookmarked = session.post(bookmark_url, json=bookmark_payload, timeout=30)
    if bookmarked.status_code != 200:
        raise SystemExit("Authenticated bookmark creation failed.")
    bookmark_list = session.get(bookmark_url, headers=auth_headers, timeout=30)
    questions = bookmark_list.json().get("questions") if bookmark_list.status_code == 200 else None
    if not isinstance(questions, list) or not any(row.get("questionId") == question_id for row in questions):
        raise SystemExit("Authenticated bookmark readback failed.")
    bookmark_payload["active"] = False
    removed = session.post(bookmark_url, json=bookmark_payload, timeout=30)
    if removed.status_code != 200:
        raise SystemExit("Authenticated bookmark cleanup failed.")

    due = session.get(
        urljoin(base, "api/me/reviews/due?limit=20&offset=0"),
        headers=auth_headers,
        timeout=30,
    )
    due_payload = due.json() if due.status_code == 200 else {}
    due_rows = due_payload.get("rows")
    if due_payload.get("mode") != "revision" or not isinstance(due_rows, list) or not due_rows:
        raise SystemExit("Authenticated revision queue failed.")
    due_question_id = due_rows[0].get("questionId")
    if not due_question_id:
        raise SystemExit("Authenticated revision queue omitted its question identity.")
    practice = session.post(
        urljoin(base, f"api/me/practice/{due_question_id}"),
        json={
            "initData": init_data,
            "attemptId": str(uuid.uuid4()),
            "selectedIndex": 0,
            "sourceType": "due",
            "mode": "revision",
            "markedForReview": False,
        },
        timeout=30,
    )
    if practice.status_code != 200 or practice.json().get("mode") != "revision":
        raise SystemExit("Authenticated revision submission failed.")

    dashboard = session.get(
        urljoin(base, "api/me/dashboard"),
        headers=auth_headers,
        timeout=30,
    )
    if dashboard.status_code != 200:
        raise SystemExit("Authenticated dashboard smoke failed.")
    preferences = session.get(
        urljoin(base, "api/me/preferences"),
        headers=auth_headers,
        timeout=30,
    )
    if preferences.status_code != 200 or preferences.json().get("preferredLanguage") != "bn":
        raise SystemExit("Authenticated preference readback failed.")


if __name__ == "__main__":
    raise SystemExit(main())
