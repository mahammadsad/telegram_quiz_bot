"""Read-only grounding check for the exact approved source rollout."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.source_rollout import (  # noqa: E402
    DYNAMIC_SOURCE_SUBJECTS,
    ROTATION_CHAPTER_KEYS,
)
from config.syllabus import SYLLABUS  # noqa: E402
from services import source_grounding  # noqa: E402
from utils.local_time import local_today  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        choices=("static", "all"),
        default="all",
    )
    args = parser.parse_args()
    result = check_source_readiness(
        target_date=local_today(),
        scope=args.scope,
    )
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


def check_source_readiness(
    *,
    target_date: date,
    scope: str,
    loader=source_grounding.load_grounding_bundle,
) -> dict[str, int | str]:
    if scope not in {"static", "all"}:
        raise ValueError("Source-readiness scope must be static or all.")

    checked = 0
    documents = 0
    missing: list[str] = []
    for subject_key, chapter_keys in ROTATION_CHAPTER_KEYS.items():
        if scope == "static" and subject_key in DYNAMIC_SOURCE_SUBJECTS:
            continue
        chapter_by_key = {
            chapter.key: chapter for chapter in SYLLABUS[subject_key]
        }
        for chapter_key in chapter_keys:
            chapter = chapter_by_key[chapter_key]
            try:
                bundle = loader(subject_key, chapter.name, target_date)
            except Exception:
                missing.append(chapter_key)
                continue
            checked += 1
            documents += len(bundle.documents)

    if missing:
        raise RuntimeError(
            "Verified source coverage is not ready for approved chapters: "
            + ", ".join(sorted(missing))
        )
    return {
        "scope": scope,
        "chapters": checked,
        "documents": documents,
    }


if __name__ == "__main__":
    raise SystemExit(main())
