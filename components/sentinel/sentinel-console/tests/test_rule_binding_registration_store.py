"""SQL transaction tests for exact, idempotent binding registration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.rule_binding_ports import (
    RegisterRuleBinding,
    RuleBindingRegistrationConflict,
    RuleBindingRegistrationForbidden,
    RuleBindingRegistrationIdempotencyConflict,
    RuleBindingRegistrationUnauthenticated,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleKind
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
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
from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_registration_store import (
    SqlAlchemyRuleBindingRegistrationStore,
)

_NOW = datetime(2026, 10, 10, 12, 30, 0, 123000, tzinfo=UTC)
_ACTOR = "binding-admin"
_SESSION = "a" * 64
_CSRF = "b" * 64
_SOURCE = "nacos-main"
_SOURCE_REVISION = "source-revision-1"


class RuleBindingRegistrationStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        await self._seed_admin_and_source()
        self.store = SqlAlchemyRuleBindingRegistrationStore(self.engine)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_registration_atomically_persists_binding_target_receipt_and_audit(self):
        binding = await self._register()

        self.assertEqual(binding.id, "binding-1")
        self.assertEqual(binding.source_label, "Operations Nacos")
        self.assertEqual(
            binding.location,
            "nacos://prod-namespace/DEFAULT_GROUP/flow-rules.json",
        )
        async with self.engine.connect() as connection:
            metadata = (
                await connection.execute(select(RuleBindingRecord.__table__))
            ).mappings().one()
            target = (
                await connection.execute(select(RulePublicationTargetRecord.__table__))
            ).mappings().one()
            receipt = (
                await connection.execute(
                    select(RuleBindingRegistrationOperationRecord.__table__)
                )
            ).mappings().one()
            audit = (await connection.execute(select(AuditEventRecord.__table__))).mappings().one()

        self.assertEqual(metadata["binding_id"], "binding-1")
        self.assertEqual(target["source_revision"], _SOURCE_REVISION)
        self.assertEqual(target["target_body"]["dataId"], "flow-rules.json")
        self.assertNotIn("rules", target["target_body"])
        self.assertEqual(receipt["request_key"], "binding-request-1")
        self.assertEqual(receipt["session_hash"], _SESSION)
        self.assertEqual(audit["action"], "rule-binding-create")
        self.assertEqual(audit["target_id"], "binding-1")

    async def test_same_key_and_payload_recovers_one_binding_without_duplicate_audit(self):
        first = await self._register()
        retried = await self._register()

        self.assertEqual(retried, first)
        async with self.engine.connect() as connection:
            binding_count = await connection.scalar(
                select(func.count()).select_from(RuleBindingRecord)
            )
            target_count = await connection.scalar(
                select(func.count()).select_from(RulePublicationTargetRecord)
            )
            audit_count = await connection.scalar(
                select(func.count()).select_from(AuditEventRecord)
            )
        self.assertEqual(binding_count, 1)
        self.assertEqual(target_count, 1)
        self.assertEqual(audit_count, 1)

    async def test_same_key_different_payload_is_rejected_without_side_effect(self):
        await self._register()
        changed = self._command(profile="sentinel-flow-v2")
        with self.assertRaises(RuleBindingRegistrationIdempotencyConflict):
            await self._invoke(changed)
        self.assertEqual(await self._count(RuleBindingRecord), 1)
        self.assertEqual(await self._count(AuditEventRecord), 1)

    async def test_source_revision_and_provider_must_match_registered_source(self):
        stale = self._command(source_revision="stale-revision")
        with self.assertRaises(RuleBindingRegistrationConflict):
            await self._invoke(stale)

        mismatched = self._command(
            target=ConsulRulePublicationTarget(
                "binding-1", _SOURCE, "rules/flow.json", "dc1"
            )
        )
        with self.assertRaises(RuleBindingRegistrationConflict):
            await self._invoke(mismatched)
        self.assertEqual(await self._count(RuleBindingRecord), 0)
        self.assertEqual(await self._count(RulePublicationTargetRecord), 0)

    async def test_duplicate_scope_is_rejected_and_does_not_write_partial_target(self):
        await self._register()
        command = self._command(
            request_key="binding-request-2", binding_id="binding-2"
        )
        with self.assertRaises(RuleBindingRegistrationConflict):
            await self._invoke(command)
        self.assertEqual(await self._count(RuleBindingRecord), 1)
        self.assertEqual(await self._count(RulePublicationTargetRecord), 1)
        self.assertEqual(await self._count(RuleBindingRegistrationOperationRecord), 1)

    async def test_authority_rechecks_admin_role_and_csrf_inside_transaction(self):
        async with self.engine.begin() as connection:
            await connection.execute(
                AccountRecord.__table__.update()
                .where(AccountRecord.account_id == _ACTOR)
                .values(role_id="view")
            )
        with self.assertRaises(RuleBindingRegistrationForbidden):
            await self._register()
        self.assertEqual(await self._count(RuleBindingRecord), 0)

        async with self.engine.begin() as connection:
            await connection.execute(
                AccountRecord.__table__.update()
                .where(AccountRecord.account_id == _ACTOR)
                .values(role_id="admin")
            )
        with self.assertRaises(RuleBindingRegistrationUnauthenticated):
            await self._invoke(self._command(), csrf_digest="wrong-csrf-digest")
        self.assertEqual(await self._count(RuleBindingRecord), 0)

    async def test_consul_target_is_supported_when_registered_source_is_consul(self):
        await self._register_source(ConfigurationSourceProvider.CONSUL)
        command = self._command(
            target=ConsulRulePublicationTarget(
                "binding-1", _SOURCE, "sentinel/prod/flow-rules", "dc1"
            )
        )
        binding = await self._invoke(command)
        self.assertEqual(binding.location, "consul://dc1/sentinel/prod/flow-rules")

    async def _register(self, **command_changes):
        return await self._invoke(self._command(**command_changes))

    async def _invoke(self, command, *, csrf_digest=_CSRF):
        return await self.store.register_rule_binding(
            command,
            actor_id=_ACTOR,
            session_digest=_SESSION,
            csrf_digest=csrf_digest,
            request_id="binding-registration-request-id",
            now=_NOW,
        )

    @staticmethod
    def _command(
        *,
        request_key="binding-request-1",
        binding_id="binding-1",
        source_revision=_SOURCE_REVISION,
        profile="sentinel-flow-v1",
        target=None,
    ):
        return RegisterRuleBinding(
            request_key=request_key,
            binding_id=binding_id,
            environment_id="prod",
            app_id="checkout",
            kind=RuleKind.FLOW,
            profile=profile,
            source_revision=source_revision,
            target=target
            or NacosRulePublicationTarget(
                binding_id,
                _SOURCE,
                "prod-namespace",
                "DEFAULT_GROUP",
                "flow-rules.json",
            ),
        )

    async def _seed_admin_and_source(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id=_ACTOR,
                    username="binding-admin",
                    username_key="c" * 64,
                    password_hash="$argon2id$synthetic-hash",
                    role_id="admin",
                    status="active",
                    built_in=False,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=_SESSION,
                    account_id=_ACTOR,
                    session_epoch="epoch-1",
                    csrf_hash=_CSRF,
                    created_at=_NOW,
                    expires_at=_NOW + timedelta(days=1),
                    revoked_at=None,
                )
            )
            await connection.execute(
                insert(RegisteredConfigurationSourceRecord).values(
                    source_id=_SOURCE,
                    revision=_SOURCE_REVISION,
                    name="Operations Nacos",
                    endpoint="https://nacos.example.test",
                    provider=ConfigurationSourceProvider.NACOS.value,
                    location="prod",
                    authentication_mode="none",
                    credential_configured=False,
                    credential_cipher_format=None,
                    credential_key_id=None,
                    credential_payload=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                    updated_by_account_id=_ACTOR,
                )
            )

    async def _register_source(self, provider: ConfigurationSourceProvider) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                RegisteredConfigurationSourceRecord.__table__.update()
                .where(RegisteredConfigurationSourceRecord.source_id == _SOURCE)
                .values(provider=provider.value)
            )

    async def _count(self, table) -> int:
        async with self.engine.connect() as connection:
            return await connection.scalar(select(func.count()).select_from(table))


if __name__ == "__main__":
    unittest.main()
