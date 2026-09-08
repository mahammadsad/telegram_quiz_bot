# 8.7.9

- Daily quiz navigation summary and review controls wrap at large text sizes
  instead of overflowing a 320-pixel screen.
- Shared bottom navigation keeps all four Bengali destinations inside their
  tracks without shrinking the learner's text.
- Measured navigation height reserves space below home content and above the
  settings save action as fonts or viewport dimensions change.
- Shell 8.7.9-ui1 refreshes cached frontend assets through the existing tested
  service-worker upgrade path; no private-data cache behavior changes.

The new doubled-text browser stress tests supplement, but do not replace,
native Telegram, OS text-size and Bengali screen-reader acceptance. Protected
CI and exact-SHA staging/production verification remain release gates.

No migration, content activation or hosting upgrade is required. Rollback:
deploy `082dc01aca7cff6f11a8b352045de9af725997e9` (8.7.8), retaining all
platform 1.5.0 migrations. This also retains the official-source redirect repair.
