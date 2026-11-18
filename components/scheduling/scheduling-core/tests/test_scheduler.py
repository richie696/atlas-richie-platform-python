"""Scheduler tests.

Timing is asserted with events and short intervals rather than fixed sleeps, so
the suite is deterministic and fast. Long-interval cases verify prompt shutdown.
"""

from __future__ import annotations

import threading
import time

import pytest

from atlas_richie.scheduling_core import ScheduleKind, Scheduler

pytestmark = pytest.mark.unit

TIMEOUT = 5.0


class TestRecurring:
    def test_interval_job_runs_repeatedly(self) -> None:
        hits: list[float] = []
        with Scheduler() as scheduler:
            scheduler.schedule_interval(0.01, lambda: hits.append(time.monotonic()))
            deadline = time.monotonic() + TIMEOUT
            while len(hits) < 3 and time.monotonic() < deadline:
                time.sleep(0.005)
        assert len(hits) >= 3

    def test_fixed_delay_job_runs_repeatedly(self) -> None:
        count = []
        with Scheduler() as scheduler:
            scheduler.schedule_fixed_delay(0.01, lambda: count.append(1))
            deadline = time.monotonic() + TIMEOUT
            while len(count) < 3 and time.monotonic() < deadline:
                time.sleep(0.005)
        assert len(count) >= 3

    def test_fixed_delay_measures_from_run_end(self) -> None:
        """A 60ms run with a 40ms delay must space starts ~100ms apart, not 40ms."""
        starts: list[float] = []

        def slow() -> None:
            starts.append(time.monotonic())
            time.sleep(0.06)

        with Scheduler() as scheduler:
            scheduler.schedule_fixed_delay(0.04, slow)
            deadline = time.monotonic() + TIMEOUT
            while len(starts) < 3 and time.monotonic() < deadline:
                time.sleep(0.005)
        assert len(starts) >= 3
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        assert all(gap >= 0.09 for gap in gaps), gaps

    def test_interval_measures_from_run_start(self) -> None:
        starts: list[float] = []

        def slow() -> None:
            starts.append(time.monotonic())
            time.sleep(0.02)

        with Scheduler() as scheduler:
            scheduler.schedule_interval(0.05, slow)
            deadline = time.monotonic() + TIMEOUT
            while len(starts) < 3 and time.monotonic() < deadline:
                time.sleep(0.005)
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        assert all(0.04 <= gap <= 0.09 for gap in gaps), gaps

    def test_runs_never_overlap(self) -> None:
        active = []
        max_active = []
        lock = threading.Lock()

        def job() -> None:
            with lock:
                active.append(1)
                max_active.append(len(active))
            time.sleep(0.03)
            with lock:
                active.pop()

        with Scheduler() as scheduler:
            scheduler.schedule_interval(0.005, job)
            time.sleep(0.2)
        assert max_active and max(max_active) == 1

    def test_initial_delay_is_respected(self) -> None:
        fired = threading.Event()
        scheduler = Scheduler()
        scheduler.schedule_interval(0.01, fired.set, initial_delay=0.15)
        scheduler.start()
        try:
            assert fired.wait(0.05) is False, "must not run before the initial delay"
            assert fired.wait(TIMEOUT) is True
        finally:
            scheduler.stop()


class TestOneShot:
    def test_once_runs_exactly_once(self) -> None:
        calls: list[int] = []
        scheduler = Scheduler()
        job = scheduler.schedule_once(0.02, lambda: calls.append(1))
        scheduler.start()
        try:
            assert job.wait_finished(TIMEOUT)
            time.sleep(0.1)
            assert calls == [1]
            assert job.stats.runs == 1
            assert job.stats.finished is True
        finally:
            scheduler.stop()

    def test_once_kind(self) -> None:
        scheduler = Scheduler()
        job = scheduler.schedule_once(0.01, lambda: None)
        assert job.kind is ScheduleKind.ONCE
        scheduler.stop()


class TestExceptionIsolation:
    def test_failing_job_does_not_stop_the_scheduler(self) -> None:
        good: list[int] = []

        def bad() -> None:
            raise RuntimeError("boom")

        with Scheduler() as scheduler:
            failing = scheduler.schedule_interval(0.01, bad, name="bad")
            scheduler.schedule_interval(0.01, lambda: good.append(1), name="good")
            deadline = time.monotonic() + TIMEOUT
            while len(good) < 3 and time.monotonic() < deadline:
                time.sleep(0.005)
        assert len(good) >= 3
        assert failing.stats.failures >= 1
        assert "RuntimeError: boom" in (failing.stats.last_error or "")

    def test_error_handler_is_notified(self) -> None:
        seen: list[tuple[str, str]] = []
        fired = threading.Event()

        def handler(name: str, error: BaseException) -> None:
            seen.append((name, type(error).__name__))
            fired.set()

        with Scheduler(error_handler=handler) as scheduler:
            scheduler.schedule_interval(0.01, lambda: (_ for _ in ()).throw(ValueError("x")), name="j")
            assert fired.wait(TIMEOUT)
        assert seen and seen[0] == ("j", "ValueError")

    def test_broken_error_handler_does_not_stop_the_job(self) -> None:
        runs: list[int] = []

        def handler(name, error):
            raise RuntimeError("handler down")

        def job() -> None:
            runs.append(1)
            raise ValueError("job down")

        with Scheduler(error_handler=handler) as scheduler:
            handle = scheduler.schedule_interval(0.01, job)
            deadline = time.monotonic() + TIMEOUT
            while handle.stats.failures < 3 and time.monotonic() < deadline:
                time.sleep(0.005)
        assert handle.stats.failures >= 3
        assert len(runs) >= 3

    def test_stats_record_last_run_at(self) -> None:
        with Scheduler() as scheduler:
            job = scheduler.schedule_interval(0.01, lambda: None)
            deadline = time.monotonic() + TIMEOUT
            while job.stats.runs < 1 and time.monotonic() < deadline:
                time.sleep(0.005)
        assert job.stats.last_run_at is not None
        assert job.stats.runs >= 1
        assert job.stats.failures == 0


