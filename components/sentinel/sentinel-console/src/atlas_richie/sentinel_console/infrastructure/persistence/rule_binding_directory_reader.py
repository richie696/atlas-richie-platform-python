"""SQL-backed, exact-source reader for Console-owned binding metadata."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.mutate_rule_set import RuleMutationBindingReader
from ...application.rule_binding_ports import (
    RuleBindingAuthorityUnavailable,
    RuleBindingDirectoryReader,
    RuleBindingScopeAuthorityUnavailable,
    RuleBindingScopeReader,
)
from ...domain.rule_bindings import (
    MAX_RULE_BINDING_SCOPE_ITEMS,
    MAX_RULE_BINDING_SCOPE_ROWS,
    RuleBinding,
    RuleBindingPage,
    RuleBindingQuery,
    RuleBindingScopeApplication,
    RuleBindingScopeCatalog,
    RuleBindingScopeEnvironment,
    RuleKind,
)
from .models import (
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RulePublicationTargetRecord,
)
from .rule_publication_target_mapping import target_from_body, target_location


class SqlAlchemyRuleBindingDirectoryReader(
    RuleBindingDirectoryReader, RuleBindingScopeReader, RuleMutationBindingReader
):
    """Resolve exact bindings from metadata, registered sources, and targets.

    The Console database owns only the binding directory metadata. Rule arrays
    remain in the provider configuration center. A missing or inconsistent
    source/target join is an authority error, never a guessed binding.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def read_rule_bindings(self, query: RuleBindingQuery) -> RuleBindingPage:
        """Return a stable, query-bound filtered page from exact authority rows."""
        if not isinstance(query, RuleBindingQuery):
            raise ValueError("rule binding query is invalid")
        bindings = await self._read_bindings(
            environment_id=query.environment_id,
            app_id=query.app_id,
            kind=query.kind,
        )
        if query.search:
            bindings = tuple(
                binding
                for binding in bindings
                if query.search
                in f"{binding.id} {binding.location} {binding.kind.value}"
            )
        offset = (query.page - 1) * query.page_size
        return RuleBindingPage(
            query=query,
            total=len(bindings),
            items=bindings[offset : offset + query.page_size],
        )

    async def read_rule_binding(self, binding_id: str) -> RuleBinding | None:
        """Read one exact binding for rule-command scope validation."""
        if not isinstance(binding_id, str) or not binding_id.strip():
            raise ValueError("rule binding identity is invalid")
        bindings = await self._read_bindings(binding_id=binding_id)
        return bindings[0] if bindings else None

    async def read_rule_binding_scopes(self) -> RuleBindingScopeCatalog:
        """Project selector scopes only from complete persisted binding joins."""
        try:
            bindings = await self._read_bindings(limit=MAX_RULE_BINDING_SCOPE_ROWS + 1)
            if len(bindings) > MAX_RULE_BINDING_SCOPE_ROWS:
                raise RuleBindingScopeAuthorityUnavailable(
                    "rule binding scope authority exceeds its configured bound"
                )
            environment_ids = tuple(sorted({item.environment_id for item in bindings}))
            applications = tuple(
                sorted({(item.environment_id, item.app_id) for item in bindings})
            )
            if (
                len(environment_ids) > MAX_RULE_BINDING_SCOPE_ITEMS
                or len(applications) > MAX_RULE_BINDING_SCOPE_ITEMS
            ):
                raise RuleBindingScopeAuthorityUnavailable(
                    "rule binding scope catalog exceeds its configured bound"
                )
            return RuleBindingScopeCatalog(
                as_of=datetime.now(UTC),
                environments=tuple(
                    RuleBindingScopeEnvironment(id=item, name=item)
                    for item in environment_ids
                ),
                applications=tuple(
                    RuleBindingScopeApplication(
                        id=app_id,
                        environment_id=environment_id,
                        name=app_id,
                    )
                    for environment_id, app_id in applications
                ),
            )
        except (RuleBindingAuthorityUnavailable, ValueError):
            raise RuleBindingScopeAuthorityUnavailable(
                "rule binding scope authority is unavailable"
            ) from None

    async def _read_bindings(
        self,
        *,
        environment_id: str | None = None,
        app_id: str | None = None,
        kind: RuleKind | None = None,
        binding_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[RuleBinding, ...]:
        metadata = RuleBindingRecord.__table__
        sources = RegisteredConfigurationSourceRecord.__table__
        targets = RulePublicationTargetRecord.__table__
        statement = (
            select(
                metadata.c.binding_id,
                metadata.c.environment_id,
                metadata.c.app_id,
                metadata.c.kind,
                metadata.c.profile,
                metadata.c.source_id,
                metadata.c.location,
                sources.c.name.label("source_label"),
                sources.c.provider.label("source_provider"),
                targets.c.source_id.label("target_source_id"),
                targets.c.target_body,
            )
            .select_from(
                metadata.outerjoin(
                    sources, metadata.c.source_id == sources.c.source_id
                ).outerjoin(targets, metadata.c.binding_id == targets.c.binding_id)
            )
            .order_by(metadata.c.binding_id.asc())
        )
        if environment_id is not None:
            statement = statement.where(metadata.c.environment_id == environment_id)
        if app_id is not None:
            statement = statement.where(metadata.c.app_id == app_id)
        if kind is not None:
            statement = statement.where(metadata.c.kind == kind.value)
        if binding_id is not None:
            statement = statement.where(metadata.c.binding_id == binding_id)
        if limit is not None:
            if type(limit) is not int or limit < 1:
                raise ValueError("rule binding authority limit is invalid")
            statement = statement.limit(limit)
        try:
            async with self._engine.connect() as connection:
                rows = (await connection.execute(statement)).mappings().all()
        except SQLAlchemyError:
            raise RuleBindingAuthorityUnavailable(
                "rule binding directory authority is unavailable"
            ) from None
        try:
            return tuple(binding_from_authority_row(row) for row in rows)
        except (KeyError, TypeError, ValueError):
            raise RuleBindingAuthorityUnavailable(
                "rule binding directory authority is unavailable"
            ) from None


def binding_from_authority_row(row: Mapping[str, object]) -> RuleBinding:
    """Validate all joined identities before exposing one directory item."""
    target = target_from_body(row["target_body"])
    if (
        row["source_label"] is None
        or row["source_provider"] is None
        or row["target_source_id"] is None
        or row["source_id"] != row["target_source_id"]
        or target.binding_id != row["binding_id"]
        or target.source_id != row["source_id"]
        or target.provider.value != row["source_provider"]
        or row["location"] != target_location(target)
    ):
        raise ValueError("rule binding authority rows do not agree")
    return RuleBinding(
        id=row["binding_id"],
        environment_id=row["environment_id"],
        app_id=row["app_id"],
        kind=RuleKind(row["kind"]),
        profile=row["profile"],
        source_id=row["source_id"],
        source_label=row["source_label"],
        location=row["location"],
    )


__all__ = ["SqlAlchemyRuleBindingDirectoryReader", "binding_from_authority_row"]
