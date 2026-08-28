from scripts.deployed_smoke import (
    SYNTHETIC_STAGING_USER_ID,
    build_synthetic_staging_init_data,
)
from telegram.auth import verify_init_data


def test_synthetic_staging_init_data_is_short_lived_and_cryptographically_valid(
    monkeypatch,
) -> None:
    token = "123456789:staging-smoke-test-token"
    init_data = build_synthetic_staging_init_data(token, auth_date=1_800_000_000)
    monkeypatch.setattr("telegram.auth.time.time", lambda: 1_800_000_001)

    user = verify_init_data(init_data, token, max_age_seconds=300)

    assert user["id"] == SYNTHETIC_STAGING_USER_ID
    assert user["username"] == "citizen_affairs_staging_smoke"
    assert "staging-smoke-" in init_data
