"""Ephemeral synthetic Console HTTP server for cross-process UI adapter tests."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime

import uvicorn
from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.read_rule_catalog import ReadRuleCatalog
from atlas_richie.sentinel_console.domain.rule_bindings import (
    RuleBinding,
    RuleKind,
)
from atlas_richie.sentinel_console.domain.rule_catalog import (
    RuleCatalogCoverage,
    RuleCatalogEntry,
    RuleCatalogFreshness,
    RuleCatalogPage,
    RuleCatalogQuery,
    RuleCatalogRefreshResult,
)
from atlas_richie.sentinel_console.domain.rule_snapshots import (
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
    RuleRecord,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_AS_OF = "2026-10-16T08:00:00+00:00"


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _SetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    async def read_active_session(self, session_digest: str) -> ActiveAccountSession:
        return ActiveAccountSession("live-test-account", "viewer", "view", "epoch-1")


class _SessionRevoker:
    async def revoke_current_session(self, session_digest: str) -> None:
        raise AssertionError(
            "The rule-catalog read integration must not revoke sessions"
        )


class _Projection:
    async def read_catalog(self, query: RuleCatalogQuery) -> RuleCatalogPage:
        timestamp = datetime.fromisoformat(_AS_OF)
        binding = RuleBinding(
            id="checkout-prod-flow",
            environment_id="prod",
            app_id="checkout",
            kind=RuleKind.FLOW,
            profile="sentinel-python-v1",
            source_id="nacos-prod",
            source_label="Integration Nacos",
            location="nacos://namespace/DEFAULT_GROUP/flow-rules.json",
        )
        rule = FlowRuleValue(
            resource="POST /checkout",
            limit_app="default",
            grade=FlowGrade.QPS,
            count=17,
            strategy=FlowStrategy.DIRECT,
            control_behavior=FlowControlBehavior.REJECT,
            cluster_mode=False,
        )
        return RuleCatalogPage(
            query=query,
            as_of=timestamp,
            coverage=RuleCatalogCoverage.COMPLETE,
            bindings_total=1,
            bindings_current=1,
            bindings_stale=0,
            bindings_not_read=0,
            total=1,
            has_more=False,
            items=(
                RuleCatalogEntry(
                    binding=binding,
                    record=RuleRecord("checkout-submit", rule),
                    checksum="integration-checksum-17",
                    source_revision="integration-revision-17",
                    version_id=None,
                    snapshot_as_of=timestamp,
                    last_attempt_at=timestamp,
                    freshness=RuleCatalogFreshness.CURRENT,
                ),
            ),
            issues=(),
        )


class _Refresher:
    async def execute(
        self, environment_id: str, app_id: str | None
    ) -> RuleCatalogRefreshResult:
        timestamp = datetime.fromisoformat(_AS_OF)
        return RuleCatalogRefreshResult(
            environment_id=environment_id,
            app_id=app_id,
            as_of=timestamp,
            coverage=RuleCatalogCoverage.COMPLETE,
            bindings_total=1,
            bindings_attempted=1,
            bindings_current=1,
            bindings_stale=0,
            bindings_not_read=0,
        )


async def _serve(port: int) -> None:
    app = build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_SetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=_SessionReader(),
        current_session_revoker=_SessionRevoker(),
        account_directory_reader=object(),
        allowed_browser_origins=frozenset({"http://localhost:5173"}),
        rule_catalog_reader=ReadRuleCatalog(_Projection()),
        rule_catalog_refresher=_Refresher(),
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
            server_header=False,
            date_header=False,
        )
    )
    task = asyncio.create_task(server.serve())
    while not server.started and not task.done():
        await asyncio.sleep(0.01)
    if task.done():
        task.result()
        raise RuntimeError("synthetic Console server exited before startup")
    assert server.servers and server.servers[0].sockets
    bound_port = server.servers[0].sockets[0].getsockname()[1]
    print(json.dumps({"ready": True, "port": bound_port}), flush=True)
    await task


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(_serve(args.port))


if __name__ == "__main__":
    main()
