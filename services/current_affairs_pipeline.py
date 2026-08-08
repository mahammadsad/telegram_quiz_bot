"""Deterministic current-affairs event and atomic-claim construction.

The ingestion layer treats an authentic official document and a verified claim
as different things.  Claims are extracted as exact evidence spans and carry a
versioned policy decision; releases that look like corrections are routed to
review instead of being silently accepted.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlparse

EVENT_POLICY_VERSION = "official_exact_span_v1"
EVENT_CLUSTER_VERSION = 1
MAX_EVENT_CLAIMS = 8

AUTHORITATIVE_SOURCE_DOMAINS = frozenset(
    {
        "cmo.wb.gov.in",
        "drdo.gov.in",
        "eci.gov.in",
        "finance.gov.in",
        "indiabudget.gov.in",
        "isro.gov.in",
        "mospi.gov.in",
        "pib.gov.in",
        "rbi.org.in",
        "sci.gov.in",
        "sebi.gov.in",
        "wb.gov.in",
    }
)

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "at", "by", "for", "from", "government", "in",
        "india", "ministry", "of", "official", "on", "press", "release",
        "the", "to", "with",
    }
)
_CORRECTION_TERMS = (
    "clarification", "corrected", "correction", "corrigendum", "erratum",
    "revised", "supersedes", "withdrawn",
)
_CATEGORY_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("west_bengal", ("west bengal", "kolkata", "bengal government")),
    ("economy_banking", ("rbi", "reserve bank", "banking", "monetary policy", "inflation", "gdp", "sebi")),
    ("science_technology", ("isro", "drdo", "space", "satellite", "science", "technology", "research", "quantum", "semiconductor")),
    ("appointments_awards", ("appointed", "appointment", "award", "honour", "honor", "chairperson", "secretary")),
    ("sports", ("championship", "olympic", "paralympic", "sports", "tournament", "world cup")),
    ("reports_indices", ("index", "report", "ranking", "survey", "statistics")),
    ("international", ("agreement", "bilateral", "global", "international", "summit", "united nations")),
    ("schemes", ("beneficiary", "mission", "programme", "program", "scheme", "yojana")),
)
_EXPIRY_DAYS = {
    "appointments_awards": 180,
    "economy_banking": 90,
    "international": 180,
    "polity_governance": 180,
    "reports_indices": 180,
    "schemes": 180,
    "science_technology": 180,
    "sports": 90,
    "west_bengal": 180,
}
_MONTHS = {
    name.casefold(): index
    for index, name in enumerate(
        (
            "", "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        )
    )
    if name
}
_MONTH_PATTERN = "|".join(_MONTHS)
_DATE_PATTERNS = (
    re.compile(rf"\b([0-3]?\d)\s+({_MONTH_PATTERN})\s+(20\d{{2}})\b", re.I),
    re.compile(rf"\b({_MONTH_PATTERN})\s+([0-3]?\d),?\s+(20\d{{2}})\b", re.I),
    re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])-([0-2]\d|3[01])\b"),
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class AtomicClaim:
    claim_key: str
    canonical_claim: str
    evidence_span: str
    valid_from: str
    review_after: str
    expires_at: str
    verification_status: str
    review_required: bool
    verification_policy: str

    def as_dict(self) -> dict[str, object]:
        return {
            "claim_key": self.claim_key,
            "canonical_claim": self.canonical_claim,
            "evidence_span": self.evidence_span,
            "valid_from": self.valid_from,
            "review_after": self.review_after,
            "expires_at": self.expires_at,
            "verification_status": self.verification_status,
            "review_required": self.review_required,
            "verification_policy": self.verification_policy,
        }


def authoritative_source_domain(url_or_domain: str) -> str:
    """Return the canonical trusted domain or reject the source."""
    parsed = urlparse(url_or_domain)
    domain = (parsed.hostname or url_or_domain).casefold().strip().removeprefix("www.")
    if domain not in AUTHORITATIVE_SOURCE_DOMAINS:
        raise ValueError("Current-affairs source is not in the authoritative registry.")
    return domain


def build_event_bundle(
    *,
    title: str,
    body: str,
    ministry: str,
    source_url: str,
    published_at: datetime,
) -> dict[str, object]:
    """Build a deterministic event cluster and exact-span atomic claims."""
    if published_at.tzinfo is None:
        raise ValueError("Current-affairs publication time must be timezone-aware.")
    published_at = published_at.astimezone(timezone.utc)
    source_domain = authoritative_source_domain(source_url)
    combined = f"{title}\n{ministry}\n{body}"
    event_date, date_precision = _event_date(combined, published_at.date())
    category = _category(combined)
    geography = _geography(combined, category)
    correction_state = (
        "suspected" if any(term in combined.casefold() for term in _CORRECTION_TERMS)
        else "none"
    )
    review_required = correction_state != "none"
    importance = _importance(combined, category)
    confidence = 0.85 if date_precision == "explicit" else 0.72
    if review_required:
        confidence = min(confidence, 0.49)
    cluster_key = _cluster_key(title, event_date, category, geography)
    expires_on = event_date + timedelta(days=_EXPIRY_DAYS[category])
    review_on = min(expires_on, event_date + timedelta(days=30))
    valid_from = datetime.combine(event_date, datetime.min.time(), tzinfo=timezone.utc)
    review_after = datetime.combine(review_on, datetime.min.time(), tzinfo=timezone.utc)
    expires_at = datetime.combine(expires_on, datetime.max.time(), tzinfo=timezone.utc)
    claims = _atomic_claims(
        body,
        cluster_key=cluster_key,
        valid_from=valid_from,
        review_after=review_after,
        expires_at=expires_at,
        review_required=review_required,
    )
    if not claims:
        raise ValueError("Official release has no safe atomic claim evidence spans.")
    return {
        "cluster_key": cluster_key,
        "cluster_version": EVENT_CLUSTER_VERSION,
        "event_title": _clean(title),
        "event_date": event_date.isoformat(),
        "event_end_date": None,
        "event_date_precision": date_precision,
        "geography": geography,
        "category": category,
        "organizations": [_clean(ministry)],
        "importance": importance,
        "confidence": confidence,
        "valid_from": valid_from.isoformat(),
        "review_after": review_after.isoformat(),
        "expires_at": expires_at.isoformat(),
        "correction_state": correction_state,
        "verification_policy": EVENT_POLICY_VERSION,
        "verification_status": "review_required" if review_required else "verified",
        "review_required": review_required,
        "source_domain": source_domain,
        "publication_date": published_at.date().isoformat(),
        "claims": [claim.as_dict() for claim in claims],
    }


def cluster_current_affairs_rows(rows: list[dict]) -> list[dict]:
    """Coalesce near-identical same-event releases without merging their claims."""
    representatives: list[dict] = []
    for row in rows:
        event = row.get("current_affairs_event")
        if not isinstance(event, dict):
            continue
        match = next((
            candidate
            for candidate in representatives
            if _same_event(candidate, event)
        ), None)
        if match is None:
            representatives.append(event)
            continue
        event["cluster_key"] = match["cluster_key"]
        event["cluster_version"] = match["cluster_version"]
        for claim in event.get("claims", []):
            if isinstance(claim, dict):
                claim["claim_key"] = _hash(
                    f"{event['cluster_key']}\n{_normalized(str(claim.get('canonical_claim') or ''))}"
                )
    return rows


def practice_pool(event_date: date, *, target_date: date, importance: int) -> str | None:
    """Classify an event into the audited revision windows."""
    age = (target_date - event_date).days
    if age < 0:
        return None
    if age <= 7:
        return "daily"
    if age <= 30:
        return "weekly"
    if age <= 90:
        return "monthly"
    if age <= 180 and importance >= 4:
        return "six_month"
    return None


def _atomic_claims(
    body: str,
    *,
    cluster_key: str,
    valid_from: datetime,
    review_after: datetime,
    expires_at: datetime,
    review_required: bool,
) -> tuple[AtomicClaim, ...]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT.split(body):
        claim = _clean(raw)
        normalized = _normalized(claim)
        if not 40 <= len(claim) <= 500 or len(_WORD.findall(normalized)) < 7:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(claim)
        if len(candidates) >= MAX_EVENT_CLAIMS:
            break
    status = "review_required" if review_required else "verified"
    return tuple(
        AtomicClaim(
            claim_key=_hash(f"{cluster_key}\n{_normalized(claim)}"),
            canonical_claim=claim,
            evidence_span=claim,
            valid_from=valid_from.isoformat(),
            review_after=review_after.isoformat(),
            expires_at=expires_at.isoformat(),
            verification_status=status,
            review_required=review_required,
            verification_policy=EVENT_POLICY_VERSION,
        )
        for claim in candidates
    )


def _event_date(text: str, publication_date: date) -> tuple[date, str]:
    candidates: list[date] = []
    for pattern_index, pattern in enumerate(_DATE_PATTERNS):
        for match in pattern.finditer(text):
            parts = match.groups()
            try:
                if pattern_index == 0:
                    value = date(int(parts[2]), _MONTHS[parts[1].casefold()], int(parts[0]))
                elif pattern_index == 1:
                    value = date(int(parts[2]), _MONTHS[parts[0].casefold()], int(parts[1]))
                else:
                    value = date(int(parts[0]), int(parts[1]), int(parts[2]))
            except ValueError:
                continue
            if publication_date - timedelta(days=180) <= value <= publication_date + timedelta(days=1):
                candidates.append(value)
    if candidates:
        return max(candidates), "explicit"
    return publication_date, "publication_fallback"


def _category(text: str) -> str:
    normalized = text.casefold()
    for category, terms in _CATEGORY_TERMS:
        if any(term in normalized for term in terms):
            return category
    return "polity_governance"


def _geography(text: str, category: str) -> str:
    normalized = text.casefold()
    if category == "west_bengal" or any(
        term in normalized for term in ("west bengal", "kolkata")
    ):
        return "west_bengal"
    if any(term in normalized for term in ("bilateral", "international", "united nations", "world")):
        return "international"
    return "india"


def _importance(text: str, category: str) -> int:
    normalized = text.casefold()
    score = 3
    if category in {"economy_banking", "science_technology", "west_bengal"}:
        score += 1
    if any(term in normalized for term in ("cabinet", "launch", "monetary policy", "supreme court", "national")):
        score += 1
    return min(5, score)


def _cluster_key(title: str, event_date: date, category: str, geography: str) -> str:
    tokens = sorted(_title_tokens(title))[:12]
    return _hash(
        "\n".join((
            str(EVENT_CLUSTER_VERSION), event_date.isoformat(), category, geography,
            " ".join(tokens),
        ))
    )


def _same_event(left: dict, right: dict) -> bool:
    if left.get("category") != right.get("category") or left.get("geography") != right.get("geography"):
        return False
    try:
        left_date = date.fromisoformat(str(left["event_date"]))
        right_date = date.fromisoformat(str(right["event_date"]))
    except (KeyError, ValueError):
        return False
    if abs((left_date - right_date).days) > 3:
        return False
    left_tokens = _title_tokens(str(left.get("event_title") or ""))
    right_tokens = _title_tokens(str(right.get("event_title") or ""))
    union = left_tokens | right_tokens
    return bool(union) and len(left_tokens & right_tokens) / len(union) >= 0.55


def _title_tokens(value: str) -> set[str]:
    return {
        token
        for token in _WORD.findall(_normalized(value))
        if len(token) > 2 and token not in _STOPWORDS
    }


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized(value: str) -> str:
    return " ".join(_WORD.findall(unicodedata.normalize("NFKC", value).casefold()))


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def known_authoritative_domains() -> Iterable[str]:
    return sorted(AUTHORITATIVE_SOURCE_DOMAINS)
