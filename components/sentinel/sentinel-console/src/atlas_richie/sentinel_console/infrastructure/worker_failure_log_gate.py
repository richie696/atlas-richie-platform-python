"""Bound repeated background-worker failure logs without changing retries."""

from __future__ import annotations

import math
import time

_DEFAULT_REMINDER_INTERVAL_SECONDS = 60.0


class WorkerFailureLogGate:
    """Allow the first failure, changed failure, and periodic reminders through."""

    def __init__(
        self,
        reminder_interval_seconds: float = _DEFAULT_REMINDER_INTERVAL_SECONDS,
    ) -> None:
        if (
            isinstance(reminder_interval_seconds, bool)
            or not isinstance(reminder_interval_seconds, (int, float))
            or not math.isfinite(reminder_interval_seconds)
            or reminder_interval_seconds <= 0
        ):
            raise ValueError("worker failure log reminder interval is invalid")
        self._reminder_interval_seconds = float(reminder_interval_seconds)
        self._last_error_type: str | None = None
        self._last_reported_at: float | None = None

    def should_report(self, error_type: str, *, now: float | None = None) -> bool:
        """Return whether a failure warning should be emitted now."""
        if not isinstance(error_type, str) or not error_type:
            raise ValueError("worker failure error type is invalid")
        observed_at = time.monotonic() if now is None else now
        if (
            isinstance(observed_at, bool)
            or not isinstance(observed_at, (int, float))
            or not math.isfinite(observed_at)
        ):
            raise ValueError("worker failure observation time is invalid")
        if self._last_error_type != error_type or self._last_reported_at is None:
            self._last_error_type = error_type
            self._last_reported_at = float(observed_at)
            return True
        if observed_at - self._last_reported_at >= self._reminder_interval_seconds:
            self._last_reported_at = float(observed_at)
            return True
        return False

    def mark_recovered(self) -> str | None:
        """Return and clear the prior error type after a successful iteration."""
        previous_error_type = self._last_error_type
        self._last_error_type = None
        self._last_reported_at = None
        return previous_error_type


__all__ = ["WorkerFailureLogGate"]
