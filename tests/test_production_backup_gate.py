from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from scripts.check_production_backup import NoRedirects, has_recent_completed_backup, main

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


@pytest.mark.parametrize("timestamp", ["2026-09-13T00:00:00Z", "2026-09-11T00:00:00+00:00"])
def test_completed_recent_backup(timestamp):
    assert has_recent_completed_backup(
        {"backups": [{"status": "COMPLETED", "inserted_at": timestamp}]}, NOW
    )


@pytest.mark.parametrize("payload", [
    None, [], {}, {"backups": None}, {"pitr_enabled": True, "backups": []},
    {"backups": [None]},
    {"backups": [{"status": "FAILED", "inserted_at": "2026-09-12T00:00:00Z"}]},
    *({"backups": [{"status": "COMPLETED", "inserted_at": timestamp}]}
      for timestamp in [None, "invalid", "2026-09-12", "2026-09-14T00:00:00Z",
                        "2026-09-10T23:59:59Z"]),
])
def test_missing_stale_malformed_or_future_backup_fails_closed(payload):
    assert not has_recent_completed_backup(payload, NOW)


def test_identity_guard_runs_before_network():
    with patch.dict("os.environ", {}, clear=True), patch(
        "scripts.check_production_backup.build_opener"
    ) as opener:
        assert main() == 1
        opener.assert_not_called()


def test_missing_credential_stops_before_network():
    with patch.dict("os.environ", {"EXPECTED_SUPABASE_PROJECT_REF": "tizxodkcpglmxgtwepor"}, clear=True), patch(
        "scripts.check_production_backup.build_opener"
    ) as opener:
        assert main() == 1
        opener.assert_not_called()


@pytest.mark.parametrize("body,expected", [(b'{"backups": []}', 1), (b'not json', 1)])
def test_invalid_provider_response_blocks_migration(body, expected):
    with patch.dict("os.environ", {
        "EXPECTED_SUPABASE_PROJECT_REF": "tizxodkcpglmxgtwepor",
        "SUPABASE_ACCESS_TOKEN": "test-secret-never-log",
    }, clear=True), patch("scripts.check_production_backup.build_opener") as opener:
        opener.return_value.open.return_value = BytesIO(body)
        assert main() == expected
        request = opener.return_value.open.call_args.args[0]
        assert request.get_method() == "GET"
        assert request.full_url == "https://api.supabase.com/v1/projects/tizxodkcpglmxgtwepor/database/backups"


def test_provider_error_does_not_echo_body_or_credentials(capsys):
    with patch.dict("os.environ", {
        "EXPECTED_SUPABASE_PROJECT_REF": "tizxodkcpglmxgtwepor",
        "SUPABASE_ACCESS_TOKEN": "test-secret-never-log",
    }, clear=True), patch("scripts.check_production_backup.build_opener") as opener:
        opener.return_value.open.side_effect = HTTPError(
            "https://api.supabase.com", 403, "private-provider-message", {}, None
        )
        assert main() == 1
    output = capsys.readouterr().out
    assert "test-secret" not in output
    assert "private-provider" not in output


def test_redirects_cannot_forward_management_credential():
    assert NoRedirects().redirect_request(None, None, 302, "", {}, "https://example.com") is None


def test_backup_gate_precedes_apply():
    from pathlib import Path

    workflow = Path(".github/workflows/supabase-migrations.yml").read_text()
    assert workflow.index("python scripts/check_production_backup.py") < workflow.index(
        "- name: Apply tracked migrations"
    )
