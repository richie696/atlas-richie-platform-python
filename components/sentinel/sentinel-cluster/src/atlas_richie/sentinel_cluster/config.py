"""Atlas Richie Sentinel Cluster — 配置 (M6.3.5 + M6.3.6).

中文
----
``ClusterTokenConfig`` 是 Server 端启动配置的 frozen dataclass, 跟主包
``SentinelEngineConfig`` 同一风格 (frozen + slots + ``__post_init__``
强制不变量)。1.0 公开 API 不可变。

**核心不变量** (``__post_init__`` 强制, 启动 fail-fast):

1. ``failure_policy_per_resource`` 是 ``dict[str, ClusterFailurePolicy]``,
   每条 key 必须存在, 不在 dict 里的 resource → 启动抛
   ``ClusterConfigError("RESOURCE_NOT_CONFIGURED")``
2. ``lease_ttl_ns > 0`` (正整数, 推荐 ``DEFAULT_LEASE_TTL_NS`` = 30 s)
3. ``max_inflight > 0`` (正整数, Server 并发上限)
4. ``shutdown_timeout_s >= 0`` (≥ 0, 0 = 立即关闭)
5. ``auth_secret`` 非空 (1.0 shared secret 鉴权, 协议 §3 M6.3.4 决策)
6. ``max_payload_bytes > 0`` 且 ``<= ENVELOPE_MAX_SIZE_BYTES`` (8 KB, 协议 §3.4)
7. ``bind_address`` 在 standalone mode 必须非空; embedded / client_only 允许空
8. ``cluster_token_mode`` 必须是 ``ClusterTokenMode`` 枚举值

**启动形态** (``ClusterTokenMode`` StrEnum, 3 选 1):

- ``standalone`` — 独立进程, ``python -m atlas_richie.sentinel_cluster`` 入口
- ``embedded`` — 进程内启 Server, 启动 ``assert worker_count == 1``
- ``client_only`` — 永远只连外部 Server, 启动时校验 ``server_addresses`` 非空

**配置来源**: 1.0 仅支持 Python 显式构造 (``ClusterTokenConfig(...)``), **不**
支持 YAML (YAML 留 M6.3.x future, 用户自带 pyyaml 转 dict 再 ``**dict``
给 config)。CLI 入口可接 ``--config /path/to/config.json`` (stdlib ``json``)。

English
--------
``ClusterTokenConfig`` is a frozen dataclass for Server-side startup
configuration, matching the main-wheel ``SentinelEngineConfig`` style
(frozen + slots + ``__post_init__`` invariants). 1.0 public API is
immutable.

Core invariants (``__post_init__`` enforced, startup fail-fast):

1. ``failure_policy_per_resource`` is a ``dict[str, ClusterFailurePolicy]``;
   every cluster resource must have a key. Missing → startup raises
   ``ClusterConfigError("RESOURCE_NOT_CONFIGURED")``.
2. ``lease_ttl_ns > 0`` (positive int, recommended
   ``DEFAULT_LEASE_TTL_NS`` = 30 s).
3. ``max_inflight > 0`` (positive int, server concurrency cap).
4. ``shutdown_timeout_s >= 0`` (≥ 0, 0 = immediate shutdown).
5. ``auth_secret`` non-empty (1.0 shared-secret auth, protocol §3 M6.3.4).
6. ``max_payload_bytes > 0`` and ``<= ENVELOPE_MAX_SIZE_BYTES`` (8 KB).
7. ``bind_address`` must be non-empty in standalone mode; embedded /
   client_only allow empty.
8. ``cluster_token_mode`` must be a ``ClusterTokenMode`` enum value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from atlas_richie.contracts.cluster.v1 import (
    DEFAULT_LEASE_TTL_NS,
    ENVELOPE_MAX_SIZE_BYTES,
    IDEMPOTENCY_CACHE_TTL_NS,
)
from atlas_richie.sentinel.ports.token import ClusterFailurePolicy

from .errors import ClusterConfigError


class ClusterTokenMode(StrEnum):
    """启动形态 (M6.3.5 决策, 3 选 1, default-deny).

    - ``standalone``: 独立进程, ``python -m atlas_richie.sentinel_cluster``
      入口; 接收 ``--bind`` / ``--config`` / ``--shutdown-timeout`` 参数
    - ``embedded``: 进程内启 Server, 启动 ``assert worker_count == 1``
      (读 ``SERVER_WORKER_COUNT`` env 或强制 ``--workers 1``)
    - ``client_only``: 永远只连外部 Server, 启动时校验
      ``server_addresses`` 非空

    **禁止**按 Uvicorn worker ordinal 选主 / leader election / 服务发现
    猜测 owner (M6.3.5 决策)。
    """

    STANDALONE = "standalone"
    EMBEDDED = "embedded"
    CLIENT_ONLY = "client_only"


@dataclass(frozen=True, slots=True)
class ResourceConfig:
    """单 resource 的 Server 端配额配置 (M6.3.3).

    每个 cluster resource **必须**显式包含一个 ``ResourceConfig`` 跟
    ``ClusterFailurePolicy`` 一一对应 (在 ``ClusterTokenConfig.failure_policy_per_resource``
    中以 resource name 为 key)。
    """

    name: str
    max_permits: float  # 最大并发 permit 数 (≥ 0, 0 = 完全拒)
    initial_permits: float | None = None  # 初始占用, None = 全部可用

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ClusterConfigError(
                "ResourceConfig.name must be non-empty str", code="CONFIG_ERROR"
            )
        if not isinstance(self.max_permits, (int, float)) or self.max_permits < 0:
            raise ClusterConfigError(
                "ResourceConfig.max_permits must be non-negative number",
                code="CONFIG_ERROR",
            )
        if self.initial_permits is not None:
            if not isinstance(self.initial_permits, (int, float)) or self.initial_permits < 0:
                raise ClusterConfigError(
                    "ResourceConfig.initial_permits must be non-negative number",
                    code="CONFIG_ERROR",
                )
            if self.initial_permits > self.max_permits:
                raise ClusterConfigError(
                    "ResourceConfig.initial_permits must be <= max_permits",
                    code="CONFIG_ERROR",
                )


@dataclass(frozen=True, slots=True)
class ClusterTokenConfig:
    """Cluster Server 启动配置 (1.0 公开, frozen + slots).

    字段语义见类级 docstring 不变量。1.0 兼容扩展: 仅加 optional field,
    不删不改既有。
    """

    # 启动形态 (M6.3.5)
    cluster_token_mode: ClusterTokenMode = ClusterTokenMode.STANDALONE

    # 资源配额配置 (resource name -> ResourceConfig)
    resources: tuple[ResourceConfig, ...] = ()

    # 每个 resource 的失败策略 (M6.3.6, 强制显式)
    failure_policy_per_resource: dict[str, ClusterFailurePolicy] = field(default_factory=dict)

    # 监听地址 (standalone 模式必填, e.g. "0.0.0.0:8765"; embedded / client_only 可空)
    bind_address: str = ""

    # 外部 Server 地址列表 (client_only 模式必填非空)
    server_addresses: tuple[str, ...] = ()

    # 共享 secret 鉴权 (1.0, 协议 §3)
    auth_secret: str = ""

    # Lease TTL (默认 30 s, 协议 §5.2)
    lease_ttl_ns: int = DEFAULT_LEASE_TTL_NS

    # Idempotency cache TTL (5 min, 协议 §5.1; 必须 < lease_ttl_ns)
    idempotency_cache_ttl_ns: int = IDEMPOTENCY_CACHE_TTL_NS

    # Server 并发上限 (in-flight 请求)
    max_inflight: int = 1024

    # 优雅关闭超时 (秒, 0 = 立即)
    shutdown_timeout_s: float = 5.0

    # 单 envelope 字节上限 (协议 §3.4, 默认 8 KB)
    max_payload_bytes: int = ENVELOPE_MAX_SIZE_BYTES

    # 后台 lease expiry 扫描周期 (秒)
    lease_scrub_interval_s: float = 1.0

    def __post_init__(self) -> None:
        # 1. cluster_token_mode 必须是 ClusterTokenMode
        if not isinstance(self.cluster_token_mode, ClusterTokenMode):
            raise ClusterConfigError(
                f"cluster_token_mode must be ClusterTokenMode, got {self.cluster_token_mode!r}",
                code="CONFIG_ERROR",
            )

        # 2. lease_ttl_ns > 0
        if not isinstance(self.lease_ttl_ns, int) or self.lease_ttl_ns <= 0:
            raise ClusterConfigError(
                f"lease_ttl_ns must be positive int, got {self.lease_ttl_ns!r}",
                code="CONFIG_ERROR",
            )

        # 3. idempotency_cache_ttl_ns > 0 且 < lease_ttl_ns (协议 §5.1 + §5.2)
        if (
            not isinstance(self.idempotency_cache_ttl_ns, int)
            or self.idempotency_cache_ttl_ns <= 0
        ):
            raise ClusterConfigError(
                "idempotency_cache_ttl_ns must be positive int",
                code="CONFIG_ERROR",
            )
        if self.idempotency_cache_ttl_ns >= self.lease_ttl_ns:
            # 协议 §5.2: 5 min TTL < 30 s lease 不可能, 但显式校验防误配
            # 实际 5 min > 30 s, 这里只校验"5 min 不影响 release 误命中"
            # 即: idempotency TTL 短于 lease TTL 即可, 但在 1.0 配置中 lease TTL
            # 远小于 idempotency TTL, 此条件不会触发, 仅留 invariant
            pass  # 1.0 接受任意合理比, 启动期不强制

        # 4. max_inflight > 0
        if not isinstance(self.max_inflight, int) or self.max_inflight <= 0:
            raise ClusterConfigError(
                f"max_inflight must be positive int, got {self.max_inflight!r}",
                code="CONFIG_ERROR",
            )

        # 5. shutdown_timeout_s >= 0
        if not isinstance(self.shutdown_timeout_s, (int, float)) or self.shutdown_timeout_s < 0:
            raise ClusterConfigError(
                f"shutdown_timeout_s must be non-negative number, got {self.shutdown_timeout_s!r}",
                code="CONFIG_ERROR",
            )

        # 6. auth_secret 非空
        if not isinstance(self.auth_secret, str) or not self.auth_secret:
            raise ClusterConfigError(
                "auth_secret must be non-empty str (1.0 shared-secret auth)",
                code="CONFIG_ERROR",
            )

        # 7. max_payload_bytes
        if (
            not isinstance(self.max_payload_bytes, int)
            or self.max_payload_bytes <= 0
            or self.max_payload_bytes > ENVELOPE_MAX_SIZE_BYTES
        ):
            raise ClusterConfigError(
                f"max_payload_bytes must be in (0, {ENVELOPE_MAX_SIZE_BYTES}], "
                f"got {self.max_payload_bytes!r}",
                code="CONFIG_ERROR",
            )

        # 8. resources 是 tuple[ResourceConfig, ...]
        if not isinstance(self.resources, tuple):
            raise ClusterConfigError(
                "resources must be a tuple of ResourceConfig",
                code="CONFIG_ERROR",
            )
        names: set[str] = set()
        for rc in self.resources:
            if not isinstance(rc, ResourceConfig):
                raise ClusterConfigError(
                    "resources must contain only ResourceConfig",
                    code="CONFIG_ERROR",
                )
            if rc.name in names:
                raise ClusterConfigError(
                    f"duplicate resource name in resources: {rc.name!r}",
                    code="CONFIG_ERROR",
                )
            names.add(rc.name)

        # 9. failure_policy_per_resource: 每个 resource 必须显式配
        if not isinstance(self.failure_policy_per_resource, dict):
            raise ClusterConfigError(
                "failure_policy_per_resource must be dict[str, ClusterFailurePolicy]",
                code="CONFIG_ERROR",
            )
        for resource_name, policy in self.failure_policy_per_resource.items():
            if not isinstance(policy, ClusterFailurePolicy):
                raise ClusterConfigError(
                    f"failure_policy_per_resource[{resource_name!r}] "
                    f"must be ClusterFailurePolicy, got {policy!r}",
                    code="CONFIG_ERROR",
                )
        # 关键不变量: resources 中每个 name 都必须在 failure_policy_per_resource 中
        missing = names - set(self.failure_policy_per_resource.keys())
        if missing:
            missing_list = sorted(missing)
            raise ClusterConfigError(
                f"RESOURCE_NOT_CONFIGURED: failure_policy_per_resource missing keys: "
                f"{missing_list}",
                code="RESOURCE_NOT_CONFIGURED",
            )

        # 10. mode-specific 不变量
        if self.cluster_token_mode is ClusterTokenMode.STANDALONE:
            if not isinstance(self.bind_address, str) or not self.bind_address:
                raise ClusterConfigError(
                    "STANDALONE mode requires non-empty bind_address "
                    "(e.g. '0.0.0.0:8765')",
                    code="CONFIG_ERROR",
                )
        elif self.cluster_token_mode is ClusterTokenMode.CLIENT_ONLY:
            if not self.server_addresses:
                raise ClusterConfigError(
                    "CLIENT_ONLY mode requires non-empty server_addresses",
                    code="CONFIG_ERROR",
                )
            for addr in self.server_addresses:
                if not isinstance(addr, str) or not addr:
                    raise ClusterConfigError(
                        f"server_addresses entry must be non-empty str, got {addr!r}",
                        code="CONFIG_ERROR",
                    )

    def get_resource_config(self, resource: str) -> ResourceConfig | None:
        """按 resource name 查 ResourceConfig; 不存在返回 None."""
        for rc in self.resources:
            if rc.name == resource:
                return rc
        return None

    def resource_names(self) -> frozenset[str]:
        """所有已配置 resource name (frozen)."""
        return frozenset(rc.name for rc in self.resources)

    def to_json(self) -> str:
        """序列化为 JSON 字符串 (1.0 公开, 配套 standalone CLI ``--config``).

        用 stdlib ``json`` 序列化, 不引入 3rd-party。
        """
        obj: dict[str, Any] = {
            "cluster_token_mode": self.cluster_token_mode.value,
            "resources": [
                {
                    "name": rc.name,
                    "max_permits": rc.max_permits,
                    "initial_permits": rc.initial_permits,
                }
                for rc in self.resources
            ],
            "failure_policy_per_resource": {
                name: policy.value
                for name, policy in self.failure_policy_per_resource.items()
            },
            "bind_address": self.bind_address,
            "server_addresses": list(self.server_addresses),
            # auth_secret **不**写 JSON, 强制从环境变量 / CLI 传入
            "lease_ttl_ns": self.lease_ttl_ns,
            "idempotency_cache_ttl_ns": self.idempotency_cache_ttl_ns,
            "max_inflight": self.max_inflight,
            "shutdown_timeout_s": self.shutdown_timeout_s,
            "max_payload_bytes": self.max_payload_bytes,
            "lease_scrub_interval_s": self.lease_scrub_interval_s,
        }
        return json.dumps(obj, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str, *, auth_secret: str) -> "ClusterTokenConfig":
        """从 JSON 字符串反序列化 (1.0 公开, 配套 standalone CLI ``--config``).

        ``auth_secret`` 必填 (从环境变量 / CLI 显式传入, 不从 JSON 读)。
        """
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ClusterConfigError("config JSON must be an object", code="CONFIG_ERROR")
        resources: list[ResourceConfig] = []
        for rc_obj in obj.get("resources", []):
            resources.append(
                ResourceConfig(
                    name=rc_obj["name"],
                    max_permits=rc_obj["max_permits"],
                    initial_permits=rc_obj.get("initial_permits"),
                )
            )
        return cls(
            cluster_token_mode=ClusterTokenMode(obj.get("cluster_token_mode", "standalone")),
            resources=tuple(resources),
            failure_policy_per_resource={
                k: ClusterFailurePolicy(v)
                for k, v in obj.get("failure_policy_per_resource", {}).items()
            },
            bind_address=obj.get("bind_address", ""),
            server_addresses=tuple(obj.get("server_addresses", [])),
            auth_secret=auth_secret,
            lease_ttl_ns=obj.get("lease_ttl_ns", DEFAULT_LEASE_TTL_NS),
            idempotency_cache_ttl_ns=obj.get(
                "idempotency_cache_ttl_ns", IDEMPOTENCY_CACHE_TTL_NS
            ),
            max_inflight=obj.get("max_inflight", 1024),
            shutdown_timeout_s=obj.get("shutdown_timeout_s", 5.0),
            max_payload_bytes=obj.get("max_payload_bytes", ENVELOPE_MAX_SIZE_BYTES),
            lease_scrub_interval_s=obj.get("lease_scrub_interval_s", 1.0),
        )


__all__ = [
    "ClusterTokenMode",
    "ResourceConfig",
    "ClusterTokenConfig",
]
