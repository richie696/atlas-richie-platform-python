"""Transactional SQL authority for rule-binding registration."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from secrets import compare_digest
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_binding_ports import (
    RegisterRuleBinding,
    RuleBindingRegistrationAuthorityUnavailable,
    RuleBindingRegistrationConflict,
    RuleBindingRegistrationForbidden,
    RuleBindingRegistrationIdempotencyConflict,
    RuleBindingRegistrationReceiptReader,
    RuleBindingRegistrationUnauthenticated,
)
from ...domain.configuration_source import ConfigurationSourceProvider
from ...domain.rule_bindings import RuleBinding, RuleKind
from ...domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
)
from ...domain.session import AccountRole
from ...domain.utc_time import is_wire_utc_millisecond_instant
from .models import (
    AccountRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RuleBindingRegistrationOperationRecord,
    RulePublicationTargetRecord,
)
from .rule_binding_directory_reader import binding_from_authority_row
from .rule_publication_target_mapping import target_body, target_location


class SqlAlchemyRuleBindingRegistrationStore:
    """Create the binding, exact target, idempotency receipt, and audit atomically."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def read_rule_binding_registration(
        self,
        binding_id: str,
        request_key: str,
        *,
        actor_id: str,
        session_digest: str,
        now: datetime,
    ) -> RuleBinding | None:
        """Read the exact actor receipt after rechecking the current admin session.

        The current session is deliberately not compared to the operation's original
        session hash. It must be a valid active admin session for the same actor;
        write replay continues to enforce its original session and fingerprint.
        """
        if not all(
            isinstance(value, str) and value.strip()
            for value in (binding_id, request_key, actor_id, session_digest)
        ) or not is_wire_utc_millisecond_instant(now):
            raise ValueError("binding registration receipt context is invalid")
        try:
            async with self._engine.begin() as connection:
                await self._authorize_receipt_read(
                    connection,
                    actor_id=actor_id,
                    session_digest=session_digest,
                    now=now,
                )
                operation = RuleBindingRegistrationOperationRecord.__table__
                receipt = await connection.execute(
                    select(operation.c.binding_id)
                    .where(
                        operation.c.request_key == request_key,
                        operation.c.binding_id == binding_id,
                        operation.c.actor_account_id == actor_id,
                    )
                    .limit(1)
                )
                if receipt.scalar_one_or_none() is None:
                    return None
                return await self._read_binding(connection, binding_id)
        except (
            RuleBindingRegistrationForbidden,
            RuleBindingRegistrationUnauthenticated,
        ):
            raise
        except (SQLAlchemyError, TypeError, ValueError):
            raise RuleBindingRegistrationAuthorityUnavailable(
                "binding registration receipt authority is unavailable"
            ) from None

    async def _authorize_receipt_read(
        self,
        connection,
        *,
        actor_id: str,
        session_digest: str,
        now: datetime,
    ) -> None:
        result = await connection.execute(
            select(AccountRecord.role_id)
            .join(
                AuthenticationSessionRecord,
                AuthenticationSessionRecord.account_id == AccountRecord.account_id,
            )
            .where(
                AccountRecord.account_id == actor_id,
                AccountRecord.status == "active",
                AuthenticationSessionRecord.session_hash == session_digest,
                AuthenticationSessionRecord.revoked_at.is_(None),
                AuthenticationSessionRecord.expires_at > now,
            )
            .with_for_update()
        )
        active = result.one_or_none()
        if active is None:
            raise RuleBindingRegistrationUnauthenticated(
                "administrator session is inactive"
            )
        if active.role_id != AccountRole.ADMIN.value:
            raise RuleBindingRegistrationForbidden("administrator role is required")

    async def _read_binding(self, connection, binding_id: str) -> RuleBinding:
        metadata = RuleBindingRecord.__table__
        sources = RegisteredConfigurationSourceRecord.__table__
        targets = RulePublicationTargetRecord.__table__
        result = await connection.execute(
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
                metadata.join(sources, metadata.c.source_id == sources.c.source_id)
                .join(targets, metadata.c.binding_id == targets.c.binding_id)
            )
            .where(metadata.c.binding_id == binding_id)
        )
        binding_row = result.mappings().one_or_none()
        if binding_row is None:
            raise RuleBindingRegistrationAuthorityUnavailable(
                "binding operation result is unavailable"
            )
        return binding_from_authority_row(binding_row)

    async def register_rule_binding(
        self,
        command: RegisterRuleBinding,
        *,
        actor_id: str,
        session_digest: str,
        csrf_digest: str,
        request_id: str,
        now: datetime,
    ) -> RuleBinding:
        """Commit one admin-authorized binding or recover its identical retry."""
        if not _valid_command_context(
            command,
            actor_id=actor_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=request_id,
            now=now,
        ):
            raise ValueError("rule binding registration context is invalid")
        fingerprint = _fingerprint(command)
        try:
            async with self._engine.begin() as connection:
                await self._authorize_write(
                    connection,
                    actor_id=actor_id,
                    session_digest=session_digest,
                    csrf_digest=csrf_digest,
                    now=now,
                )
                prior = await connection.execute(
                    select(RuleBindingRegistrationOperationRecord.__table__)
                    .where(
                        RuleBindingRegistrationOperationRecord.request_key
                        == command.request_key
                    )
                    .with_for_update()
                )
                prior_row = prior.mappings().one_or_none()
                if prior_row is not None:
                    return await self._recover(
                        connection,
                        prior_row,
                        actor_id=actor_id,
                        session_digest=session_digest,
                        fingerprint=fingerprint,
                    )

                source_result = await connection.execute(
                    select(
                        RegisteredConfigurationSourceRecord.revision,
                        RegisteredConfigurationSourceRecord.name,
                        RegisteredConfigurationSourceRecord.provider,
                    )
                    .where(
                        RegisteredConfigurationSourceRecord.source_id
                        == command.target.source_id
                    )
                    .with_for_update()
                )
                source = source_result.one_or_none()
                if (
                    source is None
                    or source.revision != command.source_revision
                    or source.provider != command.target.provider.value
                ):
                    raise RuleBindingRegistrationConflict(
                        "registered source identity or revision changed"
                    )

                instant = now.astimezone(UTC)
                await connection.execute(
                    insert(RuleBindingRecord).values(
                        binding_id=command.binding_id,
                        environment_id=command.environment_id,
                        app_id=command.app_id,
                        kind=command.kind.value,
                        profile=command.profile,
                        source_id=command.target.source_id,
                        location=target_location(command.target),
                        created_at=instant,
                        updated_at=instant,
                    )
                )
                await connection.execute(
                    insert(RulePublicationTargetRecord).values(
                        binding_id=command.binding_id,
                        source_id=command.target.source_id,
                        target_revision=str(uuid4()),
                        source_revision=command.source_revision,
                        target_body=target_body(command.target),
                        updated_at=instant,
                    )
                )
                await connection.execute(
                    insert(RuleBindingRegistrationOperationRecord).values(
                        request_key=command.request_key,
                        actor_account_id=actor_id,
                        session_hash=session_digest,
                        fingerprint_digest=fingerprint,
                        binding_id=command.binding_id,
                        created_at=instant,
                    )
                )
                await connection.execute(
                    insert(AuditEventRecord).values(
                        event_id=str(uuid4()),
                        request_id=request_id,
                        actor_account_id=actor_id,
                        action="rule-binding-create",
                        outcome="completed",
                        target_kind="rule_binding",
                        target_id=command.binding_id,
                        created_at=instant,
                    )
                )
                return RuleBinding(
                    id=command.binding_id,
                    environment_id=command.environment_id,
                    app_id=command.app_id,
                    kind=command.kind,
                    profile=command.profile,
                    source_id=command.target.source_id,
                    source_label=source.name,
                    location=target_location(command.target),
                )
        except (
            RuleBindingRegistrationConflict,
            RuleBindingRegistrationForbidden,
            RuleBindingRegistrationIdempotencyConflict,
            RuleBindingRegistrationUnauthenticated,
        ):
            raise
        except IntegrityError:
            raise RuleBindingRegistrationConflict(
                "rule binding scope or identity already exists"
            ) from None
        except (SQLAlchemyError, TypeError, ValueError):
            raise RuleBindingRegistrationAuthorityUnavailable(
                "rule binding registration authority is unavailable"
            ) from None

    async def _authorize_write(
        self,
        connection,
        *,
        actor_id: str,
        session_digest: str,
        csrf_digest: str,
        now: datetime,
    ) -> None:
        result = await connection.execute(
            select(AccountRecord.role_id, AuthenticationSessionRecord.csrf_hash)
            .join(
                AuthenticationSessionRecord,
                AuthenticationSessionRecord.account_id == AccountRecord.account_id,
            )
            .where(
                AccountRecord.account_id == actor_id,
                AccountRecord.status == "active",
                AuthenticationSessionRecord.session_hash == session_digest,
                AuthenticationSessionRecord.revoked_at.is_(None),
                AuthenticationSessionRecord.expires_at > now,
            )
            .with_for_update()
        )
        active = result.one_or_none()
        if active is None or not compare_digest(active.csrf_hash, csrf_digest):
            raise RuleBindingRegistrationUnauthenticated(
                "administrator session is inactive"
            )
        if active.role_id != AccountRole.ADMIN.value:
            raise RuleBindingRegistrationForbidden("administrator role is required")

    async def _recover(
        self,
        connection,
        row,
        *,
        actor_id: str,
        session_digest: str,
        fingerprint: str,
    ) -> RuleBinding:
        if (
            row["actor_account_id"] != actor_id
            or row["session_hash"] != session_digest
        ):
            raise RuleBindingRegistrationForbidden(
                "binding operation belongs to another session"
            )
        if not compare_digest(row["fingerprint_digest"], fingerprint):
            raise RuleBindingRegistrationIdempotencyConflict(
                "idempotency key was used for another binding"
            )
        return await self._read_binding(connection, row["binding_id"])


def _valid_command_context(
    command: RegisterRuleBinding,
    *,
    actor_id: str,
    session_digest: str,
    csrf_digest: str,
    request_id: str,
    now: datetime,
) -> bool:
    return (
        isinstance(command, RegisterRuleBinding)
        and all(
            isinstance(value, str) and bool(value.strip())
            for value in (actor_id, session_digest, csrf_digest, request_id)
        )
        and len(command.request_key) <= 128
        and is_wire_utc_millisecond_instant(now)
        and command.target.source_id.strip() != ""
        and isinstance(
            command.target,
            (NacosRulePublicationTarget, ConsulRulePublicationTarget),
        )
        and command.target.provider
        in (ConfigurationSourceProvider.NACOS, ConfigurationSourceProvider.CONSUL)
    )


def _fingerprint(command: RegisterRuleBinding) -> str:
    """Hash the non-secret canonical command identity for exact retry checks."""
    payload = {
        "bindingId": command.binding_id,
        "environmentId": command.environment_id,
        "appId": command.app_id,
        "kind": command.kind.value,
        "profile": command.profile,
        "sourceRevision": command.source_revision,
        "target": target_body(command.target),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["SqlAlchemyRuleBindingRegistrationStore"]
