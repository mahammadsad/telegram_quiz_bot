from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from scripts.check_production_backup import (
    NoRedirects,
    backup_summary,
    has_recent_completed_backup,
    has_recent_pitr_window,
    main,
)

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


@pytest.mark.parametrize("timestamp", ["2026-09-13T00:00:00Z", "2026-09-11T00:00:00+00:00"])
def test_completed_recent_backup(timestamp):
    assert has_recent_completed_backup(
        {"backups": [{"status": "COMPLETED", "inserted_at": timestamp}]}, NOW
    )


def test_pitr_window_is_recovery_evidence_even_without_daily_backup_rows():
    import scripts.check_production_backup as gate

    payload = {"backups": [], "walg_enabled": True, "pitr_enabled": True,
               "physical_backup_data": {
                   "earliest_physical_backup_date_unix": int(NOW.timestamp()) - 7 * 86400,
                   "latest_physical_backup_date_unix": int(NOW.timestamp()) - 120,
               }}
    with patch.dict("os.environ", {
        "EXPECTED_SUPABASE_PROJECT_REF": "tizxodkcpglmxgtwepor",
        "SUPABASE_ACCESS_TOKEN": "test-secret-never-log",
    }, clear=True), patch.object(gate, "build_opener") as opener, patch.object(gate, "datetime") as clock:
        import json

        opener.return_value.open.return_value = BytesIO(json.dumps(payload).encode())
        clock.now.return_value = NOW
        assert main() == 0


@pytest.mark.parametrize("earliest,latest", [
    (0, int(NOW.timestamp())), (True, int(NOW.timestamp())),
    (int(NOW.timestamp()), False), (None, int(NOW.timestamp())),
    ("1", int(NOW.timestamp())), (1, str(int(NOW.timestamp()))),
    (1, float(NOW.timestamp())), (1, int(NOW.timestamp()) + 1),
    (int(NOW.timestamp()), int(NOW.timestamp()) - 1),
    (1, int(NOW.timestamp()) - 48 * 3600 - 1),
    (1, 10 ** 100),
])
def test_invalid_or_stale_pitr_window_fails_closed(earliest, latest):
    payload = {"pitr_enabled": True, "walg_enabled": True, "physical_backup_data": {
        "earliest_physical_backup_date_unix": earliest,
        "latest_physical_backup_date_unix": latest,
    }}
    assert not has_recent_pitr_window(payload, NOW)


@pytest.mark.parametrize("pitr,walg", [(False, True), (True, False), ("true", True), (True, 1)])
def test_window_alone_or_truthy_non_boolean_flags_are_insufficient(pitr, walg):
    assert not has_recent_pitr_window({
        "pitr_enabled": pitr, "walg_enabled": walg, "physical_backup_data": {
            "earliest_physical_backup_date_unix": 1,
            "latest_physical_backup_date_unix": int(NOW.timestamp()),
        }}, NOW)


def test_pitr_freshness_boundary_and_equal_endpoints():
    timestamp = int(NOW.timestamp()) - 48 * 3600
    assert has_recent_pitr_window({
        "pitr_enabled": True, "walg_enabled": True, "physical_backup_data": {
            "earliest_physical_backup_date_unix": timestamp,
            "latest_physical_backup_date_unix": timestamp,
        }}, NOW)


def test_diagnostics_do_not_echo_provider_fields():
    assert backup_summary({
        "backups": [{"id": "private-id", "download_url": "https://private.invalid"}],
        "region": "private-region", "pitr_enabled": True,
        "physical_backup_data": {"secret": "private-value"},
    }, NOW) == {
        "backup_records": 1, "recent_completed_backup": False,
        "pitr_enabled": True, "recent_pitr_window": False,
    }


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
