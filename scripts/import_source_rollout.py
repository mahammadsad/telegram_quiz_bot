"""Validate or import only the approved static source-backed rotation rows."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.source_rollout import (  # noqa: E402
    DYNAMIC_SOURCE_SUBJECTS,
    ROTATION_CHAPTER_KEYS,
    STATIC_SOURCE_BUNDLES,
)
from config.syllabus import SYLLABUS  # noqa: E402
from scripts.import_source_documents import (  # noqa: E402
    import_source_bundle,
    validate_source_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument(
        "--approve",
        action="store_true",
        help="Import the reviewed selected rows as verified source documents.",
    )
    args = parser.parse_args()

    rows, coverage = load_static_rollout_rows()
    if args.validate_only:
        imported_count = 0
    else:
        imported_count = len(import_source_bundle(
            rows,
            approve=args.approve,
            dry_run=args.dry_run,
        ))
    print(json.dumps({
        "ok": True,
        "validated": len(rows),
        "chapters": len(coverage),
        "imported": imported_count,
        "approved": args.approve,
        "dryRun": args.dry_run,
    }, sort_keys=True))
    return 0


def load_static_rollout_rows(
    *,
    root: Path = ROOT,
) -> tuple[list[dict], dict[str, int]]:
    """Return only selected static rows after an exact catalogue coverage gate."""
    selected_topics: dict[str, set[str]] = {}
    chapter_name_to_key: dict[tuple[str, str], str] = {}
    for subject_key, chapters in SYLLABUS.items():
        if subject_key in DYNAMIC_SOURCE_SUBJECTS:
            continue
        approved = set(ROTATION_CHAPTER_KEYS[subject_key])
        for chapter in chapters:
            if chapter.key not in approved:
                continue
            chapter_name_to_key[(subject_key, chapter.name)] = chapter.key
            selected_topics[chapter.key] = {
                topic.key for topic in chapter.micro_topics
            }

    selected: list[dict] = []
    for relative_path in STATIC_SOURCE_BUNDLES:
        path = root / relative_path
        raw = json.loads(path.read_text(encoding="utf-8"))
        clean = validate_source_bundle(raw)
        for row in clean:
            chapter_key = chapter_name_to_key.get((
                str(row["subject_key"]),
                str(row["chapter"]),
            ))
            if chapter_key:
                selected.append(row)

    selected = validate_source_bundle(selected)
    covered_topics: dict[str, set[str]] = {
        chapter_key: set() for chapter_key in selected_topics
    }
    counts: Counter[str] = Counter()
    for row in selected:
        chapter_key = chapter_name_to_key[(
            str(row["subject_key"]),
            str(row["chapter"]),
        )]
        counts[chapter_key] += 1
        covered_topics[chapter_key].add(str(row["micro_topic_key"]))

    missing_chapters = sorted(
        chapter_key for chapter_key in selected_topics
        if not counts[chapter_key]
    )
    missing_topics = sorted(
        topic_key
        for chapter_key, expected in selected_topics.items()
        if not chapter_key.startswith("computer:")
        for topic_key in expected - covered_topics[chapter_key]
    )
    unexpected_topics = sorted(
        topic_key
        for chapter_key, actual in covered_topics.items()
        if not chapter_key.startswith("computer:")
        for topic_key in actual - selected_topics[chapter_key]
    )
    if missing_chapters or missing_topics or unexpected_topics:
        raise ValueError(
            "Static rollout source coverage is incomplete or outside the "
            f"approved catalogue: missing_chapters={missing_chapters}, "
            f"missing_topics={missing_topics}, "
            f"unexpected_topics={unexpected_topics}"
        )
    return selected, dict(sorted(counts.items()))


if __name__ == "__main__":
    raise SystemExit(main())
