"""SQL authority tests for the Console's rule-binding metadata directory."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.rule_binding_ports import (
    RuleBindingAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_bindings import (
    RuleBindingQuery,
    RuleKind,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RulePublicationTargetRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_directory_reader import (
    SqlAlchemyRuleBindingDirectoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_target_mapping import (
    target_body,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_target_writer import (
    SqlAlchemyRulePublicationTargetWriter,
)

_NOW = datetime(2026, 10, 10, tzinfo=UTC)


class RuleBindingDirectoryReaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        await self._seed_account_and_source()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_filters_searches_and_paginates_exact_binding_metadata(self) -> None:
        await self._seed_binding("binding-a", "app-a", "flow-a.json")
        await self._seed_binding("binding-b", "app-b", "flow-b.json")
        await self._seed_binding("binding-c", "app-c", "flow-c.json")

        query = RuleBindingQuery(
            environment_id="prod",
            app_id=None,
            kind=RuleKind.FLOW,
            search="flow",
            page=2,
            page_size=1,
        )
        page = await SqlAlchemyRuleBindingDirectoryReader(self.engine).read_rule_bindings(
            query
        )

        self.assertEqual(page.query, query)
        self.assertEqual(page.total, 3)
        self.assertEqual([item.id for item in page.items], ["binding-b"])
        self.assertEqual(page.items[0].source_label, "operations-config")
        self.assertEqual(
            page.items[0].location,
            "nacos://prod-namespace/DEFAULT_GROUP/flow-b.json",
        )

    async def test_metadata_without_exact_target_fails_closed(self) -> None:
        await self._seed_binding_metadata("binding-orphan", "app-a", "nacos://x")

        query = RuleBindingQuery("prod", None, None, "", 1, 10)
        with self.assertRaises(RuleBindingAuthorityUnavailable):
            await SqlAlchemyRuleBindingDirectoryReader(self.engine).read_rule_bindings(
                query
            )

    async def test_target_must_match_metadata_source_and_location(self) -> None:
        await self._seed_binding_metadata("binding-mismatch", "app-a", "nacos://wrong")
        target = NacosRulePublicationTarget(
            "binding-mismatch",
            "source-other",
            "prod-namespace",
            "DEFAULT_GROUP",
            "flow.json",
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RulePublicationTargetRecord).values(
                    binding_id=target.binding_id,
                    source_id=target.source_id,
                    target_revision="target-revision",
                    source_revision="source-revision",
                    target_body=target_body(target),
                    updated_at=_NOW,
                )
            )

        query = RuleBindingQuery("prod", None, None, "", 1, 10)
        with self.assertRaises(RuleBindingAuthorityUnavailable):
            await SqlAlchemyRuleBindingDirectoryReader(self.engine).read_rule_bindings(
                query
            )

    async def test_target_change_keeps_binding_directory_location_in_sync(self) -> None:
        await self._seed_binding_metadata(
            "binding-updatable",
            "app-a",
            "nacos://prod-namespace/DEFAULT_GROUP/old.json",
        )
        target = NacosRulePublicationTarget(
            "binding-updatable",
            "source-a",
            "prod-namespace",
            "DEFAULT_GROUP",
            "new.json",
        )
        await SqlAlchemyRulePublicationTargetWriter(self.engine).write_rule_publication_target(
            target,
            source_revision="source-revision",
            expected_revision=None,
            now=_NOW,
        )

        binding = await SqlAlchemyRuleBindingDirectoryReader(
            self.engine
        ).read_rule_binding("binding-updatable")

        self.assertIsNotNone(binding)
        self.assertEqual(
            binding.location,
            "nacos://prod-namespace/DEFAULT_GROUP/new.json",
        )

    async def _seed_account_and_source(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="binding-owner",
                    username="binding-owner",
                    username_key="b" * 64,
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
                    source_id="source-a",
                    revision="source-revision",
                    name="operations-config",
                    endpoint="https://config.example.test",
                    provider=ConfigurationSourceProvider.NACOS.value,
                    location="default",
                    authentication_mode="none",
                    credential_configured=False,
                    credential_cipher_format=None,
                    credential_key_id=None,
                    credential_payload=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                    updated_by_account_id="binding-owner",
                )
            )

    async def _seed_binding_metadata(
        self, binding_id: str, app_id: str, location: str
    ) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RuleBindingRecord).values(
                    binding_id=binding_id,
                    environment_id="prod",
                    app_id=app_id,
                    kind=RuleKind.FLOW.value,
                    profile="sentinel-flow-v1",
                    source_id="source-a",
                    location=location,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )

    async def _seed_binding(
        self, binding_id: str, app_id: str, data_id: str
    ) -> None:
        target = NacosRulePublicationTarget(
            binding_id,
            "source-a",
            "prod-namespace",
            "DEFAULT_GROUP",
            data_id,
        )
        location = f"nacos://{target.namespace}/{target.group}/{target.data_id}"
        await self._seed_binding_metadata(binding_id, app_id, location)
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RulePublicationTargetRecord).values(
                    binding_id=binding_id,
                    source_id=target.source_id,
                    target_revision=f"revision-{binding_id}",
                    source_revision="source-revision",
                    target_body=target_body(target),
                    updated_at=_NOW,
                )
            )


if __name__ == "__main__":
    unittest.main()
