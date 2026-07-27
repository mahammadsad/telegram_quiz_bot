"""Shared fail-closed checks for operator-supplied source metadata."""

from __future__ import annotations

from urllib.parse import urlparse

_PLACEHOLDER_HOST_LABELS = {"example", "invalid", "localhost", "placeholder", "test"}
_PLACEHOLDER_TITLE_MARKERS = ("synthetic", "placeholder")


def is_placeholder_source(source_url: str, source_title: str) -> bool:
    """Return true when source metadata is clearly synthetic or documentation-only."""

    try:
        hostname = (urlparse(source_url).hostname or "").strip().lower().rstrip(".")
    except ValueError:
        return True
    labels = hostname.split(".") if hostname else []
    title = source_title.strip().lower()
    return (
        not hostname
        or bool(labels and labels[0] in _PLACEHOLDER_HOST_LABELS)
        or any(marker in title for marker in _PLACEHOLDER_TITLE_MARKERS)
    )
