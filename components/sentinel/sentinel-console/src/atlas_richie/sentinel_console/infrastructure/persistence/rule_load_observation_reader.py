"""SQL read adapter for the authenticated Console API 0.9 load view."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from atlas_richie.contracts.rules.load_observation.v1 import (
    RuleKind as ObservedRuleKind,
    RuleLoadEventKind,
    RuleLoadFailureReason,
)

from ...application.rule_load_observation_query_ports import (
    RuleLoadObservationQueryReader,
)
from ...domain.rule_catalog import RuleCatalogCoverage
from ...domain.rule_load_observation_query import (
    RuleLoadAttemptView,
    RuleLoadFreshness,
    RuleLoadMemberView,
    RuleLoadObservationItem,
    RuleLoadObservationPage,
    RuleLoadObservationQuery,
    RuleLoadObservationTargets,
    RuleLoadObservedState,
    RuleLoadSnapshotView,
)
from ...domain.utc_time import current_utc_millisecond_instant
from ..rule_profile_capabilities import SUPPORTED_RULE_LOAD_PROFILES
from .models import (
    MetricsReporterBindingRecord,
    RuleBindingRecord,
    RuleLoadObservationCurrentRecord,
)

STALE_AFTER = timedelta(seconds=90)


class SqlAlchemyRuleLoadObservationReader(RuleLoadObservationQueryReader):
    """Join registered bindings, active enrollments, and durable current facts."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        clock=current_utc_millisecond_instant,
    ) -> None:
        self._engine = engine
        self._clock = clock

    async def read_rule_load_observations(
        self, query: RuleLoadObservationQuery
    ) -> RuleLoadObservationPage:
        if not isinstance(query, RuleLoadObservationQuery):
            raise TypeError("rule load observation query is invalid")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("query clock must return an aware instant")
        cutoff = now - STALE_AFTER
        binding = RuleBindingRecord.__table__
        reporter = MetricsReporterBindingRecord.__table__
        current = RuleLoadObservationCurrentRecord.__table__
        scope = [
            binding.c.environment_id == query.environment_id,
            binding.c.app_id == query.app_id,
            reporter.c.revoked_at.is_(None),
        ]
        if query.binding_id is not None:
            scope.append(binding.c.binding_id == query.binding_id)
        if query.instance_id is not None:
            scope.append(reporter.c.instance_id == query.instance_id)
        base = (
            select(
                binding.c.binding_id.label("binding_id"),
                reporter.c.certificate_principal.label("certificate_principal"),
                current.c.observation_id.label("observation_id"),
                current.c.received_at.label("received_at"),
            )
            .select_from(
                binding.join(
                    reporter,
                    and_(
                        reporter.c.environment_id == binding.c.environment_id,
                        reporter.c.app_id == binding.c.app_id,
                    ),
                ).outerjoin(
                    current,
                    and_(
                        current.c.binding_id == binding.c.binding_id,
                        current.c.certificate_principal == reporter.c.certificate_principal,
                        reporter.c.current_epoch.is_not(None),
                        current.c.process_epoch == reporter.c.current_epoch,
                    ),
                )
            )
            .where(*scope)
        )
        base_rows = base.subquery()
        try:
            async with self._engine.connect() as connection:
                total = int(
                    await connection.scalar(select(func.count()).select_from(base_rows))
                    or 0
                )
                # An empty result from the enrollment table is not an authoritative
                # empty application inventory. It means no enrolled reporter can
                # establish the expected-target denominator for this query.
                if total == 0:
                    return RuleLoadObservationPage(
                        query=query,
                        as_of=_utc(now),
                        coverage=RuleCatalogCoverage.PARTIAL,
                        targets=RuleLoadObservationTargets(
                            expected=None,
                            observed=None,
                            stale=None,
                            not_observed=None,
                        ),
                        total=None,
                        has_more=False,
                        items=(),
                    )
                observed = int(
                    await connection.scalar(
                        select(
                            func.sum(
                                case((base_rows.c.observation_id.is_not(None), 1), else_=0)
                            )
                        )
                    )
                    or 0
                )
                stale = int(
                    await connection.scalar(
                        select(
                            func.sum(
                                case(
                                    (
                                        and_(
                                            base_rows.c.observation_id.is_not(None),
                                            base_rows.c.received_at < cutoff,
                                        ),
                                        1,
                                    ),
                                    else_=0,
                                )
                            )
                        )
                    )
                    or 0
                )
                rows_statement = (
                    select(
                        binding.c.binding_id,
                        reporter.c.instance_id,
                        reporter.c.process_id,
                        current.c.process_epoch,
                        current.c.profile_id,
                        current.c.event_kind,
                        current.c.active_snapshot,
                        current.c.attempt,
                        current.c.observed_at,
                        current.c.received_at,
                    )
                    .select_from(
                        binding.join(
                            reporter,
                            and_(
                                reporter.c.environment_id == binding.c.environment_id,
                                reporter.c.app_id == binding.c.app_id,
                            ),
                        ).outerjoin(
                            current,
                            and_(
                                current.c.binding_id == binding.c.binding_id,
                                current.c.certificate_principal
                                == reporter.c.certificate_principal,
                                reporter.c.current_epoch.is_not(None),
                                current.c.process_epoch == reporter.c.current_epoch,
                            ),
                        )
                    )
                    .where(*scope)
                    .order_by(binding.c.binding_id.asc(), reporter.c.instance_id.asc())
                    .offset((query.page - 1) * query.page_size)
                    .limit(query.page_size + 1)
                )
                rows = (await connection.execute(rows_statement)).mappings().all()
        except SQLAlchemyError:
            raise RuntimeError("rule load observation query is unavailable") from None

        has_more = len(rows) > query.page_size
        items = tuple(
            _item_from_row(row, cutoff=cutoff)
            for row in rows[: query.page_size]
        )
        return RuleLoadObservationPage(
            query=query,
            as_of=_utc(now),
            coverage=RuleCatalogCoverage.COMPLETE,
            targets=RuleLoadObservationTargets(
                expected=total,
                observed=observed,
                stale=stale,
                not_observed=max(0, total - observed),
            ),
            total=total,
            has_more=has_more,
            items=items,
        )


