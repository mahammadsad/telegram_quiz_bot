from __future__ import annotations

import json
from pathlib import Path

from scripts import check_public_data


def _minimum_frontend(root: Path) -> None:
    for filename in ("index.html", "dashboard.html", "practice.html"):
        (root / filename).write_text("<!doctype html><title>safe</title>", encoding="utf-8")


def _scan_fixture(tmp_path: Path, filename: str, text: str) -> list[str]:
    _minimum_frontend(tmp_path)
    (tmp_path / "quizzes").mkdir(exist_ok=True)
    (tmp_path / filename).write_text(text, encoding="utf-8")
    return check_public_data.scan(tmp_path)


def test_detects_each_supported_credential_shape_without_real_credentials(tmp_path: Path) -> None:
    fake_shapes = "\n".join(
        (
            "AQ" + "." + "A" * 36,
            "AI" + "za" + "B" * 36,
            "123456789:" + "C" * 35,
            "eyJ" + "D" * 20 + "." + "E" * 20 + "." + "F" * 20,
            "sb_" + "secret_" + "G" * 28,
        )
    )

    failures = _scan_fixture(tmp_path, "fixture.txt", fake_shapes)

    labels = "\n".join(failures)
    assert "modern Google/Gemini credential" in labels
    assert "traditional Google API key" in labels
    assert "Telegram bot token" in labels
    assert "JWT-like credential" in labels
    assert "Supabase secret key" in labels


def test_detects_publishable_key_in_server_secret_assignment(tmp_path: Path) -> None:
    value = "sb_" + "publishable_" + "P" * 28

    failures = _scan_fixture(
        tmp_path,
        "settings.py",
        f'SUPABASE_SERVICE_KEY = "{value}"\n',
    )

    assert any("publishable credential assigned to server-secret field" in item for item in failures)


def test_detects_non_empty_secret_assignments_in_supported_text_formats(tmp_path: Path) -> None:
    _minimum_frontend(tmp_path)
    (tmp_path / "quizzes").mkdir()
    fixtures = {
        ".env": "APP_TOKEN=value-one\n",
        "config.yml": "service_password: value-two\n",
        "config.json": '"private_key": "value-three"\n',
        "config.toml": 'api_key = "value-four"\n',
        "settings.py": 'DATABASE_PASSWORD = "value-five"\n',
        "entrypoint.sh": "export ACCESS_TOKEN=value-six\n",
        "guide.md": "SERVICE_SECRET=value-seven\n",
        "notes.txt": "BOT_TOKEN=value-eight\n",
    }
    for filename, text in fixtures.items():
        (tmp_path / filename).write_text(text, encoding="utf-8")

    failures = check_public_data.scan(tmp_path)

    for filename in fixtures:
        assert any(filename in item and "non-empty server-secret assignment" in item for item in failures)


def test_allows_empty_names_environment_references_and_documented_placeholders(
    tmp_path: Path,
) -> None:
    token_name = "TELEGRAM_BOT_" + "TOKEN"
    another_name = "ANOTHER_" + "TOKEN"
    safe = "\n".join(
        (
            f"{token_name}=",
            'SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")',
            "GEMINI_API_KEY_PRIMARY=${{ secrets.GEMINI_API_KEY_PRIMARY }}",
            "DATABASE_PASSWORD=<secret>",
            f"{another_name}=replace-me",
        )
    )

    assert _scan_fixture(tmp_path, ".env.example", safe) == []


def test_recursively_detects_nested_answer_fields(tmp_path: Path) -> None:
    _minimum_frontend(tmp_path)
    quizzes = tmp_path / "quizzes"
    quizzes.mkdir()
    questions = [{"q": f"Question {index}", "o": ["A", "B", "C", "D"]} for index in range(10)]
    questions[4]["metadata"] = {"review": [{"correct_answer": 2}]}
    (quizzes / "quiz.json").write_text(
        json.dumps({"meta": {}, "qs": questions}),
        encoding="utf-8",
    )

    failures = check_public_data.scan(tmp_path)

    assert any("$.qs[4].metadata.review[0].correct_answer" in item for item in failures)


def test_scans_practice_frontend_for_private_server_names(tmp_path: Path) -> None:
    _minimum_frontend(tmp_path)
    (tmp_path / "quizzes").mkdir()
    private_name = "TELEGRAM_" + "BOT_TOKEN"
    (tmp_path / "practice.html").write_text(private_name, encoding="utf-8")

    failures = check_public_data.scan(tmp_path)

    assert any("practice.html: contains private server configuration name" in item for item in failures)
