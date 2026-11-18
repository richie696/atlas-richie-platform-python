"""Anti-avalanche jitter contract for `CacheFunction.get_random_extra_millis`.

The Redis driver (`atlas-richie-cache-redis`) is the only component that
writes a jittered TTL, and it must take the offset from this single
implementation — an adapter-local copy with a different distribution is a
drift bug. These tests pin the distribution so that cannot happen
silently:

- the offset is a **whole-minute bucket** in `[60_000, 600_000]` ms,
  mirroring Java's `ThreadLocalRandom.current().nextInt(1, 11) * 60_000L`;
- all ten buckets are reachable;
- the offset never escapes the documented bounds.

No backend dependency: `cache-core` stays third-party free.
"""

from __future__ import annotations

from atlas_richie.cache_core.function.cache_function import CacheFunction

#: Smallest possible offset (1 minute).
MIN_OFFSET_MS = 60_000
#: Largest possible offset (10 minutes).
MAX_OFFSET_MS = 600_000
#: Bucket width — the offset is always a whole number of minutes.
BUCKET_MS = 60_000

EXPECTED_BUCKETS = frozenset(
    range(MIN_OFFSET_MS, MAX_OFFSET_MS + 1, BUCKET_MS)
)


def test_offset_is_a_whole_minute_bucket() -> None:
    """Every draw must land on one of the ten whole-minute buckets."""
    for _ in range(500):
        value = CacheFunction.get_random_extra_millis()
        assert value in EXPECTED_BUCKETS, f"unexpected offset: {value}"
        assert value % BUCKET_MS == 0, f"offset is not a minute bucket: {value}"


def test_offset_stays_within_bounds() -> None:
    """The offset never leaves `[60s, 10min]`."""
    for _ in range(500):
        value = CacheFunction.get_random_extra_millis()
        assert MIN_OFFSET_MS <= value <= MAX_OFFSET_MS, (
            f"offset out of bounds: {value}"
        )


def test_all_ten_buckets_are_reachable() -> None:
    """The full bucket set is reachable — no bucket is dead code."""
    seen = {CacheFunction.get_random_extra_millis() for _ in range(5_000)}
    assert seen == EXPECTED_BUCKETS, f"missing buckets: {EXPECTED_BUCKETS - seen}"


def test_offset_is_positive() -> None:
    """A zero offset would defeat the purpose of the jitter."""
    for _ in range(100):
        assert CacheFunction.get_random_extra_millis() > 0