def _item_from_row(
    row: Mapping[str, object], *, cutoff: datetime
) -> RuleLoadObservationItem:
    received = row["received_at"]
    observed = row["observed_at"]
    event_kind_raw = row["event_kind"]
    active = _snapshot_view(row["active_snapshot"], row["profile_id"])
    attempt = _attempt_view(row["attempt"])
    if event_kind_raw is None:
        event_kind = None
        load_state = RuleLoadObservedState.NOT_OBSERVED
        freshness = RuleLoadFreshness.UNKNOWN
        process_epoch = None
        profile_id = None
    else:
        event_kind = RuleLoadEventKind(event_kind_raw)
        freshness = (
            RuleLoadFreshness.STALE
            if isinstance(received, datetime) and _utc(received) < cutoff
            else RuleLoadFreshness.CURRENT
        )
        process_epoch = row["process_epoch"]
        profile_id = row["profile_id"]
        if event_kind is RuleLoadEventKind.SNAPSHOT_FAILED:
            load_state = (
                RuleLoadObservedState.FAILED_KEEPS_LAST_KNOWN_GOOD
                if active is not None
                else RuleLoadObservedState.FAILED_BEFORE_FIRST_LOAD
            )
        elif event_kind is RuleLoadEventKind.SNAPSHOT_APPLIED or active is not None:
            load_state = RuleLoadObservedState.APPLIED
        else:
            load_state = RuleLoadObservedState.NOT_OBSERVED
    return RuleLoadObservationItem(
        binding_id=row["binding_id"],
        instance_id=row["instance_id"],
        process_id=row["process_id"],
        process_epoch=process_epoch,
        profile_id=profile_id,
        load_state=load_state,
        event_kind=event_kind,
        active_snapshot=active,
        attempt=attempt,
        observed_at=_utc(observed) if isinstance(observed, datetime) else None,
        received_at=_utc(received) if isinstance(received, datetime) else None,
        freshness=freshness,
    )


def _snapshot_view(value: object, profile_id: object) -> RuleLoadSnapshotView | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("stored rule snapshot is malformed")
    members_raw = value.get("members")
    complete = value.get("membership_complete") is True
    supported = profile_id in SUPPORTED_RULE_LOAD_PROFILES
    members: tuple[RuleLoadMemberView, ...] = ()
    if complete and supported and isinstance(members_raw, list):
        members = tuple(
            RuleLoadMemberView(
                rule_kind=ObservedRuleKind(item["rule_kind"]),
                fingerprint_sha256=item["fingerprint_sha256"],
            )
            for item in members_raw
            if isinstance(item, dict)
        )
        if len(members) != len(members_raw):
            raise ValueError("stored rule membership is malformed")
    return RuleLoadSnapshotView(
        source_revision=value.get("source_revision"),
        canonical_rules_sha256=value["canonical_rules_sha256"],
        membership_complete=complete and supported,
        members=members,
    )


def _attempt_view(value: object) -> RuleLoadAttemptView | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("stored rule attempt is malformed")
    return RuleLoadAttemptView(
        source_revision=value.get("source_revision"),
        canonical_rules_sha256=value.get("canonical_rules_sha256"),
        failure_reason=RuleLoadFailureReason(value["failure_reason"]),
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["STALE_AFTER", "SqlAlchemyRuleLoadObservationReader"]
