"""Read-only analytics helpers built from the shared raw tables."""

from __future__ import annotations

from collections import defaultdict

from config.settings import SESSION_TYPE
from database.client import get_client


def leaderboard(limit: int = 20, session_type: str = SESSION_TYPE) -> list[dict]:
    """Compute a live leaderboard from user_attempts.

    The repo_1 schema intentionally stores raw events, not score totals. This
    helper keeps that rule intact by aggregating attempts at read time.
    """
    client = get_client()
    attempts_res = (
        client.table("user_attempts")
        .select("user_id,is_correct,answered_at")
        .eq("session_type", session_type)
        .limit(10000)
        .execute()
    )
    attempts = attempts_res.data or []
    if not attempts:
        return []

    stats: dict[str, dict] = defaultdict(lambda: {
        "total_attempts": 0,
        "correct_attempts": 0,
        "last_attempt_at": None,
    })
    for row in attempts:
        item = stats[row["user_id"]]
        item["total_attempts"] += 1
        if row.get("is_correct"):
            item["correct_attempts"] += 1
        answered_at = row.get("answered_at")
        if answered_at and (item["last_attempt_at"] is None or answered_at > item["last_attempt_at"]):
            item["last_attempt_at"] = answered_at

    user_ids = list(stats.keys())
    users_res = (
        client.table("users")
        .select("id,telegram_id,username,first_name,last_name")
        .in_("id", user_ids)
        .execute()
    )
    users_by_id = {row["id"]: row for row in (users_res.data or [])}

    rows = []
    for user_id, item in stats.items():
        user = users_by_id.get(user_id, {})
        total = item["total_attempts"]
        correct = item["correct_attempts"]
        rows.append({
            "user_id": user_id,
            "telegram_id": user.get("telegram_id"),
            "username": user.get("username"),
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
            "total_attempts": total,
            "correct_attempts": correct,
            "accuracy_pct": round((correct / total) * 100, 2) if total else 0,
            "last_attempt_at": item["last_attempt_at"],
        })

    rows.sort(
        key=lambda row: (
            row["correct_attempts"],
            row["accuracy_pct"],
            row["total_attempts"],
            row["last_attempt_at"] or "",
        ),
        reverse=True,
    )
    return rows[:limit]
