# 8.7.4

- Makes reserve-aware replenishment fair across subjects: every under-reserve
  subject receives its first available worker slot before any subject receives
  a second slot.
- Retains live fail-closed inventory capacity, deficit ordering inside each
  round, atomic claims, bounded batches, and non-blocking worker concurrency.
- Advances the fail-closed platform contract to `1.3.0`; the application cannot
  report ready until migration `20260904172137` is applied.
