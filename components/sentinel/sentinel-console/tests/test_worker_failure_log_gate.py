from __future__ import annotations

import unittest

from atlas_richie.sentinel_console.infrastructure.worker_failure_log_gate import (
    WorkerFailureLogGate,
)


class WorkerFailureLogGateTests(unittest.TestCase):
    def test_reports_first_changed_and_periodic_failures(self) -> None:
        gate = WorkerFailureLogGate(reminder_interval_seconds=60)

        self.assertTrue(gate.should_report("DatabaseUnavailable", now=10))
        self.assertFalse(gate.should_report("DatabaseUnavailable", now=69.9))
        self.assertTrue(gate.should_report("DatabaseUnavailable", now=70))
        self.assertTrue(gate.should_report("SchemaUnavailable", now=71))

    def test_success_clears_failure_and_next_failure_is_reported(self) -> None:
        gate = WorkerFailureLogGate(reminder_interval_seconds=60)

        self.assertTrue(gate.should_report("DatabaseUnavailable", now=10))
        self.assertEqual(gate.mark_recovered(), "DatabaseUnavailable")
        self.assertIsNone(gate.mark_recovered())
        self.assertTrue(gate.should_report("DatabaseUnavailable", now=11))

    def test_rejects_invalid_interval_and_error_identity(self) -> None:
        for interval in (0, -1, float("inf"), True):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                WorkerFailureLogGate(interval)

        gate = WorkerFailureLogGate()
        with self.assertRaises(ValueError):
            gate.should_report("", now=0)


if __name__ == "__main__":
    unittest.main()
