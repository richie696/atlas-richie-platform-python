"""SQL authority tests for source-backed, last-known-good rule catalog reads."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.refresh_rule_catalog import (
    RefreshRuleCatalog,
)
from atlas_richie.sentinel_console.application.rule_snapshot_ports import (
    RuleSetSnapshotAuthorityUnavailable,
    RuleSetSnapshotTargetMissing,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleKind
from atlas_richie.sentinel_console.domain.rule_catalog import (
    RuleBindingObservedState,
    RuleBindingStatesQuery,
    RuleCatalogQuery,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.domain.rule_snapshots import (
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
    RuleRecord,
    RuleSetSnapshot,
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
from atlas_richie.sentinel_console.infrastructure.persistence.rule_catalog_projection import (
    SqlAlchemyRuleCatalogProjection,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_state_reader import (
    SqlAlchemyRuleBindingStateReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_target_mapping import (
    target_body,
)

_NOW = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)


class RuleCatalogProjectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        await self._seed_binding()
        self.projection = SqlAlchemyRuleCatalogProjection(
            self.engine, clock=lambda: _NOW
        )
        self.binding = await SqlAlchemyRuleBindingDirectoryReader(
            self.engine
        ).read_rule_binding("binding-a")
        assert self.binding is not None

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_unread_is_partial_but_confirmed_empty_array_is_complete_zero(self) -> None:
        query = RuleCatalogQuery("prod", None, None, "", 1, 20)

        binding_state_reader = SqlAlchemyRuleBindingStateReader(
            self.engine, clock=lambda: _NOW
        )
        states_query = RuleBindingStatesQuery("prod", None, None, 1, 20)
        unread_binding = await binding_state_reader.read_binding_states(states_query)
        self.assertEqual(unread_binding.total, 1)
        self.assertEqual(unread_binding.items[0].state, RuleBindingObservedState.NOT_READ)

        unread = await self.projection.read_catalog(query)
        self.assertEqual(unread.coverage.value, "partial")
        self.assertIsNone(unread.total)
        self.assertEqual(unread.bindings_not_read, 1)
        self.assertEqual(unread.issues[0].reason.value, "not_read")

        empty = RuleSetSnapshot(
            self.binding,
            None,
            "sha256:empty",
            "provider-revision-1",
            _NOW,
            (),
        )
        await self.projection.record_success(empty, _NOW)

        confirmed = await self.projection.read_catalog(query)
        self.assertEqual(confirmed.coverage.value, "complete")
        self.assertEqual(confirmed.total, 0)
        self.assertEqual(confirmed.bindings_current, 1)
        self.assertEqual(confirmed.items, ())
        self.assertEqual(confirmed.issues, ())

        empty_binding = await binding_state_reader.read_binding_states(states_query)
        self.assertEqual(
            empty_binding.items[0].state, RuleBindingObservedState.CONFIGURED_EMPTY
        )
        self.assertEqual(empty_binding.items[0].rule_count, 0)
        self.assertEqual(empty_binding.items[0].source_revision, "provider-revision-1")

    async def test_failure_retains_last_successful_rule_and_makes_total_unknown(self) -> None:
        snapshot = self._snapshot("POST /api/orders", "rule-a", 25)
        await self.projection.record_success(snapshot, _NOW)
        await self.projection.record_failure(
            self.binding, "source_unavailable", _NOW + timedelta(seconds=1)
        )

        page = await self.projection.read_catalog(
            RuleCatalogQuery("prod", None, RuleKind.FLOW, "orders", 1, 20)
        )
        self.assertEqual(page.coverage.value, "partial")
        self.assertIsNone(page.total)
        self.assertEqual(len(page.items), 1)
        self.assertEqual(page.items[0].record.id, "rule-a")
        self.assertEqual(page.items[0].freshness.value, "stale")
        self.assertTrue(page.issues[0].stale)
        self.assertEqual(page.issues[0].reason.value, "source_unavailable")

        binding_state = await SqlAlchemyRuleBindingStateReader(
            self.engine, clock=lambda: _NOW + timedelta(seconds=1)
        ).read_binding_states(RuleBindingStatesQuery("prod", "checkout", RuleKind.FLOW, 1, 20))
        self.assertEqual(
            binding_state.items[0].state, RuleBindingObservedState.SOURCE_UNAVAILABLE
        )
        self.assertEqual(binding_state.items[0].freshness.value, "stale")
        self.assertTrue(binding_state.items[0].has_last_known_good)

    async def test_search_and_page_are_applied_to_rule_rows_in_sql(self) -> None:
        snapshot = RuleSetSnapshot(
            self.binding,
            None,
            "sha256:two-rules",
            "provider-revision-1",
            _NOW,
            (
                RuleRecord(
                    "rule-a", self._flow("POST /api/orders", 25)
                ),
                RuleRecord(
                    "rule-b", self._flow("GET /api/health", 10)
                ),
            ),
        )
        await self.projection.record_success(snapshot, _NOW)

        page = await self.projection.read_catalog(
            RuleCatalogQuery("prod", "checkout", RuleKind.FLOW, "orders", 1, 1)
        )
        self.assertEqual(page.total, 1)
        self.assertEqual([item.record.id for item in page.items], ["rule-a"])

    async def test_refresh_reads_sources_and_preserves_last_known_good_on_failure(self) -> None:
        source = _SnapshotReader(self._snapshot("POST /api/orders", "rule-a", 25))
        refresher = RefreshRuleCatalog(
            self.projection, source, clock=lambda: _NOW + timedelta(seconds=1)
        )
        first = await refresher.execute("prod")
        self.assertEqual(first.bindings_attempted, 1)
        self.assertEqual(first.coverage.value, "complete")

        source.error = RuleSetSnapshotAuthorityUnavailable("private provider detail")
        second = await refresher.execute("prod")
        self.assertEqual(second.coverage.value, "partial")
        self.assertEqual(second.bindings_stale, 1)
        self.assertEqual(source.binding_ids, ["binding-a", "binding-a"])

        retained = await self.projection.read_catalog(
            RuleCatalogQuery("prod", None, None, "", 1, 20)
        )
        self.assertEqual([item.record.id for item in retained.items], ["rule-a"])
        self.assertEqual(retained.items[0].freshness.value, "stale")

        source.error = RuleSetSnapshotTargetMissing()
        await refresher.execute("prod")
        binding_state = await SqlAlchemyRuleBindingStateReader(
            self.engine, clock=lambda: _NOW + timedelta(seconds=2)
        ).read_binding_states(RuleBindingStatesQuery("prod", "checkout", RuleKind.FLOW, 1, 20))
        self.assertEqual(
            binding_state.items[0].state, RuleBindingObservedState.TARGET_MISSING
        )
        self.assertTrue(binding_state.items[0].has_last_known_good)
        self.assertEqual(binding_state.items[0].freshness.value, "stale")
        retained_after_missing = await self.projection.read_catalog(
            RuleCatalogQuery("prod", None, RuleKind.FLOW, "orders", 1, 20)
        )
        self.assertEqual([item.record.id for item in retained_after_missing.items], ["rule-a"])

    async def test_invalid_and_unsupported_profile_failures_are_distinct_states(self) -> None:
        await self.projection.record_success(
            self._snapshot("POST /api/orders", "rule-a", 25), _NOW
        )
        reader = SqlAlchemyRuleBindingStateReader(self.engine, clock=lambda: _NOW)
        query = RuleBindingStatesQuery("prod", "checkout", RuleKind.FLOW, 1, 20)
        for error_code, expected in (
            ("content_invalid", RuleBindingObservedState.CONTENT_INVALID),
            ("unsupported_profile", RuleBindingObservedState.UNSUPPORTED_PROFILE),
        ):
            await self.projection.record_failure(
                self.binding, error_code, _NOW + timedelta(seconds=1)
            )
            page = await reader.read_binding_states(query)
            self.assertEqual(page.items[0].state, expected)
            self.assertTrue(page.items[0].has_last_known_good)
            self.assertEqual(page.items[0].rule_count, None)
            self.assertEqual(page.items[0].freshness.value, "stale")

    def _snapshot(self, resource: str, rule_id: str, threshold: int) -> RuleSetSnapshot:
        return RuleSetSnapshot(
            self.binding,
            None,
            "sha256:one-rule",
            "provider-revision-1",
            _NOW,
            (RuleRecord(rule_id, self._flow(resource, threshold)),),
        )

    @staticmethod
    def _flow(resource: str, threshold: int) -> FlowRuleValue:
        return FlowRuleValue(
            resource=resource,
            limit_app="default",
            grade=FlowGrade.QPS,
            count=threshold,
            strategy=FlowStrategy.DIRECT,
            control_behavior=FlowControlBehavior.REJECT,
            cluster_mode=False,
        )

    async def _seed_binding(self) -> None:
        target = NacosRulePublicationTarget(
            "binding-a", "source-a", "prod-namespace", "DEFAULT_GROUP", "rules.json"
        )
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
            await connection.execute(
                insert(RuleBindingRecord).values(
                    binding_id=target.binding_id,
                    environment_id="prod",
                    app_id="checkout",
                    kind=RuleKind.FLOW.value,
                    profile="sentinel-flow-v1",
                    source_id=target.source_id,
                    location="nacos://prod-namespace/DEFAULT_GROUP/rules.json",
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
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


class _SnapshotReader:
    def __init__(self, snapshot: RuleSetSnapshot) -> None:
        self.snapshot = snapshot
        self.error: Exception | None = None
        self.binding_ids: list[str] = []

    async def read_rule_set_snapshot(self, binding_id: str) -> RuleSetSnapshot:
        self.binding_ids.append(binding_id)
        if self.error is not None:
            raise self.error
        return self.snapshot


if __name__ == "__main__":
    unittest.main()