class TestShutdown:
    def test_stop_is_prompt_even_with_a_long_interval(self) -> None:
        scheduler = Scheduler()
        scheduler.schedule_interval(30.0, lambda: None)
        scheduler.start()
        started = time.monotonic()
        assert scheduler.stop(timeout=2.0) == []
        assert time.monotonic() - started < 1.0, "stop must not wait out the interval"

    def test_stop_reports_unfinished_jobs(self) -> None:
        release = threading.Event()
        started = threading.Event()

        def stuck() -> None:
            started.set()
            release.wait(10)

        scheduler = Scheduler()
        scheduler.schedule_interval(0.01, stuck, name="stuck")
        scheduler.start()
        assert started.wait(TIMEOUT)
        try:
            assert scheduler.stop(timeout=0.1) == ["stuck"]
        finally:
            release.set()
            scheduler.stop(timeout=2.0)

    def test_stop_is_idempotent(self) -> None:
        scheduler = Scheduler()
        scheduler.schedule_interval(0.01, lambda: None)
        scheduler.start()
        assert scheduler.stop() == []
        assert scheduler.stop() == []

    def test_cannot_schedule_after_stop(self) -> None:
        scheduler = Scheduler()
        scheduler.stop()
        with pytest.raises(RuntimeError, match="已停止"):
            scheduler.schedule_interval(0.01, lambda: None)

    def test_cannot_restart_after_stop(self) -> None:
        scheduler = Scheduler()
        scheduler.stop()
        with pytest.raises(RuntimeError, match="已停止"):
            scheduler.start()

    def test_cancel_stops_only_that_job(self) -> None:
        cancelled: list[int] = []
        other: list[int] = []
        scheduler = Scheduler()
        first = scheduler.schedule_interval(0.01, lambda: cancelled.append(1), name="first")
        scheduler.schedule_interval(0.01, lambda: other.append(1), name="second")
        scheduler.start()
        try:
            deadline = time.monotonic() + TIMEOUT
            while len(cancelled) < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            first.cancel()
            assert first.wait_finished(TIMEOUT)
            settled = len(cancelled)
            deadline = time.monotonic() + TIMEOUT
            while len(other) < settled + 3 and time.monotonic() < deadline:
                time.sleep(0.005)
            assert len(cancelled) == settled, "cancelled job must not run again"
            assert len(other) > settled
        finally:
            scheduler.stop()

    def test_context_manager_starts_and_stops(self) -> None:
        hits: list[int] = []
        with Scheduler() as scheduler:
            assert scheduler.started is True
            scheduler.schedule_interval(0.01, lambda: hits.append(1))
            deadline = time.monotonic() + TIMEOUT
            while not hits and time.monotonic() < deadline:
                time.sleep(0.005)
        assert hits
        assert all(not job.running for job in scheduler.jobs())

    def test_job_registered_after_start_runs_immediately(self) -> None:
        fired = threading.Event()
        scheduler = Scheduler()
        scheduler.start()
        try:
            scheduler.schedule_interval(0.01, fired.set)
            assert fired.wait(TIMEOUT)
        finally:
            scheduler.stop()

    def test_stop_before_start_finishes_pending_jobs(self) -> None:
        scheduler = Scheduler()
        job = scheduler.schedule_interval(0.01, lambda: None)
        assert scheduler.stop() == []
        assert job.stats.finished is True


class TestValidation:
    @pytest.mark.parametrize("seconds", [-1.0, 0.0])
    def test_recurring_requires_positive_interval(self, seconds: float) -> None:
        scheduler = Scheduler()
        with pytest.raises(ValueError):
            scheduler.schedule_interval(seconds, lambda: None)
        scheduler.stop()

    def test_negative_initial_delay_rejected(self) -> None:
        scheduler = Scheduler()
        with pytest.raises(ValueError):
            scheduler.schedule_interval(0.01, lambda: None, initial_delay=-1)
        scheduler.stop()

    def test_non_callable_rejected(self) -> None:
        scheduler = Scheduler()
        with pytest.raises(TypeError):
            scheduler.schedule_interval(0.01, "not callable")  # type: ignore[arg-type]
        scheduler.stop()

    def test_once_accepts_zero_delay(self) -> None:
        fired = threading.Event()
        with Scheduler() as scheduler:
            scheduler.schedule_once(0.0, fired.set)
            assert fired.wait(TIMEOUT)

    def test_job_name_defaults_to_function_name(self) -> None:
        def my_job() -> None:
            pass

        scheduler = Scheduler()
        job = scheduler.schedule_interval(0.01, my_job)
        assert job.name == "my_job"
        scheduler.stop()
