"""Unit contract for one incident-history expiration pass."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta, timezone

from atlas_richie.sentinel_console.application.expire_incident_history import (
    ExpireIncidentHistory,
)


class RecordingRetention:
    def __init__(self, result: object = 2) -> None:
        self.result = result
        self.received_at: datetime | None = None

    async def expire_incident_history(self, now: datetime) -> int:
        self.received_at = now
        return self.result  # type: ignore[return-value]


class IncidentRetentionUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_normalizes_aware_time_to_utc_and_returns_committed_count(self):
        retention = RecordingRetention()
        local_time = datetime(2026, 10, 15, 12, 0, tzinfo=timezone(timedelta(hours=8)))

        expired = await ExpireIncidentHistory(retention).execute(local_time)

        self.assertEqual(expired, 2)
        self.assertEqual(retention.received_at, datetime(2026, 10, 15, 4, tzinfo=UTC))
        self.assertEqual(retention.received_at.utcoffset(), timedelta(0))

    async def test_rejects_naive_time_and_invalid_storage_count(self):
        retention = RecordingRetention()
        use_case = ExpireIncidentHistory(retention)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            await use_case.execute(datetime(2026, 10, 15))
        self.assertIsNone(retention.received_at)

        with self.assertRaisesRegex(RuntimeError, "invalid count"):
            await ExpireIncidentHistory(RecordingRetention(True)).execute(
                datetime(2026, 10, 15, tzinfo=UTC)
            )


if __name__ == "__main__":
    unittest.main()
