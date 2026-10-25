"""ASGI lifecycle support for a durable rule-publication worker."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from starlette.applications import Starlette

from ..application.run_rule_publication_worker import RunRulePublicationWorker
from .persistence.rule_publish_outbox import RulePublishClaimConflict
from .persistence.runtime_database_engine_provider import (
    RuntimeDatabaseNotConfigured,
)

_LOGGER = logging.getLogger(__name__)
_MAX_POLL_INTERVAL_SECONDS = 300.0
_MAX_ERROR_BACKOFF_SECONDS = 30.0
_RETRY_JITTER_UPPER_FACTOR = 1.5


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
        consecutive_failures = 0
        failure_delay_seconds = self._poll_interval_seconds
        error_backoff_ceiling = max(
            _MAX_ERROR_BACKOFF_SECONDS, self._poll_interval_seconds
        )
        while not stop.is_set():
            wait_seconds = self._poll_interval_seconds
            try:
                await self._worker.run_once(limit=self._batch_size)
            except asyncio.CancelledError:
                raise
            except RuntimeDatabaseNotConfigured:
                # Before first-run setup selects a database, polling is expected.
                # Keep retrying so this process becomes active after setup.
                consecutive_failures = 0
                failure_delay_seconds = self._poll_interval_seconds
            except Exception as error:
                consecutive_failures += 1
                if consecutive_failures > 1:
                    failure_delay_seconds = min(
                        failure_delay_seconds * 2, error_backoff_ceiling
                    )
                jitter_floor_seconds = max(
                    self._poll_interval_seconds,
                    min(failure_delay_seconds, error_backoff_ceiling / 2),
                )
                jitter_ceiling_seconds = min(
                    failure_delay_seconds * _RETRY_JITTER_UPPER_FACTOR,
                    error_backoff_ceiling,
                )
                wait_seconds = min(
                    random.uniform(
                        jitter_floor_seconds,
                        jitter_ceiling_seconds,
                    ),
                    error_backoff_ceiling,
                )
                # Provider and database exception messages may contain secrets or
                # rule content. Keep logs useful without echoing untrusted detail.
                if isinstance(error, RulePublishClaimConflict):
                    # These messages are fixed internal fencing reasons, never
                    # provider responses or user-controlled content.
                    _LOGGER.warning(
                        "rule publication worker iteration failed; "
                        "error_type=%s; reason=%s",
                        type(error).__name__,
                        str(error),
                    )
                else:
                    _LOGGER.warning(
                        "rule publication worker iteration failed; error_type=%s",
                        type(error).__name__,
                    )
            else:
                consecutive_failures = 0
                failure_delay_seconds = self._poll_interval_seconds
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait_seconds)
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
