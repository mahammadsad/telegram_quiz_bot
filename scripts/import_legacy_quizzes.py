"""Import old quizzes/*.json packs into the shared Supabase schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import require_env  # noqa: E402
from services import quiz_pack_service  # noqa: E402

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
        quiz_pack_service.record_quiz_pack(quiz_id, questions, meta, chat_id=0)
        imported += 1
        print(f"Imported {path.name} as quiz pack {quiz_id}.")

    print(f"Done. Imported {imported} quiz pack(s).")


if __name__ == "__main__":
    main()
