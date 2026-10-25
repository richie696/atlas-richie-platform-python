"""ASGI lifecycle support for the Console rule-load projection worker."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

from starlette.applications import Starlette

from ..application.run_rule_load_observation_projection_worker import (
    RunRuleLoadObservationProjectionWorker,
)
from .persistence.runtime_database_engine_provider import RuntimeDatabaseNotConfigured
from .worker_failure_log_gate import WorkerFailureLogGate

_LOGGER = logging.getLogger(__name__)
_MAX_POLL_INTERVAL_SECONDS = 300.0


class RuleLoadObservationProjectionWorkerLoop:
    """Poll bounded SQL outbox batches until Console shutdown."""

    def __init__(
        self,
        worker: RunRuleLoadObservationProjectionWorker,
        *,
        poll_interval_seconds: float = 1.0,
        batch_size: int = 10,
    ) -> None:
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or not 0 < poll_interval_seconds <= _MAX_POLL_INTERVAL_SECONDS
        ):
            raise ValueError("rule-load projection poll interval is invalid")
        if type(batch_size) is not int or not 1 <= batch_size <= 100:
            raise ValueError("rule-load projection batch size is invalid")
        self._worker = worker
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._batch_size = batch_size

    async def run(self, stop: asyncio.Event) -> None:
        """Run short durable polls; SQL lease tokens fence concurrent workers."""
        failure_log_gate = WorkerFailureLogGate()
        while not stop.is_set():
            try:
                await self._worker.run_once(
                    now=datetime.now(UTC), batch_size=self._batch_size
                )
            except asyncio.CancelledError:
                raise
            except RuntimeDatabaseNotConfigured:
                pass
            except Exception as error:  # noqa: BLE001 - keep the loop available
                error_type = type(error).__name__
                if failure_log_gate.should_report(error_type):
                    _LOGGER.warning(
                        "rule-load projection worker iteration failed; error_type=%s",
                        error_type,
                    )
            else:
                previous_error_type = failure_log_gate.mark_recovered()
                if previous_error_type is not None:
                    _LOGGER.info(
                        "rule-load projection worker recovered; previous_error_type=%s",
                        previous_error_type,
                    )
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                continue


def install_rule_load_observation_projection_worker_lifecycle(
    app: Starlette,
    worker: RunRuleLoadObservationProjectionWorker,
    *,
    poll_interval_seconds: float = 1.0,
    batch_size: int = 10,
) -> None:
    """Own the bounded projection task within the Console ASGI lifespan."""
    loop = RuleLoadObservationProjectionWorkerLoop(
        worker,
        poll_interval_seconds=poll_interval_seconds,
        batch_size=batch_size,
    )
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: Starlette) -> AsyncIterator[None]:
        async with previous_lifespan(application):
            stop = asyncio.Event()
            task = asyncio.create_task(
                loop.run(stop), name="sentinel-rule-load-observation-projection"
            )
            try:
                yield
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app.router.lifespan_context = lifespan


__all__ = [
    "RuleLoadObservationProjectionWorkerLoop",
    "install_rule_load_observation_projection_worker_lifecycle",
]
