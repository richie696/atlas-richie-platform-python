"""Shared PostgreSQL/MySQL acceptance for concurrent idempotent registration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
from uuid import uuid4

from sqlalchemy import delete, event, func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from atlas_richie.sentinel_console.application.rule_binding_ports import (
    RegisterRuleBinding,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleKind
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RuleBindingRegistrationOperationRecord,
    RulePublicationTargetRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    rule_binding_registration_store,
)

_SqlRuleBindingRegistrationStore = (
    rule_binding_registration_store.SqlAlchemyRuleBindingRegistrationStore
)


async def assert_competing_same_key_registrations_are_idempotent(
    engine: AsyncEngine, dialect: str
) -> None:
    """Prove two SQL stores serialize and persist one same-key registration."""
    if dialect not in {"postgresql", "mysql"}:
        raise ValueError("database acceptance dialect is unsupported")

    suffix = uuid4().hex
    current_time = datetime.now(UTC)
    now = current_time.replace(
        microsecond=current_time.microsecond // 1_000 * 1_000
    )
    actor_id = str(uuid4())
    username = f"binding-admin-{suffix}"
    session_token = f"binding-session-{suffix}"
    csrf_token = f"binding-csrf-{suffix}"
    session_digest = hashlib.sha256(session_token.encode("ascii")).hexdigest()
    csrf_digest = hashlib.sha256(csrf_token.encode("ascii")).hexdigest()
    source_id = f"nacos-binding-{suffix}"
    source_revision = f"revision-{suffix}"
    request_key = f"binding-request-{suffix}"
    request_id = f"binding-http-{suffix}"
    binding_id = f"binding-{suffix}"
    username_key = hashlib.sha256(username.encode("ascii")).hexdigest()
    authorization_queries = 0
    both_requests_waiting = asyncio.Event()

    def count_authorization_query(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal authorization_queries
        normalized = statement.casefold()
        if (
            "console_account" in normalized
            and "console_session" in normalized
            and "for update" in normalized
        ):
            authorization_queries += 1
            if authorization_queries >= 2:
                both_requests_waiting.set()

    await _seed_registration_identity(
        engine,
        actor_id=actor_id,
        username=username,
        username_key=username_key,
        session_digest=session_digest,
        csrf_digest=csrf_digest,
        source_id=source_id,
        source_revision=source_revision,
        now=now,
    )

    command = RegisterRuleBinding(
        request_key=request_key,
        binding_id=binding_id,
        environment_id=f"env-{suffix}",
        app_id=f"app-{suffix}",
        kind=RuleKind.FLOW,
        profile="sentinel-flow-v1",
        source_revision=source_revision,
        target=NacosRulePublicationTarget(
            binding_id,
            source_id,
            "acceptance-namespace",
            "DEFAULT_GROUP",
            "flow-rules.json",
        ),
    )
    stores = (
        rule_binding_registration_store.SqlAlchemyRuleBindingRegistrationStore(
            engine
        ),
        rule_binding_registration_store.SqlAlchemyRuleBindingRegistrationStore(
            engine
        ),
    )
    blocker = await engine.connect()
    blocker_transaction = await blocker.begin()
    tasks: list[asyncio.Task] = []
    event.listen(engine.sync_engine, "before_cursor_execute", count_authorization_query)
    try:
        await blocker.execute(
            select(AuthenticationSessionRecord.session_hash)
            .where(AuthenticationSessionRecord.session_hash == session_digest)
            .with_for_update()
        )

        async def register(
            store: _SqlRuleBindingRegistrationStore,
        ):
            return await store.register_rule_binding(
                command,
                actor_id=actor_id,
                session_digest=session_digest,
                csrf_digest=csrf_digest,
                request_id=request_id,
                now=now,
            )

        tasks = [asyncio.create_task(register(store)) for store in stores]
        await asyncio.wait_for(both_requests_waiting.wait(), timeout=15)
        await blocker_transaction.commit()
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=30)

        if results[0] != results[1] or results[0].id != binding_id:
            raise AssertionError("concurrent retries did not recover one binding")

        async with engine.connect() as connection:
            binding_count = await connection.scalar(
                select(func.count())
                .select_from(RuleBindingRecord)
                .where(RuleBindingRecord.binding_id == binding_id)
            )
            target_count = await connection.scalar(
                select(func.count())
                .select_from(RulePublicationTargetRecord)
                .where(RulePublicationTargetRecord.binding_id == binding_id)
            )
            receipt_count = await connection.scalar(
                select(func.count())
                .select_from(RuleBindingRegistrationOperationRecord)
                .where(
                    RuleBindingRegistrationOperationRecord.request_key == request_key
                )
            )
            audit_count = await connection.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(
                    AuditEventRecord.request_id == request_id,
                    AuditEventRecord.target_id == binding_id,
                    AuditEventRecord.action == "rule-binding-create",
                )
            )
        if (binding_count, target_count, receipt_count, audit_count) != (1, 1, 1, 1):
            raise AssertionError("concurrent retry persisted duplicate side effects")
    finally:
        if blocker_transaction.is_active:
            await blocker_transaction.rollback()
        await blocker.close()
        event.remove(
            engine.sync_engine, "before_cursor_execute", count_authorization_query
        )
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await _remove_registration_identity(
            engine,
            actor_id=actor_id,
            session_digest=session_digest,
            source_id=source_id,
            request_key=request_key,
            request_id=request_id,
            binding_id=binding_id,
        )


async def _seed_registration_identity(
    engine: AsyncEngine,
    *,
    actor_id: str,
    username: str,
    username_key: str,
    session_digest: str,
    csrf_digest: str,
    source_id: str,
    source_revision: str,
    now: datetime,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            insert(AccountRecord).values(
                account_id=actor_id,
                username=username,
                username_key=username_key,
                password_hash="$argon2id$synthetic-acceptance-hash",
                role_id="admin",
                status="active",
                built_in=False,
                last_login_at=None,
                revision=1,
                created_at=now,
                updated_at=now,
            )
        )
        await connection.execute(
            insert(AuthenticationSessionRecord).values(
                session_hash=session_digest,
                account_id=actor_id,
                session_epoch=str(uuid4()),
                csrf_hash=csrf_digest,
                created_at=now,
                expires_at=now + timedelta(hours=1),
                revoked_at=None,
            )
        )
        await connection.execute(
            insert(RegisteredConfigurationSourceRecord).values(
                source_id=source_id,
                revision=source_revision,
                name="Disposable binding acceptance source",
                endpoint="https://nacos.acceptance.invalid",
                provider=ConfigurationSourceProvider.NACOS.value,
                location="acceptance",
                authentication_mode="none",
                credential_configured=False,
                credential_cipher_format=None,
                credential_key_id=None,
                credential_payload=None,
                created_at=now,
                updated_at=now,
                updated_by_account_id=actor_id,
            )
        )


async def _remove_registration_identity(
    engine: AsyncEngine,
    *,
    actor_id: str,
    session_digest: str,
    source_id: str,
    request_key: str,
    request_id: str,
    binding_id: str,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            delete(AuditEventRecord).where(
                AuditEventRecord.request_id == request_id,
                AuditEventRecord.target_id == binding_id,
            )
        )
        await connection.execute(
            delete(RuleBindingRegistrationOperationRecord).where(
                RuleBindingRegistrationOperationRecord.request_key == request_key
            )
        )
        await connection.execute(
            delete(RulePublicationTargetRecord).where(
                RulePublicationTargetRecord.binding_id == binding_id
            )
        )
        await connection.execute(
            delete(RuleBindingRecord).where(RuleBindingRecord.binding_id == binding_id)
        )
        await connection.execute(
            delete(RegisteredConfigurationSourceRecord).where(
                RegisteredConfigurationSourceRecord.source_id == source_id
            )
        )
        await connection.execute(
            delete(AuthenticationSessionRecord).where(
                AuthenticationSessionRecord.session_hash == session_digest
            )
        )
        await connection.execute(
            delete(AccountRecord).where(AccountRecord.account_id == actor_id)
        )
