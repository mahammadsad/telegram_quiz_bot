"""Stable identities for knowledge points and question variants.

Identity deliberately excludes source access timestamps, verification runs,
usage counters, model metadata, and other mutable operational fields.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from utils.hashing import content_hash_part, normalize_text

_RELATION_ALIASES: dict[str, tuple[str, bool]] = {
    "capital": ("capital_of", False),
    "has_capital": ("capital_of", False),
    "capital_of": ("capital_of", False),
    "is_capital_of": ("capital_of", True),
    "capital_of_country": ("capital_of", True),
}


def _identity_text(value: Any) -> str:
    return normalize_text(str(value or ""))


def _digest(parts: Mapping[str, Any]) -> str:
    payload = "".join(
        content_hash_part(name, _identity_text(value))
        for name, value in parts.items()
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def knowledge_key(
    *,
    subject: str,
    entity: str,
    relation: str,
    answer_value: str,
    time_scope: str = "timeless",
    inverse: bool = False,
) -> str:
    """Return one key for a fact regardless of wording or inverse phrasing.

    Callers should pass semantic fields, not a generated question stem. Known
    inverse relation names are canonicalized automatically; ``inverse=True``
    supports syllabus relations not yet present in the small alias table.
    """
    canonical_relation, alias_is_inverse = _RELATION_ALIASES.get(
        _identity_text(relation),
        (_identity_text(relation), False),
    )
    canonical_entity = entity
    canonical_value = answer_value
    if inverse or alias_is_inverse:
        canonical_entity, canonical_value = canonical_value, canonical_entity
    fields = {
        "subject": subject,
        "entity": canonical_entity,
        "relation": canonical_relation,
        "answer_value": canonical_value,
        "time_scope": time_scope or "timeless",
    }
    if any(not _identity_text(value) for value in fields.values()):
        raise ValueError("knowledge identity fields must be non-empty")
    return _digest(fields)


def variant_fingerprint(
    *,
    stem: str,
    options: Sequence[str],
    correct_index: int,
    language: str,
) -> str:
    """Hash immutable displayed MCQ content, excluding mutable metadata."""
    if len(options) != 4 or isinstance(correct_index, bool) or correct_index not in range(4):
        raise ValueError("variant identity requires four options and a valid answer")
    normalized_options = [_identity_text(option) for option in options]
    if not _identity_text(stem) or any(not option for option in normalized_options):
        raise ValueError("variant identity content must be non-empty")
    return _digest({
        "stem": stem,
        "option_1": normalized_options[0],
        "option_2": normalized_options[1],
        "option_3": normalized_options[2],
        "option_4": normalized_options[3],
        "answer": normalized_options[correct_index],
        "language": language,
    })


def source_fact_checksum(
    *,
    source_document_id: str,
    canonical_fact: str,
    evidence_span: str,
    document_version: str,
) -> str:
    """Identify an atomic source fact without mutable access metadata."""
    fields = {
        "source_document_id": source_document_id,
        "canonical_fact": canonical_fact,
        "evidence_span": evidence_span,
        "document_version": document_version,
    }
    if any(not _identity_text(value) for value in fields.values()):
        raise ValueError("source fact identity fields must be non-empty")
    return _digest(fields)


def attach_candidate_identities(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Attach stable semantic, variant, and evidence identities to a candidate."""
    options = candidate.get("options")
    correct_index = candidate.get("correct_index")
    if not isinstance(options, list) or not isinstance(correct_index, int):
        raise ValueError("candidate options and answer are required")
    canonical_claim = str(candidate.get("canonical_claim") or "").strip()
    entity = str(candidate.get("knowledge_entity") or "").strip()
    relation = str(candidate.get("knowledge_relation") or "").strip()
    answer_value = str(candidate.get("knowledge_answer_value") or "").strip()
    time_scope = str(candidate.get("knowledge_time_scope") or "timeless").strip()
    evidence_span = str(candidate.get("evidence_summary") or "").strip()
    fact_version = str(candidate.get("fact_version") or "").strip()
    source_document_id = str(candidate.get("source_document_id") or "").strip()
    if not canonical_claim:
        raise ValueError("canonical claim is required")
    canonical_relation, alias_is_inverse = _RELATION_ALIASES.get(
        _identity_text(relation), (_identity_text(relation), False)
    )
    canonical_entity = entity
    canonical_answer = answer_value
    if bool(candidate.get("knowledge_relation_inverse")) or alias_is_inverse:
        canonical_entity, canonical_answer = canonical_answer, canonical_entity
    return {
        **candidate,
        "knowledge_key": knowledge_key(
            subject=str(candidate.get("subject_key") or candidate.get("subject") or ""),
            entity=canonical_entity,
            relation=canonical_relation,
            answer_value=canonical_answer,
            time_scope=time_scope,
        ),
        "canonical_claim": canonical_claim,
        "entity_key": _identity_text(canonical_entity),
        "relation_key": canonical_relation,
        "answer_value": canonical_answer,
        "time_scope": time_scope or "timeless",
        "variant_fingerprint": variant_fingerprint(
            stem=str(candidate.get("question") or candidate.get("question_text") or ""),
            options=options,
            correct_index=correct_index,
            language=str(candidate.get("language") or "bn"),
        ),
        "source_fact_checksum": source_fact_checksum(
            source_document_id=source_document_id,
            canonical_fact=canonical_claim,
            evidence_span=evidence_span,
            document_version=fact_version,
        ),
        "inventory_status": "verified",
        "question_form": str(candidate.get("question_form") or "mcq"),
    }
