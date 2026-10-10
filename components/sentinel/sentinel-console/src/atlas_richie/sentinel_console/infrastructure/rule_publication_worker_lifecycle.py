"""ASGI lifecycle support for a durable rule-publication worker."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

from starlette.applications import Starlette

from ..application.run_rule_publication_worker import RunRulePublicationWorker

_LOGGER = logging.getLogger(__name__)
_MAX_POLL_INTERVAL_SECONDS = 300.0


class RulePublicationWorkerLoop:
    """Poll the durable outbox until the owning ASGI lifespan shuts down."""

    def __init__(
        self,
        worker: RunRulePublicationWorker,
        *,
        poll_interval_seconds: float = 1.0,
        batch_size: int = 10,
    ) -> None:
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or not 0 < poll_interval_seconds <= _MAX_POLL_INTERVAL_SECONDS
        ):
            raise ValueError("publication worker poll interval is invalid")
        if type(batch_size) is not int or not 1 <= batch_size <= 100:
            raise ValueError("publication worker batch size is invalid")
        self._worker = worker
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._batch_size = batch_size

    async def run(self, stop: asyncio.Event) -> None:
        """Run bounded polling; each database claim remains lease-fenced."""
        while not stop.is_set():
            try:
                await self._worker.run_once(limit=self._batch_size)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # Provider and database exception messages may contain secrets or
                # rule content. Keep logs useful without echoing untrusted detail.
                _LOGGER.warning(
                    "rule publication worker iteration failed; error_type=%s",
                    type(error).__name__,
                )
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=self._poll_interval_seconds
                )
            except TimeoutError:
                continue


def install_rule_publication_worker_lifecycle(
    app: Starlette,
    worker: RunRulePublicationWorker,
    *,
    poll_interval_seconds: float = 1.0,
    batch_size: int = 10,
) -> None:
    """Run a publication worker within ASGI startup/shutdown ownership.

    Deployment composition must install this only when the matching provider,
    source resolver, and durable outbox are available. Multi-process safety is
    provided by SQL claim leases and fencing, not by process election here.
    """
    loop = RulePublicationWorkerLoop(
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
                loop.run(stop), name="sentinel-rule-publication-worker"
            )
            try:
                yield
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app.router.lifespan_context = lifespan


__all__ = ["RulePublicationWorkerLoop", "install_rule_publication_worker_lifecycle"]
