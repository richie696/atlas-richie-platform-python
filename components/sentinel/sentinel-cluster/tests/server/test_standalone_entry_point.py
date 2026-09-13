"""StandaloneTokenServer / CLI 单测 (M6.3.5).

4 个单测覆盖: CLI 参数 / config JSON 解析 / 默认值 / 启动 fail-fast.
"""

from __future__ import annotations

import argparse
import json

import pytest

from atlas_richie.contracts.cluster.v1 import (
    DEFAULT_LEASE_TTL_NS,
    ENVELOPE_MAX_SIZE_BYTES,
)
from atlas_richie.sentinel.ports.token import ClusterFailurePolicy

from atlas_richie.sentinel_cluster.config import (
    ClusterTokenConfig,
    ClusterTokenMode,
    ResourceConfig,
)
from atlas_richie.sentinel_cluster.errors import ClusterConfigError
from atlas_richie.sentinel_cluster.server.standalone import (
    StandaloneTokenServer,
    _build_arg_parser,
    _build_config_from_args,
)

pytestmark = pytest.mark.unit


def _ns(**kwargs) -> argparse.Namespace:
    """构造 argparse Namespace with defaults."""
    base = {
        "bind": "127.0.0.1:0",
        "config": "",
        "auth_secret": "test-secret",
        "shutdown_timeout": 5.0,
        "lease_ttl_ns": DEFAULT_LEASE_TTL_NS,
        "max_payload_bytes": ENVELOPE_MAX_SIZE_BYTES,
        "max_inflight": 1024,
        "log_level": "INFO",
    }
    base.update(kwargs)
    return argparse.Namespace(**base)


class TestStandaloneEntryPoint:
    """Standalone CLI / StandaloneTokenServer 启动行为."""

    def test_cli_argparse_defaults_and_overrides(self) -> None:
        # CLI 解析: 默认 + override
        parser = _build_arg_parser()
        ns_default = parser.parse_args(["--auth-secret", "s"])
        assert ns_default.bind == "0.0.0.0:8765"
        assert ns_default.shutdown_timeout == 5.0
        # override
        ns_override = parser.parse_args(
            [
                "--bind", "127.0.0.1:9999",
                "--auth-secret", "mysecret",
                "--shutdown-timeout", "10.0",
            ]
        )
        assert ns_override.bind == "127.0.0.1:9999"
        assert ns_override.auth_secret == "mysecret"
        assert ns_override.shutdown_timeout == 10.0

    def test_config_json_loads_resources_and_policy(self, tmp_path) -> None:
        # config JSON 解析: resources + failure_policy
        config_obj = {
            "cluster_token_mode": "standalone",
            "bind_address": "127.0.0.1:8888",
            "resources": [
                {"name": "/r1", "max_permits": 5.0},
                {"name": "/r2", "max_permits": 3.0},
            ],
            "failure_policy_per_resource": {
                "/r1": "fail_closed",
                "/r2": "fail_open",
            },
            "lease_ttl_ns": 60_000_000_000,
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_obj))
        ns = _ns(config=str(config_file), auth_secret="s")
        cfg = _build_config_from_args(ns)
        assert cfg.bind_address == "127.0.0.1:8888"
        assert len(cfg.resources) == 2
        assert cfg.failure_policy_per_resource["/r1"] == ClusterFailurePolicy.FAIL_CLOSED
        assert cfg.failure_policy_per_resource["/r2"] == ClusterFailurePolicy.FAIL_OPEN
        assert cfg.lease_ttl_ns == 60_000_000_000
        # auth_secret 必须从 CLI 显式传入 (不在 JSON)
        assert cfg.auth_secret == "s"

    def test_missing_auth_secret_fails_fast(self) -> None:
        # 启动 fail-fast: 缺 auth_secret
        ns = _ns(auth_secret="")
        with pytest.raises(ClusterConfigError, match="auth_secret is required"):
            _build_config_from_args(ns)

    @pytest.mark.asyncio
    async def test_construct_rejects_non_standalone_mode(self) -> None:
        # 启动 fail-fast: mode 错 (embedded 传给 StandaloneTokenServer)
        cfg = ClusterTokenConfig(
            cluster_token_mode=ClusterTokenMode.EMBEDDED,
            bind_address="",
            auth_secret="s",
            resources=(ResourceConfig(name="/r1", max_permits=5.0),),
            failure_policy_per_resource={"/r1": ClusterFailurePolicy.FAIL_CLOSED},
        )
        with pytest.raises(ClusterConfigError, match="requires mode=STANDALONE"):
            StandaloneTokenServer(cfg)
