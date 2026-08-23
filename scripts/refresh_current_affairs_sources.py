"""Refresh expiring current-affairs facts from strict official PIB releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time as time_module
import unicodedata
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import (  # noqa: E402
    CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS,
    EXPECTED_SUPABASE_PROJECT_REF,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
    supabase_project_ref_matches,
)
from config.source_rollout import ROTATION_CHAPTER_KEYS  # noqa: E402
from config.syllabus import SYLLABUS  # noqa: E402
from scripts.import_source_documents import (  # noqa: E402
    import_source_bundle,
    validate_source_bundle,
)
from services.current_affairs_pipeline import (  # noqa: E402
    authoritative_source_domain,
    build_event_bundle,
    cluster_current_affairs_rows,
)

PIB_RSS_URL = "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3"
PIB_SECONDARY_RSS_URL = (
    "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=1"
)
PIB_ALL_RELEASES_URL = (
    "https://www.pib.gov.in/AllRelease.aspx?MenuId=3&lang=1&reg=3"
)
RBI_PRESS_RELEASES_RSS_URL = "https://rbi.org.in/pressreleases_rss.xml"
USER_AGENT = "telegram-quiz-source-refresh/1.0 (+official-PIB-only)"
MAX_RESPONSE_BYTES = 5_000_000
MAX_FACT_SUMMARY_CHARS = 3_600
DEFAULT_MAX_ITEMS = 80
DEFAULT_MINIMUM_PER_CHAPTER = 4
MAX_FETCH_WORKERS = 6
FETCH_ATTEMPTS = 3
FETCH_RETRY_DELAY_SECONDS = 2
IST = ZoneInfo("Asia/Kolkata")
ALLOWED_CONTENT_TYPES = frozenset({
    "application/rss+xml",
    "application/xml",
    "text/xml",
    "text/html",
})


class CurrentAffairsRefreshError(RuntimeError):
    """A safe, source-readiness failure with no quiz-generation side effects."""


@dataclass(frozen=True, slots=True)
class Release:
    prid: str
    url: str
    ministry: str
    title: str
    published_at: datetime
    body: str


@dataclass(frozen=True, slots=True)
class RefreshStats:
    rss_items: int
    accepted: int
    skipped: int


CLASSIFICATIONS: dict[str, tuple[str, str, str]] = {
    "national:t01": (
        "current-affairs:national",
        "জাতীয় সাম্প্রতিক ঘটনা",
        "current-affairs:national:t01",
    ),
    "national:t02": (
        "current-affairs:national",
        "জাতীয় সাম্প্রতিক ঘটনা",
        "current-affairs:national:t02",
    ),
    "national:t03": (
        "current-affairs:national",
        "জাতীয় সাম্প্রতিক ঘটনা",
        "current-affairs:national:t03",
    ),
    "national:t04": (
        "current-affairs:national",
        "জাতীয় সাম্প্রতিক ঘটনা",
        "current-affairs:national:t04",
    ),
    "science:t01": (
        "current-affairs:science-technology",
        "বিজ্ঞান ও প্রযুক্তি",
        "current-affairs:science-technology:t01",
    ),
    "science:t02": (
        "current-affairs:science-technology",
        "বিজ্ঞান ও প্রযুক্তি",
        "current-affairs:science-technology:t02",
    ),
    "science:t03": (
        "current-affairs:science-technology",
        "বিজ্ঞান ও প্রযুক্তি",
        "current-affairs:science-technology:t03",
    ),
    "science:t04": (
        "current-affairs:science-technology",
        "বিজ্ঞান ও প্রযুক্তি",
        "current-affairs:science-technology:t04",
    ),
}

SCIENCE_SPACE_TERMS = (
    "isro", "space", "satellite", "rocket", "launch vehicle", "astronomy",
    "defence technology", "defense technology", "drdo", "missile", "naval technology",
)
SCIENCE_HEALTH_TERMS = (
    "biotechnology", "biotech", "vaccine", "genome", "genomic", "medical technology",
    "clinical", "drug discovery", "pharmaceutical", "disease surveillance", "health research",
)
SCIENCE_DIGITAL_TERMS = (
    "artificial intelligence", " ai ", "machine learning", "digital technology",
    "telecom", "semiconductor", "cyber", "quantum", "5g", "6g", "electronics",
    "supercomputer", "computing", "communication technology",
)
SCIENCE_GENERAL_TERMS = (
    "science", "technology", "research", "innovation", "scientist", "patent",
    "laboratory", "scientific", "startup", "earth sciences", "ocean technology",
)
LAW_TERMS = (
    "supreme court", "high court", "judicial", "judiciary", "legislation",
    "bill ", " act ", "rules ", "regulation", "parliament", "ordinance", "legal",
    "tribunal", "court", "justice",
)
ADMIN_TERMS = (
    "commission", "authority", "board", "council", "administration", "governance",
    "civil service", "secretary", "institution", "department", "census", "appointment",
)
DEVELOPMENT_TERMS = (
    "economy", "economic", "employment", "livelihood", "agriculture", "farmer",
    "education", "school", "university", "welfare", "social", "infrastructure",
    "rural", "urban", "women", "child", "tribal", "housing", "poverty", "scheme",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    parser.add_argument(
        "--minimum-per-chapter",
        type=int,
        default=DEFAULT_MINIMUM_PER_CHAPTER,
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Import as verified under the reviewed PIB-only ingestion policy.",
    )
    args = parser.parse_args()
    if args.max_items < 1 or args.max_items > 200:
        raise SystemExit("--max-items must be between 1 and 200")
    if args.minimum_per_chapter < 1 or args.minimum_per_chapter > 20:
        raise SystemExit("--minimum-per-chapter must be between 1 and 20")
    if args.approve and (args.validate_only or args.dry_run):
        raise SystemExit("--approve cannot be combined with --validate-only or --dry-run")
    if not (args.approve or args.validate_only or args.dry_run):
        raise SystemExit("Choose --validate-only, --dry-run, or --approve")

    rows, stats = refresh_rows(
        fetch_text=fetch_text,
        now=datetime.now(timezone.utc),
        max_items=args.max_items,
    )
    clean_rows = validate_source_bundle(rows)
    coverage = validate_current_affairs_coverage(
        clean_rows,
        minimum_per_chapter=args.minimum_per_chapter,
    )
    if args.approve:
        require_write_identity()
        imported = import_source_bundle(clean_rows, approve=True)
        imported_count = len(imported)
    else:
        imported_count = 0

    print(json.dumps({
        "ok": True,
        "rssItems": stats.rss_items,
        "accepted": stats.accepted,
        "skipped": stats.skipped,
        "sourceDomains": dict(sorted(Counter(
            str(row["source_domain"]) for row in clean_rows
        ).items())),
        "coverage": coverage,
        "imported": imported_count,
        "approved": args.approve,
    }, sort_keys=True))
    return 0


def refresh_rows(
    *,
    fetch_text,
    now: datetime,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> tuple[list[dict], RefreshStats]:
    now = _as_utc(now)
    item_batches: list[list[str]] = []
    for feed_url in (PIB_RSS_URL, PIB_SECONDARY_RSS_URL):
        try:
            feed_items = parse_rss_items(fetch_text(feed_url))
        except CurrentAffairsRefreshError:
            continue
        if feed_items:
            item_batches.append(feed_items)
    try:
        release_index_items = parse_all_release_items(fetch_text(PIB_ALL_RELEASES_URL))
    except CurrentAffairsRefreshError:
        release_index_items = []
    if release_index_items:
        item_batches.append(release_index_items)
    items = _interleave_unique(item_batches)
    if not items:
        raise CurrentAffairsRefreshError(
            "The official PIB endpoints returned no release items."
        )

    candidates: list[tuple[str, str]] = []
    skipped = 0
    seen_prids: set[str] = set()
    for raw_url in items:
        try:
            prid, release_url = canonical_release_url(raw_url)
            if prid in seen_prids:
                continue
            seen_prids.add(prid)
        except CurrentAffairsRefreshError:
            skipped += 1
            continue
        candidates.append((prid, release_url))
        if len(candidates) >= max_items:
            break

    def load_release(candidate: tuple[str, str]) -> Release | None:
        prid, release_url = candidate
        try:
            return parse_release(prid, release_url, fetch_text(release_url))
        except CurrentAffairsRefreshError:
            return None

    rows: list[dict] = []
    workers = min(MAX_FETCH_WORKERS, max(1, len(candidates)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for release in executor.map(load_release, candidates):
            if release is None or not release_is_current(release.published_at, now):
                skipped += 1
                continue
            try:
                rows.append(release_to_source_row(release, now))
            except ValueError:
                # A real PIB page can be complete enough to parse while still
                # containing no sentence that satisfies the exact-span atomic
                # claim policy. Reject that one release without discarding the
                # rest of the independently valid refresh batch.
                skipped += 1

    rbi_rows, rbi_stats = refresh_rbi_rows(
        fetch_text=fetch_text,
        now=now,
        max_items=max_items,
    )
    rows.extend(rbi_rows)
    skipped += rbi_stats.skipped
    if not rows:
        raise CurrentAffairsRefreshError(
            "No current, complete PIB releases passed the source-safety checks."
        )
    return cluster_current_affairs_rows(rows), RefreshStats(
        rss_items=len(items) + rbi_stats.rss_items,
        accepted=len(rows),
        skipped=skipped,
    )


def refresh_rbi_rows(*, fetch_text, now: datetime, max_items: int) -> tuple[list[dict], RefreshStats]:
    """Read only the official RBI press-release feed, failing closed per item.

    RBI is an independently operated primary authority.  Its feed embeds the
    release text, so no unaudited third-party extraction or PDF parsing is used.
    A temporary RBI outage never blocks valid PIB coverage.
    """
    try:
        raw_items = parse_rbi_rss_items(fetch_text(RBI_PRESS_RELEASES_RSS_URL))
    except Exception:
        return [], RefreshStats(rss_items=0, accepted=0, skipped=0)
    rows: list[dict] = []
    skipped = 0
    for item in raw_items[:max_items]:
        try:
            release = rbi_item_to_release(item)
            if not release_is_current(release.published_at, now):
                skipped += 1
                continue
            rows.append(release_to_source_row(release, now))
        except (CurrentAffairsRefreshError, ValueError):
            skipped += 1
    return rows, RefreshStats(rss_items=len(raw_items), accepted=len(rows), skipped=skipped)


def _interleave_unique(batches: list[list[str]]) -> list[str]:
    """Mix official endpoint results so one feed cannot starve broad coverage."""
    items: list[str] = []
    seen: set[str] = set()
    offsets = [0] * len(batches)
    while True:
        added = False
        for index, batch in enumerate(batches):
            if offsets[index] >= len(batch):
                continue
            item = batch[offsets[index]]
            offsets[index] += 1
            added = True
            if item not in seen:
                seen.add(item)
                items.append(item)
        if not added:
            return items


def fetch_text(url: str) -> str:
    requested_domain = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if requested_domain not in {"pib.gov.in", "rbi.org.in"}:
        raise CurrentAffairsRefreshError("Current-affairs source host is not approved.")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/html;q=0.9",
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                status = getattr(response, "status", 200)
                encoding = response.headers.get_content_charset() or "utf-8"
                content_type = response.headers.get_content_type().lower()
                final_url = response.geturl()
            break
        except HTTPError as exc:
            last_error = exc
            if 400 <= exc.code < 500 and exc.code != 429:
                raise CurrentAffairsRefreshError(
                    "Official current-affairs source request was rejected."
                ) from exc
        except Exception as exc:
            last_error = exc
        if attempt < FETCH_ATTEMPTS:
            time_module.sleep(FETCH_RETRY_DELAY_SECONDS * attempt)
    else:
        raise CurrentAffairsRefreshError(
            "Official current-affairs source request failed."
        ) from last_error
    final = urlparse(final_url)
    if (
        final.scheme != "https"
        or (final.hostname or "").lower().removeprefix("www.") != requested_domain
    ):
        raise CurrentAffairsRefreshError("Official current-affairs source redirected outside its host.")
    if status != 200 or len(payload) > MAX_RESPONSE_BYTES:
        raise CurrentAffairsRefreshError("Official current-affairs source response was rejected.")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise CurrentAffairsRefreshError("Official current-affairs source content type was rejected.")
    try:
        return payload.decode(encoding)
    except (LookupError, UnicodeDecodeError) as exc:
        raise CurrentAffairsRefreshError("Official current-affairs source encoding was rejected.") from exc


def parse_rss_items(xml_text: str) -> list[str]:
    try:
        root = SafeET.fromstring(xml_text)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise CurrentAffairsRefreshError("The official PIB RSS feed was malformed.") from exc
    links: list[str] = []
    for item in (node for node in root.iter() if _local_name(node.tag) == "item"):
        link = next(
            (
                _clean_text(child.text or "")
                for child in item
                if _local_name(child.tag) == "link"
            ),
            "",
        )
        if link:
            links.append(link)
    return links


def parse_rbi_rss_items(xml_text: str) -> list[dict[str, str]]:
    """Parse the narrow, documented RBI RSS item shape without trusting HTML."""
    try:
        root = SafeET.fromstring(xml_text)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise CurrentAffairsRefreshError("The official RBI RSS feed was malformed.") from exc
    rows: list[dict[str, str]] = []
    for item in (node for node in root.iter() if _local_name(node.tag) == "item"):
        fields = {
            _local_name(child.tag): _clean_text(child.text or "")
            for child in item
        }
        if all(fields.get(key) for key in ("title", "description", "link", "pubdate")):
            rows.append(fields)
    return rows


def rbi_item_to_release(item: dict[str, str]) -> Release:
    """Turn one canonical RBI RSS item into a provenance-preserving release."""
    url = str(item.get("link") or "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower().removeprefix("www.") != "rbi.org.in":
        raise CurrentAffairsRefreshError("RBI RSS item points outside the official host.")
    query = {key.lower(): values for key, values in parse_qs(parsed.query).items()}
    prid = (query.get("prid") or [""])[0]
    if not re.fullmatch(r"[0-9]{3,12}", prid):
        raise CurrentAffairsRefreshError("RBI RSS item has an invalid release identifier.")
    parser = _RBITextParser()
    parser.feed(str(item["description"]))
    parser.close()
    body = _clean_body(parser.parts)
    if len(body) < 250:
        raise CurrentAffairsRefreshError("RBI release is missing sufficient official text.")
    try:
        published_at = parsedate_to_datetime(str(item["pubdate"]))
    except (TypeError, ValueError) as exc:
        raise CurrentAffairsRefreshError("RBI RSS item has an invalid publication date.") from exc
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=IST)
    return Release(
        prid=f"rbi-{prid}", url=url, ministry="Reserve Bank of India",
        title=_clean_text(str(item["title"])), published_at=published_at.astimezone(timezone.utc), body=body,
    )


class _RBITextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1
        elif tag.lower() in {"p", "li", "tr", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag.lower() in {"p", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def parse_all_release_items(html_text: str) -> list[str]:
    parser = _PIBReleaseLinkParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as exc:
        raise CurrentAffairsRefreshError(
            "The official PIB release index was malformed."
        ) from exc
    return parser.links


class _PIBReleaseLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next(
            (value or "" for key, value in attrs if key.lower() == "href"),
            "",
        )
        if not href or "prid=" not in href.casefold():
            return
        candidate = urljoin(PIB_ALL_RELEASES_URL, href)
        try:
            canonical_release_url(candidate)
        except CurrentAffairsRefreshError:
            return
        self.links.append(candidate)


def canonical_release_url(raw_url: str) -> tuple[str, str]:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    if host.removeprefix("www.") != "pib.gov.in" or parsed.scheme != "https":
        raise CurrentAffairsRefreshError("RSS item points outside the official PIB host.")
    if parsed.path.lower() not in {
        "/pressreleaseiframepage.aspx",
        "/pressreleasepage.aspx",
        "/pressrelesedetail.aspx",
        "/pressreleasedetail.aspx",
        "/pressrelesedetailm.aspx",
        "/pressreleasedetailm.aspx",
    }:
        raise CurrentAffairsRefreshError("RSS item is not a PIB press-release page.")
    query = {key.lower(): values for key, values in parse_qs(parsed.query).items()}
    prid = (query.get("prid") or [""])[0]
    if not re.fullmatch(r"[0-9]{5,12}", prid):
        raise CurrentAffairsRefreshError("PIB press release has an invalid identifier.")
    return prid, f"https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID={prid}"


def parse_release(prid: str, url: str, html_text: str) -> Release:
    parser = _PIBReleaseParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as exc:
        raise CurrentAffairsRefreshError("PIB press-release HTML could not be parsed.") from exc
    ministry = _clean_text(" ".join(parser.fields["ministry"]))
    title = _clean_text(" ".join(parser.fields["title"]))
    date_text = _clean_text(" ".join(parser.fields["date"]))
    body = _clean_body(parser.body_parts)
    if len(ministry) < 3 or len(title) < 12 or len(body) < 250:
        raise CurrentAffairsRefreshError("PIB press release is missing required official content.")
    published_at = parse_pib_datetime(date_text)
    return Release(
        prid=prid,
        url=url,
        ministry=ministry,
        title=title,
        published_at=published_at,
        body=body,
    )


class _PIBReleaseParser(HTMLParser):
    _FIELD_IDS = {
        "ministryname": "ministry",
        "titleh2": "title",
        "prdatetime": "date",
    }
    _BODY_TAGS = {"p", "li"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, list[str]] = {
            "ministry": [],
            "title": [],
            "date": [],
        }
        self.body_parts: list[str] = []
        self._stack: list[tuple[str, str | None, bool, bool]] = []
        self._active_field: str | None = None
        self._active_field_depth = 0
        self._skip_depth = 0
        self._body_depth = 0
        self._body_started = False
        self._body_stopped = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): (value or "") for key, value in attrs}
        element_id = attr_map.get("id", "").lower()
        skip_started = tag.lower() in {"script", "style", "noscript"}
        body_started = (
            self._body_started
            and not self._body_stopped
            and tag.lower() in self._BODY_TAGS
        )
        self._stack.append((tag.lower(), self._active_field, skip_started, body_started))
        if skip_started:
            self._skip_depth += 1
        if element_id == "lblviews":
            self._body_stopped = True
            self._body_depth = 0
        field = self._FIELD_IDS.get(element_id)
        if field:
            self._active_field = field
            self._active_field_depth = len(self._stack)
        if body_started:
            self._body_depth += 1
            self.body_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        _opened_tag, previous_field, skip_started, body_started = self._stack.pop()
        if (
            self._active_field
            and self._active_field_depth == len(self._stack) + 1
        ):
            ended_field = self._active_field
            self._active_field = previous_field
            self._active_field_depth = 0
            if ended_field == "date":
                self._body_started = True
        if body_started:
            self._body_depth = max(0, self._body_depth - 1)
            self.body_parts.append("\n")
        if skip_started:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._active_field:
            self.fields[self._active_field].append(data)
        if self._body_depth and not self._body_stopped:
            self.body_parts.append(data)


def parse_pib_datetime(value: str) -> datetime:
    match = re.search(
        r"\b([0-3]?[0-9])\s+([A-Z]{3})\s+([0-9]{4})\s+"
        r"([0-1]?[0-9]):([0-5][0-9])\s*(AM|PM)\b",
        value.upper(),
    )
    if not match:
        raise CurrentAffairsRefreshError("PIB release has an invalid publication date.")
    day, month_text, year, hour_text, minute_text, meridiem = match.groups()
    months = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    }
    month = months.get(month_text)
    hour = int(hour_text)
    if month is None or not 1 <= hour <= 12:
        raise CurrentAffairsRefreshError("PIB release has an invalid publication date.")
    if meridiem == "AM":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    try:
        local = datetime(
            int(year),
            month,
            int(day),
            hour,
            int(minute_text),
            tzinfo=IST,
        )
    except ValueError as exc:
        raise CurrentAffairsRefreshError("PIB release has an invalid publication date.") from exc
    return local.astimezone(timezone.utc)


def release_is_current(published_at: datetime, now: datetime) -> bool:
    age = now - _as_utc(published_at)
    return -timedelta(hours=1) <= age <= timedelta(
        days=CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS
    )


def classify_release(release: Release) -> tuple[str, str, str]:
    headline = f" {release.title} {release.ministry} ".casefold()
    text = f"{headline} {release.body[:1600]} ".casefold()
    if _contains_any(text, SCIENCE_SPACE_TERMS):
        return CLASSIFICATIONS["science:t01"]
    if _contains_any(text, SCIENCE_HEALTH_TERMS):
        return CLASSIFICATIONS["science:t02"]
    if _contains_any(text, SCIENCE_DIGITAL_TERMS):
        return CLASSIFICATIONS["science:t03"]
    if _contains_any(text, LAW_TERMS):
        return CLASSIFICATIONS["national:t03"]
    if _contains_any(text, DEVELOPMENT_TERMS):
        return CLASSIFICATIONS["national:t04"]
    if _contains_any(headline, ADMIN_TERMS):
        return CLASSIFICATIONS["national:t02"]
    general_science_matches = {
        term for term in SCIENCE_GENERAL_TERMS if term in text
    }
    if (
        _contains_any(headline, SCIENCE_GENERAL_TERMS)
        or len(general_science_matches) >= 2
    ):
        return CLASSIFICATIONS["science:t04"]
    return CLASSIFICATIONS["national:t01"]


def release_to_source_row(release: Release, accessed_at: datetime) -> dict:
    chapter_key, chapter_name, micro_topic_key = classify_release(release)
    topic_name = _micro_topic_name(micro_topic_key)
    published_at = _as_utc(release.published_at)
    accessed_at = _as_utc(accessed_at)
    local_publication_date = published_at.astimezone(IST).date()
    event = build_event_bundle(
        title=release.title,
        body=release.body,
        ministry=release.ministry,
        source_url=release.url,
        published_at=published_at,
    )
    expires_at = max(
        datetime.fromisoformat(str(event["expires_at"])),
        accessed_at + timedelta(days=1),
    )
    event["expires_at"] = expires_at.isoformat()
    for claim in event.get("claims") or []:
        if datetime.fromisoformat(str(claim["expires_at"])) < expires_at:
            claim["expires_at"] = expires_at.isoformat()
    body = _truncate_at_word(release.body, MAX_FACT_SUMMARY_CHARS - 300)
    source_domain = authoritative_source_domain(release.url)
    source_label = "Official RBI press release" if source_domain == "rbi.org.in" else "Official PIB release"
    source_prefix = "rbi" if source_domain == "rbi.org.in" else "pib"
    fact_summary = (
        f"{source_label} dated {published_at.astimezone(IST).date().isoformat()} "
        f"from {release.ministry}. Title: {release.title}. "
        f"Verified release text: {body}"
    )
    digest = hashlib.sha256(
        "\n".join((
            release.prid,
            release.ministry,
            release.title,
            published_at.isoformat(),
            release.body,
        )).encode("utf-8")
    ).hexdigest()[:12]
    return {
        "subject_key": "current-affairs",
        "chapter": chapter_name,
        "micro_topic_key": micro_topic_key,
        "micro_topic_name": topic_name,
        "source_url": release.url,
        "source_title": release.title,
        "source_domain": source_domain,
        "source_kind": "official",
        "source_published_at": published_at.isoformat(),
        "source_accessed_at": accessed_at.isoformat(),
        "fact_summary": fact_summary,
        "fact_version": (
            f"{source_prefix}-{release.prid}-{local_publication_date.isoformat()}-{digest}"
        ),
        "expires_at": expires_at.isoformat(),
        "verification_notes": (
            "Official document identity and exact-span atomic claims were validated "
            "under official_exact_span_v1; correction-like releases require review."
        ),
        "current_affairs_event": event,
        "_chapter_key": chapter_key,
    }


def validate_current_affairs_coverage(
    rows: list[dict],
    *,
    minimum_per_chapter: int,
) -> dict[str, int]:
    expected = set(ROTATION_CHAPTER_KEYS["current-affairs"])
    counts = Counter(
        _chapter_key_for_name(str(row["chapter"]))
        for row in rows
    )
    topic_counts: dict[str, set[str]] = {key: set() for key in expected}
    for row in rows:
        topic_counts[_chapter_key_for_name(str(row["chapter"]))].add(
            str(row["micro_topic_key"])
        )
    missing = [
        key
        for key in sorted(expected)
        if counts[key] < minimum_per_chapter or len(topic_counts[key]) < 2
    ]
    if missing:
        raise CurrentAffairsRefreshError(
            "Current-affairs source coverage is below the approved chapter threshold: "
            + ", ".join(missing)
        )
    return {key: counts[key] for key in sorted(expected)}


def require_write_identity() -> None:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise CurrentAffairsRefreshError("Supabase write configuration is incomplete.")
    if (
        not EXPECTED_SUPABASE_PROJECT_REF
        or not supabase_project_ref_matches()
    ):
        raise CurrentAffairsRefreshError("Supabase project ownership check failed.")


def _micro_topic_name(micro_topic_key: str) -> str:
    for chapter in SYLLABUS["current-affairs"]:
        for topic in chapter.micro_topics:
            if topic.key == micro_topic_key:
                return topic.name
    raise CurrentAffairsRefreshError("Classifier selected an unknown current-affairs topic.")


def _chapter_key_for_name(chapter_name: str) -> str:
    for chapter in SYLLABUS["current-affairs"]:
        if chapter.name == chapter_name:
            return chapter.key
    raise CurrentAffairsRefreshError("Current-affairs row uses an unknown chapter.")


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _clean_text(value: str) -> str:
    value = "".join(
        char if char.isspace() or not unicodedata.category(char).startswith("C") else " "
        for char in value
    )
    return re.sub(r"\s+", " ", value).strip()


def _clean_body(parts: list[str]) -> str:
    lines = []
    for raw in "".join(parts).splitlines():
        line = _clean_text(raw)
        if not line or line in {"*******", "*****"}:
            continue
        lines.append(line)
    return "\n".join(lines)


def _truncate_at_word(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0].rstrip() + "…"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise CurrentAffairsRefreshError("Current-affairs timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
