"""Immutable source identities for every migration recorded in production.

These hashes are MD5 only to retain the original Supabase ledger-audit format;
they are integrity identifiers, not security primitives. The 37 historical
sources were matched to production statement bytes. Later sources were matched
by version/name after production-schema equivalence checks and then pinned from
the applied release. The historical set was independently re-read on 2026-08-24;
the learner-bootstrap source was pinned after its gated production apply and
contract verification on 2026-08-31. New migrations must not be added before
their own production apply and verification succeeds.
"""

from __future__ import annotations

PRODUCTION_LEDGER_SOURCE_MD5: dict[str, tuple[str, str]] = {
    "atomic_quiz_integrity": ("20260718124105", "73636f261938e77ab62018f24537a623"),
    "question_provenance_reporting": ("20260718124214", "460f4e8a7b34c89c0cdba718dfd20519"),
    "syllabus_v2_catalogue": ("20260718163445", "8bfc6e641a4076eebb440218f43a7e5e"),
    "learning_resources_foundation": ("20260718174627", "0a56b31ff2051a104e9fc149605a6299"),
    "learning_resources_fk_indexes": ("20260718174639", "666497e1b0719dcb20a0b4d3d8109db4"),
    "learning_resources_legacy_pack_compatibility": ("20260718180231", "38d786ad1da53f8ef7fe15968c9f2b38"),
    "personalized_learning_foundation": ("20260718184133", "97cf8cd4851f16075a5d935cdd1bd613"),
    "personalized_learning_fk_compatibility": ("20260718184138", "8e7ef21c7fc31e57d7632cac6c361150"),
    "remove_redundant_personal_review_unique": ("20260718185411", "9375da34d75c4a08b67bdfca5a9e32f1"),
    "learning_analytics_leaderboards": ("20260718193324", "b8368579ff710266f38c43ff55b9a67c"),
    "personal_practice_answers": ("20260718193329", "d67e567a41c07f09fbf7cd424e6aaa24"),
    "canonical_subject_learning_projections": ("20260718193333", "eb0d9fbf05ee914dd522967091bfa927"),
    "canonical_subject_storage_compatibility": ("20260718193337", "1cc19b8f219b7b95ed72d3040d1b34ed"),
    "resource_quality_operations": ("20260718200550", "9b95a514d0d150f0f6fdca82cea93adb"),
    "dedupe_source_resource_cache": ("20260718203738", "dbaebfdbbcdfd48cb42c7cf8852f57c4"),
    "production_integrity_contract_v2": ("20260727104645", "cc53752216bbf7209cef3eadcfdea955"),
    "learning_and_leaderboard_contract_v2": ("20260727104716", "d0fa875b4ad16651d679ff33eccc5cab"),
    "revision_reports_and_rankings": ("20260727104740", "1852c779b936c0d2a1a745fdb537483c"),
    "durable_write_rate_limits": ("20260727104755", "168cbec32deed6af0ac0498fbf9292ca"),
    "source_backed_rotation_v1": ("20260728080439", "74618e5918a1e4fa92a34b84af7908be"),
    "quiz_quality_and_negative_marking": ("20260729105500", "8e09f17eedd81ab0b3ad31ec6e515606"),
    "personal_learning_projection_hotfix": ("20260729140552", "09348ab128de2695daacea89d775d4ba"),
    "leaderboard_privacy_hotfix": ("20260808140807", "bcf58aaa7e9788d0457da552e2ac64b0"),
    "atomic_quiz_post_finalization": ("20260808140812", "a1afdb9995958257d47bc93f4188282a"),
    "durable_quiz_jobs": ("20260808140819", "a7eaf229063989caa1d15c1861567d5a"),
    "fix_leaderboard_privacy_contract_invoker": ("20260808140823", "8a5b42a987bf545b84d57b5b8f90573d"),
    "phase_c_content_identity_foundation": ("20260808140838", "bf5985782f5e05e68578f6368d0c1dc8"),
    "phase_c_inventory_jobs_and_usage": ("20260808140843", "676467c6481664a869cd1cd05c177c4b"),
    "phase_c_verified_candidate_persistence": ("20260808140850", "5e620e647a009b8db24397e9b2de5032"),
    "phase_d_current_affairs_events": ("20260808140855", "6e0134a7ae7f4d02ff2b0c2b77cc3358"),
    "phase_e_personal_knowledge_mastery": ("20260808140909", "7d73b3d2916b97a8b909c2fceeb38083"),
    "phase_e_exam_configuration": ("20260808140917", "245b823e851a1613c1fe5a3238e141bd"),
    "phase_e_previous_year_and_mock_attempts": ("20260808140930", "ac25174eb5f278090c22757101e6b5bb"),
    "phase_e_question_quality_administration": ("20260808140935", "688fa52dbc3a1bf87796a45e8934f62d"),
    "source_optional_timeless_quiz_generation": ("20260808160554", "a7c1d0040cc20b374017e3331332e8d6"),
    "bound_cached_source_resource_titles": ("20260808184535", "09c78f77388a73e953eef22809dace80"),
    "current_affairs_claim_hash_parity": ("20260808190716", "32703f999e62dcc8ae3e3be37c2d328f"),
    "server_timed_daily_attempts": ("20260820090000", "84d5327542c6944bc2d17b7e2be3c9de"),
    "question_verification_independence": ("20260820100000", "75bb8ce7e28aaa640a94919c2e55c710"),
    "learning_test_catalog": ("20260820110000", "4cd4301181ae174c7980f8f03c3c4b70"),
    "privacy_rights": ("20260820120000", "2ed80725129098eb22e3241e7ad559db"),
    "job_subject_fk_indexes": ("20260821090000", "d0b3c65c6232e9a73d6dcb62519074ab"),
    "harden_pg_trgm_extension": ("20260821091000", "a1f3ae33e373b14787f9b8943d3d3955"),
    "restore_chapter_history_uniqueness": ("20260821100000", "7e755cf7e1db7835cb0987508f12dd7b"),
    "reconcile_unknown_quiz_post": ("20260821101000", "a0009b52c69e3ede8913ec70a696e670"),
    "platform_contract_v1": ("20260822190025", "7f02d50664b19d8ae9391a009a9e8653"),
    "learner_report_status_projection": ("20260823065257", "e4de3dc550bf911651011134e6d9a463"),
    "durable_reminder_consent_delivery": ("20260824033823", "ea17591b8070d6ef1708acac43ef74cf"),
    "fair_content_replenishment_claims": ("20260824052500", "0bab7058c930df4b2d532123dcefc94f"),
    "operator_blocked_quiz_recovery": ("20260826080000", "af474c52612e3876d9fc6fb63ce01354"),
    "deduplicate_open_content_replenishment_jobs": (
        "20260827040000",
        "b8ca0e0c5320733f6ec6ad3a4260de8a",
    ),
    "durable_primary_scheduler": (
        "20260828211539",
        "022a4a02595b0c5e0e3eacddd2d04ea7",
    ),
    "dashboard_rpc_transaction_mode": (
        "20260829031810",
        "a471a2859bdb35f4e19142a6fb3366d9",
    ),
    "bookmark_question_identity_projection": (
        "20260829091919",
        "ce721bd2fb27738e6b1769e34deb4d31",
    ),
    "pg_net_extension_schema_hardening": (
        "20260829094700",
        "4c3411cfee52734a924723cbc0f61aea",
    ),
    "pg_net_request_sequence_continuity": (
        "20260829152100",
        "fdf579cd3c01a8753f365e1d18b7c23a",
    ),
    "guarded_validation_dead_letter_recovery": (
        "20260829163136",
        "9eac16f908e3b760049efae42244f8c9",
    ),
    "source_optional_stable_replenishment": (
        "20260830095000",
        "ab3f913d9af0afa1db75a6599e3e0ae2",
    ),
    "return_new_replenishment_jobs": (
        "20260830095800",
        "ba1b9f9bdd908631d317103767c18f16",
    ),
    "learner_bootstrap_latency_contract": (
        "20260831011657",
        "162ec1e833d4d79d39723e8f839abbb1",
    ),
    "reserve_aware_replenishment_claims": (
        "20260904164836",
        "ab2f7a8b0b28b07ddd3ef42479f30ca1",
    ),
    "reserve_tier_round_robin_claims": (
        "20260904172137",
        "55a6c8aeb8e367f030ffdd83bc3a2f13",
    ),
}


def ledger_version(migration_name: str) -> str:
    return PRODUCTION_LEDGER_SOURCE_MD5[migration_name][0]
