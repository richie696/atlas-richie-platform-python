"""SQL reader for immutable, exact publication targets keyed by binding."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_publication_ports import (
    RulePublicationAuthorityUnavailable,
    RulePublicationTargetReader,
)
from ...domain.rule_publication_targets import VersionedRulePublicationTarget
from .models import (
    RegisteredConfigurationSourceRecord,
    RulePublicationTargetRecord,
)
from .rule_publication_target_mapping import target_from_body


class SqlAlchemyRulePublicationTargetReader(RulePublicationTargetReader):
    """Read only the provider target registered for the requested binding."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def read_rule_publication_target(
        self, binding_id: str
    ) -> VersionedRulePublicationTarget | None:
        """Return an exact target/revision; malformed authority data fails closed."""
        if not isinstance(binding_id, str) or not binding_id.strip():
            raise ValueError("rule publication target binding is invalid")
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(
                        RulePublicationTargetRecord.__table__,
                        RegisteredConfigurationSourceRecord.revision.label(
                            "registered_source_revision"
                        ),
                        RegisteredConfigurationSourceRecord.provider.label(
                            "registered_source_provider"
                        ),
                    )
                    .select_from(
                        RulePublicationTargetRecord.__table__.outerjoin(
                            RegisteredConfigurationSourceRecord.__table__,
                            RegisteredConfigurationSourceRecord.source_id
                            == RulePublicationTargetRecord.source_id,
                        )
                    )
                    .where(
                        RulePublicationTargetRecord.binding_id == binding_id
                    )
                )
                row = result.mappings().one_or_none()
        except SQLAlchemyError:
            raise RulePublicationAuthorityUnavailable(
                "publication target authority is unavailable"
            ) from None
        if row is None:
            return None
        try:
            target = target_from_body(row["target_body"])
            if (
                target.binding_id != binding_id
                or target.source_id != row["source_id"]
                or target.provider.value != row["registered_source_provider"]
                or row["source_revision"]
                != row["registered_source_revision"]
            ):
                raise ValueError("publication target source identity is stale")
            return VersionedRulePublicationTarget(
                revision=row["target_revision"],
                source_revision=row["source_revision"],
                target=target,
            )
        except (KeyError, TypeError, ValueError):
            raise RulePublicationAuthorityUnavailable(
                "publication target authority is unavailable"
            ) from None


__all__ = ["SqlAlchemyRulePublicationTargetReader"]
