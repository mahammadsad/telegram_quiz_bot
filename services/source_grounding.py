"""Fail-closed selection of operator-verified facts for quiz generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from config.settings import CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS
from services.question_validation import QuizValidationError
from storage import source_documents_repo


@dataclass(frozen=True, slots=True)
class SourceDocument:
    id: str
    url: str
    title: str
    domain: str
    kind: str
    published_at: str | None
    accessed_at: str
    fact_summary: str
    fact_version: str
    expires_at: str | None


@dataclass(frozen=True, slots=True)
class GroundingBundle:
    subject_key: str
    chapter: str
    micro_topic_id: str
    micro_topic_key: str
    micro_topic_name: str
    documents: tuple[SourceDocument, ...]

    @property
    def source_ids(self) -> set[str]:
        return {row.id for row in self.documents}

    def prompt_facts(self) -> list[dict]:
        return [
            {
                "source_document_id": row.id,
                "source_title": row.title,
                "source_domain": row.domain,
                "source_kind": row.kind,
                "source_published_at": row.published_at,
                "fact_version": row.fact_version,
                "verified_facts": row.fact_summary,
            }
            for row in self.documents
        ]


def load_grounding_bundle(
    subject_key: str,
    chapter: str,
    target_date: date,
) -> GroundingBundle:
    rows = source_documents_repo.list_grounding_bundle(
        subject_key,
        chapter,
        target_date.isoformat(),
    )
    if not rows:
        raise QuizValidationError(
            f"No verified source facts are available for {subject_key}/{chapter}."
        )

    first_topic_id = str(rows[0].get("micro_topic_id") or "")
    same_topic = [row for row in rows if str(row.get("micro_topic_id") or "") == first_topic_id]
    documents = tuple(_validated_document(row, subject_key, target_date) for row in same_topic)
    if not first_topic_id or not documents:
        raise QuizValidationError("The grounding bundle has no reusable micro-topic or source facts.")
    return GroundingBundle(
        subject_key=subject_key,
        chapter=chapter,
        micro_topic_id=first_topic_id,
        micro_topic_key=_required(rows[0], "micro_topic_key"),
        micro_topic_name=_required(rows[0], "micro_topic_name"),
        documents=documents,
    )


def _validated_document(row: dict, subject_key: str, target_date: date) -> SourceDocument:
    source_id = _required(row, "source_document_id")
    url = _required(row, "source_url")
    title = _required(row, "source_title")
    domain = _required(row, "source_domain").lower()
    kind = _required(row, "source_kind")
    if kind not in {"official", "primary", "secondary"}:
        raise QuizValidationError(f"Source {source_id} has an invalid source kind.")
    accessed_at = _required(row, "source_accessed_at")
    fact_summary = _required(row, "fact_summary")
    fact_version = _required(row, "fact_version")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise QuizValidationError(f"Source {source_id} must use an HTTPS URL.")
    hostname = parsed.hostname.lower()
    if hostname != domain and not hostname.endswith(f".{domain}"):
        raise QuizValidationError(f"Source {source_id} URL does not match its verified domain.")

    published_at = _optional(row.get("source_published_at"))
    expires_at = _optional(row.get("expires_at"))
    if expires_at and _as_date(expires_at) < target_date:
        raise QuizValidationError(f"Source {source_id} expired before the quiz date.")
    if subject_key == "current-affairs":
        if kind == "secondary":
            raise QuizValidationError("Current-affairs grounding must use official or primary sources.")
        if not published_at:
            raise QuizValidationError("Current-affairs sources must include a publication date.")
        oldest = target_date - timedelta(days=CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS)
        published_date = _as_date(published_at)
        if published_date < oldest or published_date > target_date:
            raise QuizValidationError("Current-affairs source date is outside the allowed window.")

    return SourceDocument(
        id=source_id,
        url=url,
        title=title,
        domain=domain,
        kind=kind,
        published_at=published_at,
        accessed_at=accessed_at,
        fact_summary=fact_summary,
        fact_version=fact_version,
        expires_at=expires_at,
    )


def _required(row: dict, key: str) -> str:
    value = str(row.get(key) or "").strip()
    if not value:
        raise QuizValidationError(f"Verified source bundle is missing {key}.")
    return value


def _optional(value: object) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def _as_date(value: str) -> date:
    try:
        text = value.replace("Z", "+00:00")
        if "T" in text or "+" in text[10:]:
            return datetime.fromisoformat(text).astimezone(timezone.utc).date()
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise QuizValidationError("Verified source contains an invalid date.") from exc
