"""Fail closed when public assets or repository text expose answers or credentials."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_QUIZ_KEYS = {
    "a",
    "answer",
    "answer_index",
    "correct_answer",
    "correct_index",
    "correct_option",
    "detailed_explanation",
    "e",
    "explanation",
}
FORBIDDEN_FRONTEND_NAMES = {
    "DATABASE_PASSWORD",
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_PRIMARY",
    "GEMINI_API_KEY_SECONDARY",
    "SUPABASE_SERVICE_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_FORUM_TOPICS_JSON",
}
CREDENTIAL_SHAPES = {
    "modern Google/Gemini credential": re.compile(r"(?<![0-9A-Za-z_-])AQ\.[0-9A-Za-z_-]{30,}"),
    "traditional Google API key": re.compile(r"(?<![0-9A-Za-z_-])AIza[0-9A-Za-z_-]{30,}"),
    "Telegram bot token": re.compile(r"(?<!\d)\d{6,12}:[0-9A-Za-z_-]{30,}"),
    "JWT-like credential": re.compile(
        r"(?<![0-9A-Za-z_-])eyJ[0-9A-Za-z_-]{15,}\.[0-9A-Za-z_-]{15,}\.[0-9A-Za-z_-]{15,}"
    ),
    "Supabase secret key": re.compile(r"(?<![0-9A-Za-z_-])sb_secret_[0-9A-Za-z_-]{20,}"),
}
PUBLISHABLE_SHAPE = re.compile(r"(?<![0-9A-Za-z_-])sb_publishable_[0-9A-Za-z_-]{20,}")
ASSIGNMENT_LINE = re.compile(
    r"""(?im)^[ \t]*(?:export[ \t]+)?["']?([A-Za-z_][A-Za-z0-9_.-]*)["']?"""
    r"""[ \t]*(=|:)[ \t]*(.*?)[ \t]*$"""
)
TEXT_SUFFIXES = {
    ".env",
    ".example",
    ".html",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".sql",
    ".text",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_PARTS = {
    ".git",
    ".mypy_cache",
    ".npm-cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "playwright-report",
    "test-results",
}
PLACEHOLDER_WORDS = {
    "...",
    "changeme",
    "example",
    "none",
    "null",
    "placeholder",
    "redacted",
    "replace-me",
    "replace_me",
    "secret",
    "test-only",
    "your-value",
}


def _public_json_paths(root: Path) -> list[Path]:
    paths = list((root / "quizzes").glob("**/*.json"))
    public_dir = root / "public"
    if public_dir.exists():
        paths.extend(public_dir.glob("**/*.json"))
    return sorted(set(paths))


def _walk_forbidden_keys(value: Any, location: str = "$") -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_location = f"{location}.{key_text}"
            if key_text.casefold() in FORBIDDEN_QUIZ_KEYS:
                yield child_location
            yield from _walk_forbidden_keys(child, child_location)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_forbidden_keys(child, f"{location}[{index}]")


def _is_text_path(path: Path) -> bool:
    return (
        path.name == "Procfile"
        or path.name.startswith(".env")
        or path.suffix.casefold() in TEXT_SUFFIXES
    )


def _iter_text_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if _is_text_path(path):
            yield path


def _credential_shape_failures(text: str, label: str) -> list[str]:
    failures = [
        f"{label}: contains a credential shaped like {shape_name}"
        for shape_name, pattern in CREDENTIAL_SHAPES.items()
        if pattern.search(text)
    ]
    return failures


def _is_server_secret_name(name: str) -> bool:
    normalized = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    exact = {
        "API_KEY",
        "DATABASE_URL",
        "PASSWORD",
        "PRIVATE_KEY",
        "SECRET",
        "SERVICE_KEY",
        "TOKEN",
    }
    suffixes = (
        "_API_KEY",
        "_DATABASE_URL",
        "_PASSWORD",
        "_PRIVATE_KEY",
        "_SECRET",
        "_SERVICE_KEY",
        "_TOKEN",
    )
    return normalized in exact or normalized.endswith(suffixes)


def _clean_assignment_value(value: str) -> str:
    cleaned = value.strip().rstrip(",;").strip()
    if cleaned.startswith(("'", '"')) and cleaned.endswith(cleaned[:1]) and len(cleaned) >= 2:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _is_safe_reference_or_placeholder(value: str) -> bool:
    cleaned = _clean_assignment_value(value)
    lower = cleaned.casefold()
    if PUBLISHABLE_SHAPE.search(cleaned):
        return False
    if any(pattern.search(cleaned) for pattern in CREDENTIAL_SHAPES.values()):
        return False
    if not cleaned or lower in PLACEHOLDER_WORDS:
        return True
    if cleaned.startswith(("<", "$", "{{", "${{")):
        return True
    if lower.startswith(("env(", "getenv(", "os.environ", "os.getenv")):
        return True
    if "os.environ" in lower or "os.getenv" in lower:
        return True
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*,?", cleaned):
        return True
    if any(marker in cleaned for marker in ("(", ")", " + ", " if ", " else ")):
        return True
    if re.fullmatch(r"\*{3,}", cleaned):
        return True
    return bool(
        re.fullmatch(
            r"(?:your|replace|example|test|dummy)[-_][A-Za-z0-9_.{}$-]+",
            cleaned,
            flags=re.IGNORECASE,
        )
    )


def _is_disposable_local_database(name: str, value: str, relative: Path) -> bool:
    cleaned = _clean_assignment_value(value)
    normalized = name.upper()
    if normalized == "POSTGRES_PASSWORD" and cleaned == "postgres":
        return relative.as_posix() == ".github/workflows/ci.yml"
    if normalized.endswith("DATABASE_URL"):
        return bool(
            re.fullmatch(
                r"postgres(?:ql)?://postgres:postgres@(?:localhost|127\.0\.0\.1):\d+/[A-Za-z0-9_-]+",
                cleaned,
            )
        )
    return False


def _assignment_failures(text: str, relative: Path) -> list[str]:
    failures: list[str] = []
    for match in ASSIGNMENT_LINE.finditer(text):
        name, delimiter, value = match.groups()
        if delimiter == ":" and relative.suffix.casefold() in {".py", ".sh"}:
            continue
        if not _is_server_secret_name(name):
            continue
        if _is_safe_reference_or_placeholder(value):
            continue
        if _is_disposable_local_database(name, value, relative):
            continue
        failures.append(f"{relative}: non-empty server-secret assignment for {name}")

        if PUBLISHABLE_SHAPE.search(value):
            failures.append(
                f"{relative}: Supabase publishable credential assigned to server-secret field {name}"
            )
    return failures


def _current_tree_failures(root: Path) -> list[str]:
    failures: list[str] = []
    for path in _public_json_paths(root):
        relative = path.relative_to(root)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"{relative}: invalid public JSON ({type(exc).__name__})")
            continue
        if path.parts[-2] == "quizzes":
            questions = payload.get("qs") if isinstance(payload, dict) else None
            if not isinstance(questions, list) or len(questions) != 10:
                failures.append(f"{relative}: expected exactly 10 public questions")
        for location in _walk_forbidden_keys(payload):
            failures.append(f"{relative}: answer-bearing field at {location}")

    for filename in ("index.html", "dashboard.html", "practice.html"):
        path = root / filename
        if not path.exists():
            failures.append(f"{filename}: required frontend file is missing")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name in sorted(FORBIDDEN_FRONTEND_NAMES):
            if name in text:
                failures.append(f"{filename}: contains private server configuration name {name}")

    for path in _iter_text_files(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        relative = path.relative_to(root)
        failures.extend(_credential_shape_failures(text, str(relative)))
        failures.extend(_assignment_failures(text, relative))
    return failures


def _history_failures(root: Path) -> list[str]:
    """Scan committed text blobs for high-confidence credential shapes only."""
    result = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    failures: list[str] = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        object_id, separator, object_path = line.partition(" ")
        if not separator or object_id in seen:
            continue
        seen.add(object_id)
        path = Path(object_path)
        if not _is_text_path(path) or any(part in SKIP_PARTS for part in path.parts):
            continue
        blob = subprocess.run(
            ["git", "cat-file", "-p", object_id],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if blob.returncode != 0 or len(blob.stdout) > 2_000_000 or b"\0" in blob.stdout:
            continue
        text = blob.stdout.decode("utf-8", errors="ignore")
        failures.extend(
            _credential_shape_failures(text, f"history:{object_id[:12]}:{object_path}")
        )
    return failures


def scan(root: Path = ROOT, *, include_history: bool = False) -> list[str]:
    failures = _current_tree_failures(root)
    if include_history:
        failures.extend(_history_failures(root))
    return sorted(set(failures))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history",
        action="store_true",
        help="also scan every committed text blob for high-confidence credential shapes",
    )
    args = parser.parse_args()
    failures = scan(include_history=args.history)
    if failures:
        raise SystemExit("\n".join(failures))
    scope = "current tree and Git history" if args.history else "current tree"
    print(f"Public-data check passed for {scope}: no answer fields or credentials found.")


if __name__ == "__main__":
    main()
