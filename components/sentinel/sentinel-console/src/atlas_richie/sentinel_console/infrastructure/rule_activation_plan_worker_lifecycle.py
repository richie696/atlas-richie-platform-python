"""ASGI lifecycle support for durable activation-plan scheduling."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

from starlette.applications import Starlette

from ..application.run_rule_activation_plan_worker import RunRuleActivationPlanWorker

_LOGGER = logging.getLogger(__name__)
_MAX_POLL_INTERVAL_SECONDS = 300.0


class RuleActivationPlanWorkerLoop:
    """Poll SQL-backed plan claims; the database remains the scheduler authority."""

    def __init__(
        self,
        worker: RunRuleActivationPlanWorker,
        *,
        poll_interval_seconds: float = 1.0,
        batch_size: int = 10,
    ) -> None:
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or not 0 < poll_interval_seconds <= _MAX_POLL_INTERVAL_SECONDS
        ):
            raise ValueError("activation plan worker poll interval is invalid")
        if type(batch_size) is not int or not 1 <= batch_size <= 100:
            raise ValueError("activation plan worker batch size is invalid")
        self._worker = worker
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._batch_size = batch_size

    async def run(self, stop: asyncio.Event) -> None:
        """Poll bounded due batches until the owning ASGI lifespan stops."""
        while not stop.is_set():
            try:
                await self._worker.run_once(limit=self._batch_size)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _LOGGER.warning(
                    "rule activation plan worker iteration failed; error_type=%s",
                    type(error).__name__,
                )
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=self._poll_interval_seconds
                )
            except TimeoutError:
                continue


def install_rule_activation_plan_worker_lifecycle(
    app: Starlette,
    worker: RunRuleActivationPlanWorker,
    *,
    poll_interval_seconds: float = 1.0,
    batch_size: int = 10,
) -> None:
    """Run the explicitly assembled scheduler inside ASGI startup/shutdown."""
    loop = RuleActivationPlanWorkerLoop(
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
                loop.run(stop), name="sentinel-rule-activation-plan-worker"
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
    "RuleActivationPlanWorkerLoop",
    "install_rule_activation_plan_worker_lifecycle",
]
