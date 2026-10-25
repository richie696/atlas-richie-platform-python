"""Refresh a bounded batch of registered rule sources into the read projection."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from ..domain.rule_bindings import RuleBinding
from ..domain.rule_catalog import RuleCatalogQuery, RuleCatalogRefreshResult
from ..domain.rule_snapshots import RuleSetSnapshot
from .rule_catalog_ports import RuleCatalogProjection
from .rule_snapshot_ports import (
    RuleSetSnapshotAuthorityUnavailable,
    RuleSetSnapshotInvalid,
    RuleSetSnapshotReader,
    RuleSetSnapshotTargetMissing,
    RuleSetSnapshotUnsupportedProfile,
)

MAX_REFRESH_BATCH = 24
MAX_REFRESH_CONCURRENCY = 8


class RefreshRuleCatalog:
    """Read bounded exact source snapshots and preserve last-known-good rows."""

    def __init__(
        self,
        projection: RuleCatalogProjection,
        snapshot_reader: RuleSetSnapshotReader,
        *,
        clock: Callable[[], datetime],
        concurrency: int = MAX_REFRESH_CONCURRENCY,
        batch_size: int = MAX_REFRESH_BATCH,
    ) -> None:
        if not 1 <= concurrency <= MAX_REFRESH_CONCURRENCY or not 1 <= batch_size <= MAX_REFRESH_BATCH:
            raise ValueError("rule catalog refresh bounds are invalid")
        self._projection = projection
        self._snapshot_reader = snapshot_reader
        self._clock = clock
        self._concurrency = concurrency
        self._batch_size = batch_size

    async def execute(
        self, environment_id: str, app_id: str | None = None
    ) -> RuleCatalogRefreshResult:
        """Refresh oldest bindings first; one source failure never aborts peers."""
        candidates = await self._projection.refresh_candidates(
            environment_id, app_id, self._batch_size
        )
        if any(
            not isinstance(binding, RuleBinding)
            or binding.environment_id != environment_id
            or (app_id is not None and binding.app_id != app_id)
            for binding in candidates
        ):
            raise ValueError("rule catalog refresh candidates escaped their scope")
        semaphore = asyncio.Semaphore(self._concurrency)

        async def refresh_one(binding: RuleBinding) -> None:
            async with semaphore:
                attempted_at = self._clock()
                try:
                    snapshot = await self._snapshot_reader.read_rule_set_snapshot(binding.id)
                    if (
                        not isinstance(snapshot, RuleSetSnapshot)
                        or snapshot.binding.id != binding.id
                        or snapshot.binding != binding
                    ):
                        await self._projection.record_failure(
                            binding, "content_invalid", attempted_at
                        )
                        return
                except RuleSetSnapshotInvalid:
                    await self._projection.record_failure(
                        binding, "content_invalid", attempted_at
                    )
                    return
                except RuleSetSnapshotTargetMissing:
                    await self._projection.record_failure(
                        binding, "target_missing", attempted_at
                    )
                    return
                except RuleSetSnapshotUnsupportedProfile:
                    await self._projection.record_failure(
                        binding, "unsupported_profile", attempted_at
                    )
                    return
                except RuleSetSnapshotAuthorityUnavailable:
                    await self._projection.record_failure(
                        binding, "source_unavailable", attempted_at
                    )
                    return
                except LookupError:
                    await self._projection.record_failure(
                        binding, "source_unavailable", attempted_at
                    )
                    return
                await self._projection.record_success(snapshot, attempted_at)

        await asyncio.gather(*(refresh_one(binding) for binding in candidates))
        as_of = self._clock()
        page = await self._projection.read_catalog(
            _refresh_query(environment_id, app_id)
        )
        return RuleCatalogRefreshResult(
            environment_id=environment_id,
            app_id=app_id,
            as_of=as_of,
            coverage=page.coverage,
            bindings_total=page.bindings_total,
            bindings_attempted=len(candidates),
            bindings_current=page.bindings_current,
            bindings_stale=page.bindings_stale,
            bindings_not_read=page.bindings_not_read,
        )


def _refresh_query(environment_id: str, app_id: str | None):
    return RuleCatalogQuery(environment_id, app_id, None, "", 1, 1)


__all__ = ["MAX_REFRESH_BATCH", "MAX_REFRESH_CONCURRENCY", "RefreshRuleCatalog"]
