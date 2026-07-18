"""Check cached resource links and record only safe availability categories."""

from __future__ import annotations

import argparse
import time
from dataclasses import asdict, dataclass
from typing import Protocol

import requests

from storage import resource_quality_repo

TIMEOUT_SECONDS = 20
USER_AGENT = "TelegramQuizBot-ResourceMonitor/1.0"


class Requester(Protocol):
    def get(self, url: str, **kwargs) -> requests.Response: ...

    def head(self, url: str, **kwargs) -> requests.Response: ...


@dataclass(frozen=True, slots=True)
class CheckResult:
    outcome: str
    error_category: str
    status_code: int | None
    response_ms: int


def check_resource(row: dict, requester: Requester = requests) -> CheckResult:
    started = time.monotonic()
    url = str(row.get("url") or "")
    if not url.startswith("https://"):
        return _result(started, "hard_failure", "invalid_url", None)
    try:
        if row.get("resource_type") == "youtube" and row.get("youtube_video_id"):
            response = requester.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT_SECONDS,
            )
            return _classify(response.status_code, started, youtube=True)

        response = requester.head(
            url,
            allow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code in {403, 405}:
            response = requester.get(
                url,
                allow_redirects=True,
                stream=True,
                headers={"User-Agent": USER_AGENT, "Range": "bytes=0-1023"},
                timeout=TIMEOUT_SECONDS,
            )
        return _classify(response.status_code, started, youtube=False)
    except requests.Timeout:
        return _result(started, "transient_error", "timeout", None)
    except requests.RequestException:
        return _result(started, "transient_error", "network_error", None)


def _classify(status: int, started: float, *, youtube: bool) -> CheckResult:
    if 200 <= status < 400:
        return _result(started, "available", "ok", status)
    if status == 404:
        category = "video_unavailable" if youtube else "not_found"
        return _result(started, "hard_failure", category, status)
    if status == 410:
        return _result(started, "hard_failure", "gone", status)
    if status in {401, 403}:
        if youtube:
            return _result(started, "hard_failure", "video_unavailable", status)
        return _result(started, "transient_error", "access_denied", status)
    if status == 429:
        return _result(started, "transient_error", "rate_limited", status)
    if 500 <= status < 600:
        return _result(started, "transient_error", "server_error", status)
    return _result(started, "hard_failure", "unexpected_status", status)


def _result(
    started: float,
    outcome: str,
    category: str,
    status: int | None,
) -> CheckResult:
    elapsed = max(0, min(300000, round((time.monotonic() - started) * 1000)))
    return CheckResult(outcome, category, status, elapsed)


def run(*, limit: int, dry_run: bool = False) -> dict[str, int]:
    rows = resource_quality_repo.link_check_batch(limit=limit)
    summary = {"checked": 0, "available": 0, "hard_failure": 0, "transient_error": 0}
    session = requests.Session()
    for row in rows:
        result = check_resource(row, session)
        summary["checked"] += 1
        summary[result.outcome] += 1
        if not dry_run:
            resource_quality_repo.record_link_check(
                str(row["resource_id"]),
                asdict(result),
            )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Check cached learning-resource links")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    summary = run(limit=max(1, min(args.limit, 200)), dry_run=args.dry_run)
    print(" ".join(f"{key}={value}" for key, value in summary.items()))


if __name__ == "__main__":
    main()
