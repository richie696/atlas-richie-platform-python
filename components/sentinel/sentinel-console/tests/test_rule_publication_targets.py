"""Contracts for exact server-side publication target resolution."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.rule_publication_ports import (
    RulePublicationAuthorityUnavailable,
    RulePublicationTargetConflict,
    RulePublicationTargetReader,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
    VersionedRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_target_mapping import (
    target_body,
    target_from_body,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_target_reader import (
    SqlAlchemyRulePublicationTargetReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_target_writer import (
    SqlAlchemyRulePublicationTargetWriter,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    RegisteredConfigurationSourceRecord,
    RulePublicationTargetRecord,
)

_NOW = datetime(2026, 10, 9, tzinfo=UTC)


class RulePublicationTargetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    def test_provider_targets_keep_exact_mapping_separate(self) -> None:
        nacos = NacosRulePublicationTarget(
            "binding-a", "source-a", "namespace-a", "DEFAULT_GROUP", "app-flow.json"
        )
        consul = ConsulRulePublicationTarget(
            "binding-b", "source-b", "sentinel/apps/app-b/flow.json", "dc-east"
        )

        self.assertEqual(nacos.provider, ConfigurationSourceProvider.NACOS)
        self.assertEqual(nacos.data_id, "app-flow.json")
        self.assertEqual(consul.provider, ConfigurationSourceProvider.CONSUL)
        self.assertEqual(consul.key, "sentinel/apps/app-b/flow.json")
        self.assertNotIn("password", repr(nacos))
        self.assertNotIn("token", repr(consul))

    def test_missing_and_invalid_targets_are_not_defaulted(self) -> None:
        invalid_nacos = (
            {"binding_id": "", "source_id": "source", "namespace": "ns",
             "group": "group", "data_id": "rules.json"},
            {"binding_id": "binding", "source_id": "source", "namespace": "ns",
             "group": "group", "data_id": "rules\n.json"},
            {"binding_id": "binding", "source_id": "source", "namespace": "ns",
             "group": "group", "data_id": "x" * 513},
            {"binding_id": "binding", "source_id": "source", "namespace": "\ufeff",
             "group": "group", "data_id": "rules.json"},
            {"binding_id": "binding", "source_id": "source", "namespace": "safe\x01value",
             "group": "group", "data_id": "rules.json"},
            {"binding_id": "binding", "source_id": "source\x01id", "namespace": "ns",
             "group": "group", "data_id": "rules.json"},
            {"binding_id": "binding", "source_id": "source", "namespace": "\ud800",
             "group": "group", "data_id": "rules.json"},
            {"binding_id": "b" * 201, "source_id": "source", "namespace": "ns",
             "group": "group", "data_id": "rules.json"},
        )
        for values in invalid_nacos:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    NacosRulePublicationTarget(**values)

        for key in ("", "/rules", "rules/", "rules//flow", "rules/../flow"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    ConsulRulePublicationTarget("binding", "source", key)

    def test_provider_target_values_accept_512_units_but_not_more(self) -> None:
        nacos = NacosRulePublicationTarget(
            "binding-a",
            "source-a",
            "n" * 512,
            "g" * 512,
            "d" * 512,
        )
        consul = ConsulRulePublicationTarget(
            "binding-b", "source-b", "k" * 512, "d" * 512
        )
        self.assertEqual(len(nacos.namespace), 512)
        self.assertEqual(len(consul.key), 512)
        NacosRulePublicationTarget(
            "binding-c", "source-c", "🚀" * 256, "group", "rules.json"
        )
        with self.assertRaises(ValueError):
            NacosRulePublicationTarget(
                "binding-c", "source-c", "🚀" * 257, "group", "rules.json"
            )

    def test_provider_target_storage_mapping_is_exact_and_round_trips(self) -> None:
        targets = (
            NacosRulePublicationTarget(
                "binding-a", "source-a", "namespace-a", "DEFAULT_GROUP", "orders.json"
            ),
            ConsulRulePublicationTarget(
                "binding-b", "source-b", "sentinel/orders/flow.json", "dc-west"
            ),
        )
        for target in targets:
            with self.subTest(target=target.provider):
                body = target_body(target)
                self.assertEqual(target_from_body(body), target)
                self.assertNotIn("credential", str(body).lower())
                extra = {**body, "unexpected": "value"}
                with self.assertRaises(ValueError):
                    target_from_body(extra)

    async def test_reader_port_is_consumer_owned_and_exact_binding_scoped(self) -> None:
        class Reader:
            async def read_rule_publication_target(self, binding_id: str):
                if binding_id == "binding-a":
                    return VersionedRulePublicationTarget(
                        revision="mapping-rev-1",
                        source_revision="source-rev-1",
                        target=NacosRulePublicationTarget(
                            binding_id,
                            "source-a",
                            "namespace-a",
                            "DEFAULT_GROUP",
                            "orders-flow.json",
                        ),
                    )
                return None

        reader: RulePublicationTargetReader = Reader()
        self.assertEqual(
            await reader.read_rule_publication_target("binding-a"),
            VersionedRulePublicationTarget(
                revision="mapping-rev-1",
                source_revision="source-rev-1",
                target=NacosRulePublicationTarget(
                    "binding-a",
                    "source-a",
                    "namespace-a",
                    "DEFAULT_GROUP",
                    "orders-flow.json",
                ),
            ),
        )
        self.assertIsNone(await reader.read_rule_publication_target("missing-binding"))

    async def test_sql_reader_preserves_exact_target_revision_and_missing_is_none(
        self,
    ) -> None:
        await self._seed_registered_source(
            source_id="source-sql",
            revision="source-rev-2",
            provider=ConfigurationSourceProvider.NACOS,
        )
        target = NacosRulePublicationTarget(
            "binding-sql", "source-sql", "namespace-sql", "DEFAULT_GROUP", "flow.json"
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RulePublicationTargetRecord).values(
                    binding_id=target.binding_id,
                    source_id=target.source_id,
                    target_revision="mapping-rev-7",
                    source_revision="source-rev-2",
                    target_body=target_body(target),
                    updated_at=_NOW,
                )
            )

        reader = SqlAlchemyRulePublicationTargetReader(self.engine)
        result = await reader.read_rule_publication_target("binding-sql")
        self.assertIsNotNone(result)
        self.assertEqual(result.revision, "mapping-rev-7")
        self.assertEqual(result.source_revision, "source-rev-2")
        self.assertEqual(result.target, target)
        self.assertIsNone(await reader.read_rule_publication_target("missing-sql"))

    async def test_sql_reader_hides_malformed_or_cross_binding_mapping(self) -> None:
        await self._seed_registered_source(
            source_id="source-sql",
            revision="source-rev-2",
            provider=ConfigurationSourceProvider.CONSUL,
        )
        target = ConsulRulePublicationTarget(
            "binding-body", "source-sql", "sentinel/app/flow.json"
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RulePublicationTargetRecord).values(
                    binding_id="binding-row",
                    source_id=target.source_id,
                    target_revision="mapping-rev-8",
                    source_revision="source-rev-2",
                    target_body=target_body(target),
                    updated_at=_NOW,
                )
            )

        reader = SqlAlchemyRulePublicationTargetReader(self.engine)
        with self.assertRaises(RulePublicationAuthorityUnavailable):
            await reader.read_rule_publication_target("binding-row")

    async def test_sql_reader_rejects_stale_source_revision(self) -> None:
        await self._seed_registered_source(
            source_id="source-stale",
            revision="source-current-rev",
            provider=ConfigurationSourceProvider.NACOS,
        )
        target = NacosRulePublicationTarget(
            "binding-stale",
            "source-stale",
            "namespace",
            "DEFAULT_GROUP",
            "flow.json",
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RulePublicationTargetRecord).values(
                    binding_id=target.binding_id,
                    source_id=target.source_id,
                    target_revision="mapping-rev-stale",
                    source_revision="source-old-rev",
                    target_body=target_body(target),
                    updated_at=_NOW,
                )
            )

        reader = SqlAlchemyRulePublicationTargetReader(self.engine)
        with self.assertRaises(RulePublicationAuthorityUnavailable):
            await reader.read_rule_publication_target("binding-stale")

    async def test_target_writer_creates_and_replaces_with_exact_revisions(self) -> None:
        await self._seed_registered_source(
            source_id="source-write",
            revision="source-rev-1",
            provider=ConfigurationSourceProvider.NACOS,
        )
        writer = SqlAlchemyRulePublicationTargetWriter(self.engine)
        original = NacosRulePublicationTarget(
            "binding-write",
            "source-write",
            "namespace-a",
            "GROUP_A",
            "flow-a.json",
        )
        first = await writer.write_rule_publication_target(
            original,
            source_revision="source-rev-1",
            expected_revision=None,
            now=_NOW,
        )
        self.assertEqual(first.source_revision, "source-rev-1")

        replacement = NacosRulePublicationTarget(
            "binding-write",
            "source-write",
            "namespace-a",
            "GROUP_A",
            "flow-b.json",
        )
        second = await writer.write_rule_publication_target(
            replacement,
            source_revision="source-rev-1",
            expected_revision=first.revision,
            now=_NOW,
        )
        self.assertNotEqual(second.revision, first.revision)
        self.assertEqual(second.target, replacement)
        self.assertEqual(
            await SqlAlchemyRulePublicationTargetReader(
                self.engine
            ).read_rule_publication_target("binding-write"),
            second,
        )

    async def test_target_writer_rejects_stale_mapping_or_source_revision(self) -> None:
        await self._seed_registered_source(
            source_id="source-write",
            revision="source-current",
            provider=ConfigurationSourceProvider.NACOS,
        )
        writer = SqlAlchemyRulePublicationTargetWriter(self.engine)
        target = NacosRulePublicationTarget(
            "binding-write",
            "source-write",
            "namespace-a",
            "GROUP_A",
            "flow-a.json",
        )
        with self.assertRaises(RulePublicationTargetConflict):
            await writer.write_rule_publication_target(
                target,
                source_revision="source-old",
                expected_revision=None,
                now=_NOW,
            )

        first = await writer.write_rule_publication_target(
            target,
            source_revision="source-current",
            expected_revision=None,
            now=_NOW,
        )
        with self.assertRaises(RulePublicationTargetConflict):
            await writer.write_rule_publication_target(
                target,
                source_revision="source-current",
                expected_revision="stale-mapping-revision",
                now=_NOW,
            )
        async with self.engine.connect() as connection:
            stored = await connection.scalar(
                select(RulePublicationTargetRecord.target_revision).where(
                    RulePublicationTargetRecord.binding_id == target.binding_id
                )
            )
        self.assertEqual(stored, first.revision)

    async def test_target_writer_rejects_provider_mismatch(self) -> None:
        await self._seed_registered_source(
            source_id="source-write",
            revision="source-rev-1",
            provider=ConfigurationSourceProvider.NACOS,
        )
        writer = SqlAlchemyRulePublicationTargetWriter(self.engine)
        target = ConsulRulePublicationTarget(
            "binding-write", "source-write", "sentinel/rules/flow.json"
        )
        with self.assertRaises(RulePublicationTargetConflict):
            await writer.write_rule_publication_target(
                target,
                source_revision="source-rev-1",
                expected_revision=None,
                now=_NOW,
            )

    async def _seed_registered_source(
        self,
        *,
        source_id: str,
        revision: str,
        provider: ConfigurationSourceProvider,
    ) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="target-owner",
                    username="target-owner",
                    username_key="t" * 64,
                    password_hash="$argon2id$synthetic-hash",
                    role_id="admin",
                    status="active",
                    built_in=True,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await connection.execute(
                insert(RegisteredConfigurationSourceRecord).values(
                    source_id=source_id,
                    revision=revision,
                    name="test source",
                    endpoint="https://config.example.test",
                    provider=provider.value,
                    location="default",
                    authentication_mode="none",
                    credential_configured=False,
                    credential_cipher_format=None,
                    credential_key_id=None,
                    credential_payload=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                    updated_by_account_id="target-owner",
                )
            )
