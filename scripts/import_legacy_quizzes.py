"""Import old quizzes/*.json packs into the shared Supabase schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import require_env  # noqa: E402
from services import quiz_pack_service  # noqa: E402
from utils.quiz_ids import parse_quiz_id  # noqa: E402

QUIZZES_DIR = ROOT / "quizzes"


def main() -> None:
    require_env("SUPABASE_URL")
    require_env("SUPABASE_SERVICE_KEY")

    if not QUIZZES_DIR.exists():
        print("No quizzes/ directory found.")
        return

    imported = 0
    for path in sorted(QUIZZES_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        quiz_id = (payload.get("meta") or {}).get("quiz_id") or path.stem
        meta = payload.get("meta") or {"quiz_id": quiz_id}
        questions = payload.get("qs") or []
        if not questions:
            print(f"Skipped {path.name}: no questions.")
            continue
        try:
            _, id_subject_key = parse_quiz_id(quiz_id)
        except ValueError:
            id_subject_key = None
        subject_key = meta.get("subject_key") or id_subject_key
        if not subject_key:
            print(f"Skipped {path.name}: add an explicit canonical meta.subject_key; display names are not used for routing/classification.")
            continue
        if any("a" not in item and "correct_index" not in item for item in questions):
            print(f"Skipped {path.name}: public fallback intentionally contains no server-side answer key.")
            continue
        chapter = str(meta.get("chapter") or "").strip()
        normalized = []
        for item in questions:
            explanation = item.get("explanation") or item.get("e") or ""
            normalized.append({
                "question": item.get("question") or item.get("q"),
                "options": item.get("options") or item.get("o"),
                "correct_index": item.get("correct_index", item.get("a")),
                "explanation": explanation,
                "detailed_explanation": item.get("detailed_explanation") or explanation,
                "difficulty": item.get("difficulty") or "medium",
                "subject_key": subject_key,
                "chapter": chapter,
            })
        quiz_pack_service.record_quiz_pack(quiz_id, normalized, {**meta, "subject_key": subject_key}, chat_id=0)
        imported += 1
        print(f"Imported {path.name} as quiz pack {quiz_id}.")

    print(f"Done. Imported {imported} quiz pack(s).")


if __name__ == "__main__":
    main()
