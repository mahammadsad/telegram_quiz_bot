from __future__ import annotations

from scripts import check_leaderboard_privacy as smoke


def test_smoke_audits_payloads_without_returning_private_values() -> None:
    users = [
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "telegram_id": 9_000_000_001,
            "first_name": "PrivateAlpha",
            "last_name": "HiddenAlpha",
            "username": "private_alpha",
            "photo_url": "https://example.invalid/private-alpha.jpg",
            "public_display_name": None,
            "username_visible": False,
        }
    ]
    payload = {
        "rows": [
            {
                "displayName": "PrivateAlpha HiddenAlpha",
                "photo_url": "https://example.invalid/private-alpha.jpg",
                "opaque": "11111111-1111-4111-8111-111111111111",
            },
            {"displayName": "@private_alpha"},
        ]
    }

    counts = smoke.audit_payloads(users, [payload])

    assert counts.private_name_matches == 1
    assert counts.private_username_matches == 1
    assert counts.private_photo_matches == 1
    assert counts.raw_identifier_fields == 2
    output = smoke.format_counts(counts)
    assert "PrivateAlpha" not in output
    assert "private_alpha" not in output
    assert "11111111" not in output


def test_explicit_public_identity_is_not_counted_as_private_match() -> None:
    users = [
        {
            "id": "22222222-2222-4222-8222-222222222222",
            "telegram_id": 9_000_000_002,
            "first_name": "Chosen Public Label",
            "last_name": "Not Public",
            "username": "chosen_user",
            "photo_url": None,
            "public_display_name": "Chosen Public Label",
            "username_visible": True,
        }
    ]
    payload = {
        "rows": [
            {"displayName": "Chosen Public Label"},
            {"displayName": "@chosen_user"},
        ]
    }

    assert smoke.audit_payloads(users, [payload]) == smoke.PrivacyCounts()


def test_clean_anonymous_payload_produces_required_zero_output() -> None:
    users = [
        {
            "id": "33333333-3333-4333-8333-333333333333",
            "telegram_id": 9_000_000_003,
            "first_name": "Private",
            "last_name": "Learner",
            "username": "private_user",
            "photo_url": "https://example.invalid/private.jpg",
            "public_display_name": None,
            "username_visible": False,
        }
    ]

    counts = smoke.audit_payloads(
        users,
        [{"rows": [{"displayName": "শিক্ষার্থী ABCDEF012345"}]}],
    )

    assert counts == smoke.PrivacyCounts()
    assert smoke.format_counts(counts).splitlines() == [
        "private_name_matches = 0",
        "private_username_matches = 0",
        "private_photo_matches = 0",
        "raw_identifier_fields = 0",
    ]
