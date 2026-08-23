"""Fail CI when a declared direct dependency differs from its deployed lock."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_PINNED_REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s;]+)$")


def _direct_requirements(source: Path, seen: set[Path] | None = None) -> dict[str, str]:
    seen = seen or set()
    source = source.resolve()
    if source in seen:
        raise ValueError(f"recursive requirements include: {source.name}")
    seen.add(source)

    dependencies: dict[str, str] = {}
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r ") or line.startswith("--requirement "):
            include = line.split(maxsplit=1)[1].strip()
            dependencies.update(_direct_requirements(source.parent / include, seen))
            continue
        match = _PINNED_REQUIREMENT.fullmatch(line)
        if not match:
            raise ValueError(f"{source.name}: unsupported requirement {line!r}")
        dependencies[match.group(1).replace("_", "-").casefold()] = match.group(2)
    return dependencies


def _locked_requirements(lockfile: Path) -> dict[str, str]:
    locked: dict[str, str] = {}
    for raw_line in lockfile.read_text(encoding="utf-8").splitlines():
        match = _PINNED_REQUIREMENT.fullmatch(raw_line.strip())
        if match:
            locked[match.group(1).replace("_", "-").casefold()] = match.group(2)
    return locked


def check_pair(source_name: str, lock_name: str, root: Path = ROOT) -> list[str]:
    source = root / source_name
    lockfile = root / lock_name
    declared = _direct_requirements(source)
    locked = _locked_requirements(lockfile)
    return [
        f"{lock_name}: {name} declares {expected}, locks {locked.get(name, 'nothing')}"
        for name, expected in sorted(declared.items())
        if locked.get(name) != expected
    ]


def main() -> int:
    failures = check_pair("requirements.txt", "requirements.lock")
    failures.extend(check_pair("requirements-dev.txt", "requirements-dev.lock"))
    if failures:
        print("Lockfile parity check failed:", *failures, sep="\n- ", file=sys.stderr)
        return 1
    print("lockfile_parity=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
