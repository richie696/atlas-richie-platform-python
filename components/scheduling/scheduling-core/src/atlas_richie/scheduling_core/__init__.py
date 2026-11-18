"""Interval, fixed-delay and one-shot job scheduling.

Zero dependencies: threads and events from the standard library. Extracted because
`secret-rotation-daemon` and the console's activation-plan worker each hand-roll
the same polling loop, graceful stop and exception isolation.

Design: one daemon thread per job, runs are sequential within a job (a slow run
delays the next tick rather than overlapping), different jobs run concurrently.
Stopping signals an event so shutdown is prompt instead of waiting out a sleep,
and joins each thread within the remaining timeout.

Not included: cron expression parsing and a persistent job store. Those are
separate concerns (Quartz-style scheduling) and would add dependencies.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable

_log = logging.getLogger(__name__)


class ScheduleKind(StrEnum):
    INTERVAL = "INTERVAL"
    FIXED_DELAY = "FIXED_DELAY"
    ONCE = "ONCE"


@dataclass
class JobStats:
    runs: int = 0
    failures: int = 0
    last_error: str | None = None
    last_run_at: float | None = None
    finished: bool = False


@dataclass
class Job:
    """A scheduled job handle. `stats` is a live snapshot, updated under a lock."""

    id: str
    name: str
    kind: ScheduleKind
    seconds: float
    stats: JobStats = field(default_factory=JobStats)
    _fn: Callable[[], None] = field(repr=False, default=lambda: None)
    _initial_delay: float = field(repr=False, default=0.0)
    _stop: threading.Event = field(repr=False, default_factory=threading.Event)
    _thread: threading.Thread | None = field(repr=False, default=None)
    _lock: threading.Lock = field(repr=False, default_factory=threading.Lock)
    _done: threading.Event = field(repr=False, default_factory=threading.Event)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def cancel(self) -> None:
        """Stop this job. A run already in flight is allowed to finish."""
        self._stop.set()

    def wait_finished(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)


class Scheduler:
    """Owns a set of jobs and their threads; supports graceful shutdown."""

    def __init__(
        self,
        *,
        name: str = "scheduler",
        error_handler: Callable[[str, BaseException], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._name = name
        self._error_handler = error_handler
        self._clock = clock
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._started = False
        self._stopped = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def started(self) -> bool:
        return self._started

    def jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def schedule_interval(
        self,
        seconds: float,
        fn: Callable[[], None],
        *,
        name: str | None = None,
        initial_delay: float = 0.0,
    ) -> Job:
        """Fixed-rate: the next tick is measured from the START of the previous run.

        A run longer than the interval simply delays the next tick; runs never
        overlap.
        """
        return self._add(ScheduleKind.INTERVAL, seconds, fn, name, initial_delay)

    def schedule_fixed_delay(
        self,
        seconds: float,
        fn: Callable[[], None],
        *,
        name: str | None = None,
        initial_delay: float = 0.0,
    ) -> Job:
        """Fixed-delay: the next tick is measured from the END of the previous run."""
        return self._add(ScheduleKind.FIXED_DELAY, seconds, fn, name, initial_delay)

    def schedule_once(
        self, seconds: float, fn: Callable[[], None], *, name: str | None = None
    ) -> Job:
        return self._add(ScheduleKind.ONCE, seconds, fn, name, seconds)

    def _add(
        self,
        kind: ScheduleKind,
        seconds: float,
        fn: Callable[[], None],
        name: str | None,
        initial_delay: float,
    ) -> Job:
        if seconds < 0 or initial_delay < 0:
            raise ValueError("seconds and initial_delay must be >= 0")
        if kind is not ScheduleKind.ONCE and seconds <= 0:
            raise ValueError("recurring jobs need a positive interval")
        if not callable(fn):
            raise TypeError("fn must be callable")
        with self._lock:
            if self._stopped:
                raise RuntimeError("scheduler已停止，不能继续注册任务")
            job = Job(
                id=uuid.uuid4().hex,
                name=name or getattr(fn, "__name__", "job"),
                kind=kind,
                seconds=seconds,
                _fn=fn,
                _initial_delay=initial_delay,
            )
            self._jobs[job.id] = job
            if self._started:
                self._spawn(job)
            return job

    def start(self) -> None:
        with self._lock:
            if self._stopped:
                raise RuntimeError("scheduler已停止，不能重新启动")
            if self._started:
                return
            self._started = True
            for job in self._jobs.values():
                self._spawn(job)

    def _spawn(self, job: Job) -> None:
        thread = threading.Thread(
            target=self._run, args=(job,), name=f"{self._name}:{job.name}", daemon=True
        )
        job._thread = thread
        thread.start()

    def _run(self, job: Job) -> None:
        try:
            if job._stop.wait(job._initial_delay):
                return
            while not job._stop.is_set():
                started_at = self._clock()
                self._invoke(job)
                if job.kind is ScheduleKind.ONCE:
                    return
                if job.kind is ScheduleKind.INTERVAL:
                    elapsed = self._clock() - started_at
                    wait_for = max(0.0, job.seconds - elapsed)
                else:
                    wait_for = job.seconds
                if job._stop.wait(wait_for):
                    return
        finally:
            with job._lock:
                job.stats.finished = True
            job._done.set()

    def _invoke(self, job: Job) -> None:
        try:
            job._fn()
        except BaseException as error:  # noqa: BLE001 — one job must not kill the scheduler
            with job._lock:
                job.stats.failures += 1
                job.stats.last_error = f"{type(error).__name__}: {error}"
            _log.exception("job failed; scheduler=%s job=%s", self._name, job.name)
            if self._error_handler is not None:
                try:
                    self._error_handler(job.name, error)
                except Exception:  # noqa: BLE001 — a broken handler must not stop the job
                    _log.exception("scheduler error_handler raised; job=%s", job.name)
        else:
            with job._lock:
                job.stats.runs += 1
        finally:
            with job._lock:
                job.stats.last_run_at = self._clock()

    def stop(self, timeout: float | None = 5.0) -> list[str]:
        """Signal every job and join within `timeout`.

        Returns the names of jobs whose in-flight run did not finish in time.
        Idempotent; the scheduler cannot be restarted afterwards.
        """
        with self._lock:
            self._stopped = True
            jobs = list(self._jobs.values())
        for job in jobs:
            job._stop.set()
        deadline = None if timeout is None else time.monotonic() + timeout
        unfinished: list[str] = []
        for job in jobs:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if job._thread is not None:
                job._thread.join(remaining)
                if job._thread.is_alive():
                    unfinished.append(job.name)
            elif not job._done.is_set():
                job._done.set()
                with job._lock:
                    job.stats.finished = True
        return unfinished

    def __enter__(self) -> Scheduler:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


__all__ = ["Job", "JobStats", "ScheduleKind", "Scheduler"]
