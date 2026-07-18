"""Fail CI if public quiz/frontend assets contain answers or server secrets."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_QUIZ_KEYS = {
    "a",
    "correct_index",
    "correct_option",
    "e",
    "explanation",
    "detailed_explanation",
}
FORBIDDEN_PUBLIC_TOKENS = {
    "SUPABASE_SERVICE_KEY",
    "GEMINI_API_KEY_PRIMARY",
    "GEMINI_API_KEY_SECONDARY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_FORUM_TOPICS_JSON",
}
SECRET_ASSIGNMENT = re.compile(
    r"(?im)^[\t ]*(GEMINI_API_KEY(?:_PRIMARY|_SECONDARY)?|SUPABASE_SERVICE_KEY|TELEGRAM_BOT_TOKEN)"
    r"[\t ]*=[\t ]*([^\s#]+)"
)
SECRET_SHAPES = {
    "Gemini API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "Telegram bot token": re.compile(r"\b\d{6,12}:[0-9A-Za-z_-]{30,}\b"),
    "JWT-like credential": re.compile(r"\beyJ[0-9A-Za-z_-]{20,}\.[0-9A-Za-z_-]{20,}\.[0-9A-Za-z_-]{20,}\b"),
}
TEXT_SUFFIXES = {".py", ".html", ".md", ".yml", ".yaml", ".toml", ".txt", ".json", ".sql", ".example"}


def main() -> None:
    failures: list[str] = []
    for path in sorted((ROOT / "quizzes").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        questions = payload.get("qs")
        if not isinstance(questions, list) or len(questions) != 10:
            failures.append(f"{path.name}: expected exactly 10 public questions")
            continue
        for index, question in enumerate(questions, start=1):
            leaked = FORBIDDEN_QUIZ_KEYS.intersection(question)
            if leaked:
                failures.append(f"{path.name} question {index}: forbidden keys {sorted(leaked)}")

    for filename in ("index.html", "dashboard.html"):
        text = (ROOT / filename).read_text(encoding="utf-8")
        for token in FORBIDDEN_PUBLIC_TOKENS:
            if token in text:
                failures.append(f"{filename}: contains private configuration name {token}")

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or any(part in {".git", ".venv", "__pycache__"} for part in path.parts):
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name != "Procfile":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        relative = path.relative_to(ROOT)
        if path.name.startswith(".env"):
            for match in SECRET_ASSIGNMENT.finditer(text):
                value = match.group(2).strip("'\"")
                if value and not value.startswith(("${{", "<")):
                    failures.append(f"{relative}: non-empty {match.group(1)} assignment")
        for label, pattern in SECRET_SHAPES.items():
            if pattern.search(text):
                failures.append(f"{relative}: contains a credential shaped like {label}")

    if failures:
        raise SystemExit("\n".join(failures))
    print("Public-data check passed: no answer keys or server secret names found.")


if __name__ == "__main__":
    main()
