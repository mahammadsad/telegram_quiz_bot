"""
Text normalization + hashing for duplicate detection.

Three-layer duplicate detection strategy (per project spec):
    1. question_hash   -> exact-duplicate lookup (unique DB constraint, O(1))
    2. normalized_text -> cheap textual comparison / debugging
    3. similarity       -> fuzzy near-duplicate search via Postgres pg_trgm
                            (see database/schema.sql: find_similar_questions)

Layers 1-2 are computed here in Python. Layer 3 is delegated to Postgres
because trigram similarity search over a growing question bank does not
scale if done client-side in Python.
"""

from __future__ import annotations

import hashlib
import re

# Collapse any run of whitespace to a single space.
_WHITESPACE_RE = re.compile(r"\s+")

# Strip common punctuation, including the Bengali daŗi/danda "।" and other
# Bengali-context punctuation, so that trivial punctuation differences don't
# defeat exact-duplicate detection.
_PUNCT_RE = re.compile(r"[।,.!?\"'‘’“”:;()\[\]{}—–\-]+")


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, and collapse whitespace.

    This is intentionally aggressive: it's used purely for duplicate
    detection, never for display. Two questions that are identical except
    for punctuation or casing should normalize to the same string.
    """
    text = (text or "").strip().lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def question_hash(question_text: str) -> str:
    """SHA-256 hex digest of the normalized question text.

    Used as a unique DB constraint (questions.question_hash) to reject
    exact/near-exact duplicates in O(1) at insert time.
    """
    normalized = normalize_text(question_text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
