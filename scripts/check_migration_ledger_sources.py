"""Verify recovered production migration sources against pinned ledger hashes."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.migration_ledger import PRODUCTION_LEDGER_SOURCE_MD5  # noqa: E402

MIGRATIONS = ROOT / "supabase" / "migrations"
MIGRATION_REFERENCE = re.compile(r"\b\d{14}_[a-z0-9_]+\.sql\b")
REFERENCE_SUFFIXES = {".json", ".md", ".py", ".sh", ".toml", ".yaml", ".yml"}
EXCLUDED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
}


def missing_references() -> list[str]:
    """Reject stale physical migration filenames outside immutable SQL sources."""

    available = {path.name for path in MIGRATIONS.glob("*.sql")}
    problems: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in REFERENCE_SUFFIXES:
            continue
        if path.parent == MIGRATIONS:
            continue
        if any(part in EXCLUDED_DIRECTORIES for part in path.relative_to(ROOT).parts):
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for reference in MIGRATION_REFERENCE.findall(line):
                if reference not in available:
                    relative = path.relative_to(ROOT)
                    problems.append(f"missing_reference:{relative}:{line_number}:{reference}")
    return problems


def failures() -> list[str]:
    problems: list[str] = []
    for name, (version, expected_md5) in PRODUCTION_LEDGER_SOURCE_MD5.items():
        path = MIGRATIONS / f"{version}_{name}.sql"
        if not path.is_file():
            problems.append(f"missing:{path.name}")
            continue
        observed = hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324
        if observed != expected_md5:
            problems.append(f"source_mismatch:{path.name}")
    problems.extend(missing_references())
    return problems


def main() -> int:
    problems = failures()
    if problems:
        for problem in problems:
            print(problem)
        return 1
    print(f"production_migration_sources=verified count={len(PRODUCTION_LEDGER_SOURCE_MD5)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
