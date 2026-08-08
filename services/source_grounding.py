"""Fail-closed selection of operator-verified facts for quiz generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from config.settings import APP_TIMEZONE, CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS
from config.syllabus import get_chapter
from services.current_affairs_pipeline import (
    EVENT_POLICY_VERSION,
    authoritative_source_domain,
)
from services.question_validation import QuizValidationError
from storage import source_documents_repo
from utils.source_validation import is_placeholder_source

LOCAL_TIMEZONE = ZoneInfo(APP_TIMEZONE)


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
    micro_topic_id: str = ""
    micro_topic_key: str = ""
    micro_topic_name: str = ""
    current_affairs_event_date: str | None = None
    current_affairs_practice_pool: str | None = None
    current_affairs_verification_policy: str | None = None


@dataclass(frozen=True, slots=True)
class MicroTopicReference:
    id: str
    key: str
    name: str


@dataclass(frozen=True, slots=True)
class GroundingBundle:
    subject_key: str
    chapter: str
    micro_topic_id: str
    micro_topic_key: str
    micro_topic_name: str
    documents: tuple[SourceDocument, ...]
    topics: tuple[MicroTopicReference, ...] = ()

    @property
    def source_required(self) -> bool:
        return bool(self.documents)

    @property
    def available_topics(self) -> tuple[MicroTopicReference, ...]:
        if self.topics:
            return self.topics
        seen: dict[str, MicroTopicReference] = {}
        for row in self.documents:
            key = row.micro_topic_key or self.micro_topic_key
            seen.setdefault(key, MicroTopicReference(
                id=row.micro_topic_id or self.micro_topic_id,
                key=key,
                name=row.micro_topic_name or self.micro_topic_name,
            ))
        return tuple(seen.values())

    @property
    def allowed_micro_topics(self) -> dict[str, str]:
        return {row.key: row.id for row in self.available_topics}

    @property
    def source_ids(self) -> set[str]:
        return {row.id for row in self.documents}

    @property
    def source_topics(self) -> dict[str, tuple[str, str]]:
        return {
            row.id: (
                row.micro_topic_id or self.micro_topic_id,
                row.micro_topic_key or self.micro_topic_key,
            )
            for row in self.documents
        }

    @property
    def topic_keys(self) -> set[str]:
        return {row.key for row in self.available_topics}

    @property
    def required_source_diversity(self) -> int:
        return min(4, len(self.source_ids)) if self.source_required else 0

    @property
    def required_topic_diversity(self) -> int:
        return min(4, len(self.topic_keys))

    def prompt_facts(self) -> list[dict]:
        return [
            {
                "source_document_id": row.id,
                "micro_topic_key": row.micro_topic_key or self.micro_topic_key,
                "micro_topic_name": row.micro_topic_name or self.micro_topic_name,
                "source_title": row.title,
                "source_domain": row.domain,
                "source_kind": row.kind,
                "source_published_at": row.published_at,
                "fact_version": row.fact_version,
                "verified_facts": row.fact_summary,
                "current_affairs_event_date": row.current_affairs_event_date,
                "current_affairs_practice_pool": row.current_affairs_practice_pool,
                "current_affairs_verification_policy": (
                    row.current_affairs_verification_policy
                ),
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
    documents = tuple(
        _validated_document(row, subject_key, target_date)
        for row in rows
    )
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


def load_generation_bundle(
    subject_key: str,
    chapter: str,
    target_date: date,
) -> GroundingBundle:
    """Prefer verified facts, then use curated timeless syllabus context.

    Current affairs deliberately has no model-memory fallback.
    """
    try:
        return load_grounding_bundle(subject_key, chapter, target_date)
    except QuizValidationError:
        if subject_key == "current-affairs":
            raise

    configured = get_chapter(subject_key, chapter)
    ordered_keys = [topic.key for topic in configured.micro_topics]
    rows_by_key = {
        str(row.get("key") or ""): row
        for row in source_documents_repo.list_micro_topics(ordered_keys)
    }
    topics = tuple(
        MicroTopicReference(
            id=str(rows_by_key[topic.key].get("id") or ""),
            key=topic.key,
            name=topic.name,
        )
        for topic in configured.micro_topics
        if topic.key in rows_by_key
    )
    if len(topics) != len(configured.micro_topics) or any(not row.id for row in topics):
        raise QuizValidationError(
            f"Curated syllabus micro-topics are not synchronized for {subject_key}/{chapter}."
        )
    return GroundingBundle(
        subject_key=subject_key,
        chapter=chapter,
        micro_topic_id=topics[0].id,
        micro_topic_key=topics[0].key,
        micro_topic_name=topics[0].name,
        documents=(),
        topics=topics,
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
    if is_placeholder_source(url, title):
        raise QuizValidationError(f"Source {source_id} uses placeholder source metadata.")
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
        event_policy = _optional(row.get("current_affairs_verification_policy"))
        event_date = _optional(row.get("current_affairs_event_date"))
        practice_pool = _optional(row.get("current_affairs_practice_pool"))
        if event_policy:
            if event_policy != EVENT_POLICY_VERSION or not event_date or not practice_pool:
                raise QuizValidationError("Current-affairs event evidence contract is invalid.")
            try:
                authoritative_source_domain(domain)
            except ValueError as exc:
                raise QuizValidationError(
                    "Current-affairs event evidence source is not authoritative."
                ) from exc
            event_age = (target_date - _as_date(event_date)).days
            if not 0 <= event_age <= 180:
                raise QuizValidationError(
                    "Current-affairs event date is outside the revision window."
                )
        else:
            oldest = target_date - timedelta(days=CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS)
            published_date = _as_local_date(published_at)
            if published_date < oldest or published_date > target_date:
                raise QuizValidationError(
                    "Current-affairs source date is outside the allowed window."
                )

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
        micro_topic_id=_required(row, "micro_topic_id"),
        micro_topic_key=_required(row, "micro_topic_key"),
        micro_topic_name=_required(row, "micro_topic_name"),
        current_affairs_event_date=_optional(
            row.get("current_affairs_event_date")
        ),
        current_affairs_practice_pool=_optional(
            row.get("current_affairs_practice_pool")
        ),
        current_affairs_verification_policy=_optional(
            row.get("current_affairs_verification_policy")
        ),
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


def _as_local_date(value: str) -> date:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(LOCAL_TIMEZONE).date()
    except ValueError as exc:
        raise QuizValidationError("Verified source contains an invalid date.") from exc
