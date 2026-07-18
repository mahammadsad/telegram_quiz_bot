"""Validate and import manually reviewed source fact bundles into Supabase."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.subjects import get_subject  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="JSON array of source documents")
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Mark every validated row verified; without this flag rows remain drafts.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate bundle structure and source metadata without connecting to Supabase.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = json.loads(args.path.read_text(encoding="utf-8"))
    clean_rows = validate_source_bundle(rows)
    if args.validate_only:
        print(json.dumps({"ok": True, "validated": len(clean_rows), "approved": False}))
        return 0

    from database.client import get_client

    client = get_client()
    imported = []
    for index, clean in enumerate(clean_rows, start=1):
        chapter = _one(
            client.table("quiz_chapters")
            .select("id,subject_key,name")
            .eq("subject_key", clean["subject_key"])
            .eq("name", clean["chapter"])
            .limit(1)
            .execute().data,
            f"Unknown chapter at row {index}",
        )
        micro_topic = _find_or_create_micro_topic(client, chapter, clean, args.dry_run)
        payload = {
            "micro_topic_id": micro_topic["id"],
            "source_url": clean["source_url"],
            "source_title": clean["source_title"],
            "source_domain": clean["source_domain"],
            "source_kind": clean["source_kind"],
            "source_published_at": clean["source_published_at"],
            "source_accessed_at": clean["source_accessed_at"],
            "fact_summary": clean["fact_summary"],
            "fact_version": clean["fact_version"],
            "expires_at": clean["expires_at"],
            "verification_status": "verified" if args.approve else "draft",
            "verification_notes": clean.get("verification_notes") or (
                "Operator approved validated import." if args.approve else "Awaiting operator approval."
            ),
            "review_required": not args.approve,
            "verified_at": datetime.now(timezone.utc).isoformat() if args.approve else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if args.dry_run:
            imported.append({**payload, "micro_topic_key": micro_topic["key"]})
            continue
        result = client.table("source_documents").upsert(
            payload,
            on_conflict="micro_topic_id,source_url,fact_version",
        ).execute()
        imported.append(result.data[0])

    if args.approve and not args.dry_run:
        for subject_key in sorted({str(row["subject_key"]) for row in rows}):
            client.rpc(
                "cache_verified_source_resources",
                {"p_subject_key": subject_key},
            ).execute()

    mode = "validated" if args.dry_run else "imported"
    print(json.dumps({"ok": True, mode: len(imported), "approved": args.approve}))
    return 0


def validate_source_bundle(rows: object) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("Source bundle must be a non-empty JSON array.")
    clean_rows = [validate_source_row(raw, index) for index, raw in enumerate(rows, start=1)]
    identities: set[tuple[str, str, str]] = set()
    for index, clean in enumerate(clean_rows, start=1):
        identity = (
            clean["micro_topic_key"] or clean["micro_topic_name"].strip().lower(),
            clean["source_url"],
            clean["fact_version"],
        )
        if identity in identities:
            raise ValueError(f"Source row {index} duplicates a micro-topic, URL, and fact version.")
        identities.add(identity)
    return clean_rows


def validate_source_row(raw: object, row_number: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"Source row {row_number} must be an object.")
    subject_key = _required(raw, "subject_key", row_number)
    get_subject(subject_key, require_quiz_enabled=True)
    chapter = _required(raw, "chapter", row_number)
    micro_topic_name = _required(raw, "micro_topic_name", row_number)
    source_url = _required(raw, "source_url", row_number)
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"Source row {row_number} must use an HTTPS URL.")
    source_domain = _required(raw, "source_domain", row_number).lower()
    hostname = parsed.hostname.lower()
    if hostname != source_domain and not hostname.endswith(f".{source_domain}"):
        raise ValueError(f"Source row {row_number} domain does not match its URL.")
    source_kind = str(raw.get("source_kind") or "official").strip().lower()
    if source_kind not in {"official", "primary", "secondary"}:
        raise ValueError(f"Source row {row_number} has an invalid source_kind.")
    published_at = _optional_datetime(raw.get("source_published_at"), "source_published_at", row_number)
    if subject_key == "current-affairs" and not published_at:
        raise ValueError(f"Current-affairs source row {row_number} requires source_published_at.")
    if subject_key == "current-affairs" and source_kind == "secondary":
        raise ValueError(f"Current-affairs source row {row_number} must be official or primary.")
    accessed_at = _optional_datetime(raw.get("source_accessed_at"), "source_accessed_at", row_number)
    accessed_at = accessed_at or datetime.now(timezone.utc).isoformat()
    expires_at = _optional_datetime(raw.get("expires_at"), "expires_at", row_number)
    if expires_at and datetime.fromisoformat(expires_at) <= datetime.fromisoformat(accessed_at):
        raise ValueError(f"Source row {row_number} expires_at must follow source_accessed_at.")
    fact_summary = _required(raw, "fact_summary", row_number)
    if len(fact_summary) < 40:
        raise ValueError(f"Source row {row_number} fact_summary is too short.")
    return {
        "subject_key": subject_key,
        "chapter": chapter,
        "micro_topic_name": micro_topic_name,
        "micro_topic_key": str(raw.get("micro_topic_key") or "").strip().lower(),
        "source_url": source_url,
        "source_title": _required(raw, "source_title", row_number),
        "source_domain": source_domain,
        "source_kind": source_kind,
        "source_published_at": published_at,
        "source_accessed_at": accessed_at,
        "fact_summary": fact_summary,
        "fact_version": str(raw.get("fact_version") or date.today().isoformat()).strip(),
        "expires_at": expires_at,
        "verification_notes": str(raw.get("verification_notes") or "").strip(),
    }


def _find_or_create_micro_topic(client, chapter: dict, clean: dict, dry_run: bool) -> dict:
    query = client.table("quiz_micro_topics").select("id,key,name").eq("chapter_id", chapter["id"])
    if clean["micro_topic_key"]:
        query = query.eq("key", clean["micro_topic_key"])
    else:
        query = query.eq("name", clean["micro_topic_name"])
    rows = query.limit(1).execute().data or []
    if rows:
        return rows[0]
    digest = hashlib.sha256(
        f"{clean['subject_key']}:{clean['chapter']}:{clean['micro_topic_name']}".encode("utf-8")
    ).hexdigest()[:16]
    key = clean["micro_topic_key"] or f"{clean['subject_key']}:{digest}"
    payload = {
        "chapter_id": chapter["id"],
        "key": key,
        "name": clean["micro_topic_name"],
        "normalized_name": clean["micro_topic_name"].strip().lower(),
        "target_coverage": 10,
        "mastery_relevance": 1.0,
    }
    if dry_run:
        return {"id": "00000000-0000-0000-0000-000000000000", **payload}
    return client.table("quiz_micro_topics").insert(payload).execute().data[0]


def _one(rows: list[dict] | None, message: str) -> dict:
    if not rows:
        raise ValueError(message)
    return rows[0]


def _required(raw: dict, field: str, row_number: int) -> str:
    value = str(raw.get(field) or "").strip()
    if not value:
        raise ValueError(f"Source row {row_number} requires {field}.")
    return value


def _optional_datetime(value: object, field: str, row_number: int) -> str | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError as exc:
        raise ValueError(f"Source row {row_number} has invalid {field}.") from exc


if __name__ == "__main__":
    raise SystemExit(main())
