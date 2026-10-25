"""SQL persistence for trusted, exact rule-publication target configuration."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_publication_ports import (
    RulePublicationAuthorityUnavailable,
    RulePublicationTargetConflict,
    RulePublicationTargetWriter,
)
from ...domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
    RulePublicationTarget,
    VersionedRulePublicationTarget,
)
from ...domain.utc_time import is_wire_utc_millisecond_instant
from .models import (
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RulePublicationTargetRecord,
)
from .rule_publication_target_mapping import target_body, target_location


class SqlAlchemyRulePublicationTargetWriter(RulePublicationTargetWriter):
    """Compare-and-set a binding target under the current registered source.

    This adapter is a trusted server-side configuration boundary. It must not
    be exposed directly as a browser route without admin authentication,
    CSRF/idempotency handling, and a transactionally associated audit record.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def write_rule_publication_target(
        self,
        target: RulePublicationTarget,
        *,
        source_revision: str,
        expected_revision: str | None,
        now: datetime,
    ) -> VersionedRulePublicationTarget:
        """Persist an exact target if both source and prior mapping revisions match."""
        if not isinstance(
            target, (NacosRulePublicationTarget, ConsulRulePublicationTarget)
        ):
            raise ValueError("rule publication target is invalid")
        if (
            not isinstance(source_revision, str)
            or not source_revision.strip()
            or (
                expected_revision is not None
                and (
                    not isinstance(expected_revision, str)
                    or not expected_revision.strip()
                )
            )
            or not is_wire_utc_millisecond_instant(now)
        ):
            raise ValueError("rule publication target write facts are invalid")

        next_revision = str(uuid4())
        VersionedRulePublicationTarget(
            revision=next_revision,
            source_revision=source_revision,
            target=target,
        )
        if expected_revision is not None:
            VersionedRulePublicationTarget(
                revision=expected_revision,
                source_revision=source_revision,
                target=target,
            )
        try:
            async with self._engine.begin() as connection:
                source_result = await connection.execute(
                    select(
                        RegisteredConfigurationSourceRecord.revision,
                        RegisteredConfigurationSourceRecord.provider,
                    )
                    .where(
                        RegisteredConfigurationSourceRecord.source_id
                        == target.source_id
                    )
                    .with_for_update()
                )
                source = source_result.one_or_none()
                if (
                    source is None
                    or source.revision != source_revision
                    or source.provider != target.provider.value
                ):
                    raise RulePublicationTargetConflict(
                        "registered source does not match the requested target"
                    )

                current_result = await connection.execute(
                    select(RulePublicationTargetRecord.target_revision)
                    .where(
                        RulePublicationTargetRecord.binding_id == target.binding_id
                    )
                    .with_for_update()
                )
                current_revision = current_result.scalar_one_or_none()
                if current_revision != expected_revision:
                    raise RulePublicationTargetConflict(
                        "rule publication target changed"
                    )

                values = {
                    "binding_id": target.binding_id,
                    "source_id": target.source_id,
                    "target_revision": next_revision,
                    "source_revision": source_revision,
                    "target_body": target_body(target),
                    "updated_at": now,
                }
                if current_revision is None:
                    await connection.execute(
                        insert(RulePublicationTargetRecord).values(**values)
                    )
                else:
                    updated = await connection.execute(
                        update(RulePublicationTargetRecord)
                        .where(
                            RulePublicationTargetRecord.binding_id
                            == target.binding_id,
                            RulePublicationTargetRecord.target_revision
                            == expected_revision,
                        )
                        .values(
                            **{
                                key: value
                                for key, value in values.items()
                                if key != "binding_id"
                            }
                        )
                    )
                    if updated.rowcount != 1:
                        raise RulePublicationTargetConflict(
                            "rule publication target changed"
                        )
                await connection.execute(
                    update(RuleBindingRecord)
                    .where(RuleBindingRecord.binding_id == target.binding_id)
                    .values(
                        source_id=target.source_id,
                        location=target_location(target),
                        updated_at=now,
                    )
                )
                return VersionedRulePublicationTarget(
                    revision=next_revision,
                    source_revision=source_revision,
                    target=target,
                )
        except RulePublicationTargetConflict:
            raise
        except IntegrityError:
            raise RulePublicationTargetConflict(
                "rule publication target changed"
            ) from None
        except SQLAlchemyError:
            raise RulePublicationAuthorityUnavailable(
                "publication target authority is unavailable"
            ) from None


__all__ = ["SqlAlchemyRulePublicationTargetWriter"]
