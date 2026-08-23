from pathlib import Path

from scripts import check_lockfile_parity


def test_repository_lockfiles_match_declared_direct_dependencies() -> None:
    assert check_lockfile_parity.check_pair("requirements.txt", "requirements.lock") == []
    assert check_lockfile_parity.check_pair("requirements-dev.txt", "requirements-dev.lock") == []


def test_parity_reports_a_changed_direct_dependency(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("demo-package==2.0.0\n", encoding="utf-8")
    (tmp_path / "requirements.lock").write_text("demo-package==1.0.0\n", encoding="utf-8")

    assert check_lockfile_parity.check_pair("requirements.txt", "requirements.lock", tmp_path) == [
        "requirements.lock: demo-package declares 2.0.0, locks 1.0.0"
    ]
