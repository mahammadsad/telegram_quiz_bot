# Contributing

1. Open an issue describing the learner or operator problem before a large change.
2. Create a focused branch; do not commit secrets, generated answer keys, or real learner data.
3. Add tests for behavior and migration contracts.
4. Run `ruff check .`, `mypy`, `pytest -q`, `python scripts/check_public_data.py --history`, and `npm audit`.
5. Keep public quiz projections answer-free and preserve Telegram HMAC validation, server-side scoring, RLS, and privacy-safe leaderboard identities.
6. Submit a draft pull request with migration, deployment, and rollback notes.

Question content must include provenance and evidence accepted by the repository policy. AI output is never treated as verified solely because a second prompt agrees.

The repository does not yet declare a code license. Contributions therefore require an explicit maintainer decision before reuse rights can be assumed.
