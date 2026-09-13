"""`NacosRuleSourceConfig` frozen dataclass + 值对象 (M6.1.2)。

中文
----
**PLANNING M6.1.2 硬约束**:
- 不可变 frozen dataclass;配置字段、状态、错误使用 Enum / 值对象
- **不**向调用方泄漏 SDK client 或 callback 类型
- 公开 API 锁定后**不**允许扩展自动生成配置项的便利 API (default-deny 收窄 5 类)

设计要点:

- 4 个公开类型: ``NacosAuth`` / ``NacosTLS`` / ``NacosSourceState`` (StrEnum) /
  ``NacosSourceError`` (StrEnum) / ``NacosRuleSourceConfig`` (frozen dataclass)
- ``NacosAuth`` / ``NacosTLS`` 内部字段 (password / cert / key) 在 ``__repr__``
  中**必须**脱敏 (M6.1.5 脱敏要求前置到 M6.1.2)
- ``__post_init__`` 校验: source_id 非空, server_addresses 非空, namespace
  非空, group 非空, data_id_prefix 非空, 超时与退避 > 0 且 reconnect_max
  >= reconnect_initial
- 5 个 rule data-id 约定由 ``data_id_for(rule_type)`` 方法按
  ``{data_id_prefix}-{flow|degrade|param_flow|system|authority}-rules.json``
  生成 (PLANNING M6.1 的 1:1 Java 约定)

English
--------
``NacosRuleSourceConfig`` frozen dataclass + value objects (M6.1.2).

**PLANNING M6.1.2 hard constraints**:
- Immutable frozen dataclass; config fields / states / errors via Enum / value objects
- **No** SDK client / callback type leaks to callers
- After public API freeze, **no** auto-generated convenience config (default-deny 5 类)
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import timedelta
from enum import StrEnum
from typing import Mapping  # noqa: F401  (used in docstring type annotations)


# ---------------------------------------------------------------------------
# Public value objects (公开值对象)

@dataclass(frozen=True, slots=True)
class NacosAuth:
    """Nacos 认证信息 (用户名 + 密码)。

    公开 API:**只**暴露 ``username`` 字段;``password`` 字段**不**进
    ``__repr__`` / ``str()`` / 日志 (M6.1.5 脱敏要求前置)。

    应用:
    - 等同 1:1 Java sentinel-datasource-nacos 的 username + password
    - Nacos 2.x 也支持 access token; 若启用, 把 token 作为 password 传 (SDK
      会自动处理); M6.1 阶段**不**引入单独的 token 字段
    """

    username: str
    password: str

    def __post_init__(self) -> None:
        # username 必填; password 必填 (Nacos auth 强制要求)
        if not self.username or not isinstance(self.username, str):
            raise ValueError("NacosAuth.username must be a non-empty str")
        if not isinstance(self.password, str) or not self.password:
            raise ValueError("NacosAuth.password must be a non-empty str")

    def __repr__(self) -> str:
        # 脱敏: password 不进 repr
        return f"NacosAuth(username={self.username!r}, password=<redacted>)"


@dataclass(frozen=True, slots=True)
class NacosTLS:
    """Nacos TLS / mTLS 配置。

    公开 API: 3 个证书字段 (CA 必填, cert / key 可选 mTLS) + verify 开关
    (默认 True, 与 Nacos SDK 默认一致)。所有 PEM 内容**不**进 ``__repr__`` /
    日志 (M6.1.5 脱敏要求前置)。
    """

    ca: str
    cert: str | None = None
    key: str | None = None
    verify: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.ca, str) or not self.ca:
            raise ValueError("NacosTLS.ca must be a non-empty str (PEM)")
        # mTLS: cert 和 key 必须同时给
        if (self.cert is None) != (self.key is None):
            raise ValueError("NacosTLS cert/key must both be set or both be None")

    def __repr__(self) -> str:
        # 脱敏: ca / cert / key PEM 内容不进 repr
        return (
            f"NacosTLS(ca=<redacted {len(self.ca)} bytes>,"
            f" cert={'<redacted>' if self.cert else 'None'},"
            f" key={'<redacted>' if self.key else 'None'},"
            f" verify={self.verify})"
        )


# ---------------------------------------------------------------------------
# State / Error enums (公开状态机 / 错误分类 — M6.1.4 落地)

class NacosSourceState(StrEnum):
    """NacosRuleSource 状态机 (operator observability 用)。

    状态迁移 (M6.1.3 生命周期 + M6.1.4 错误分类):

    - ``CONNECTING``: 启动后首次读取未完成 (M6.1.3)
    - ``READY``: 至少一次成功 publish 后 (M6.1.3)
    - ``STALE``: 长期无更新 / last-known-good 过期 (M6.1.4)
    - ``DISCONNECTED``: SDK 连接中断 (M6.1.4)
    - ``CLOSED``: aclose() 后 (M6.1.5)
    """

    CONNECTING = "connecting"
    READY = "ready"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    CLOSED = "closed"


class NacosSourceError(StrEnum):
    """错误分类 (M6.1.4 落地)。

    5 类错误对应不同的恢复策略 + 暴露给 operator 的 failure reason:

    - ``AUTH``: 鉴权失败 (用户名/密码错); **不**自动重试, 等人工干预
    - ``NOT_FOUND``: 配置 data_id 不存在; 视作 last-known-good 保留, 不算 fail
    - ``EMPTY``: 配置存在但为空; 视作"删除", 保留 last-known-good
    - ``DECODE``: JSON / schema / 业务校验失败; last-known-good 保留, 标记坏规则
    - ``NETWORK``: 网络中断 / 超时 / DNS 失败; 触发有界指数退避重连
    """

    AUTH = "auth"
    NOT_FOUND = "not_found"
    EMPTY = "empty"
    DECODE = "decode"
    NETWORK = "network"


# ---------------------------------------------------------------------------
# Top-level config (公开 immutable assembly DTO — 必填字段不兜底)

# 5 类 rule data-id 后缀 (PLANNING M6.1 的 1:1 Java 约定)
_RULE_TYPE_DATA_ID_SUFFIX: dict[str, str] = {
    "flow": "flow-rules.json",
    "degrade": "degrade-rules.json",
    "param_flow": "param-flow-rules.json",
    "system": "system-rules.json",
    "authority": "authority-rules.json",
}


@dataclass(frozen=True, slots=True)
class NacosRuleSourceConfig:
    """公开 immutable assembly DTO (PLANNING M6.1.2 硬约束)。

    字段分组:

    - **identity** (必填): ``source_id`` (Supervisor 写入 activation fact)
    - **endpoint** (必填): ``server_addresses`` (多节点, tuple 防泄漏 list),
      ``namespace``, ``group``
    - **rule binding** (必填): ``data_id_prefix`` (5 个 rule data-id 的
      公共前缀; 完整 data-id 由 ``data_id_for(rule_type)`` 生成)
    - **auth / TLS** (可选): ``auth`` (``NacosAuth | None``), ``tls``
      (``NacosTLS | None``)
    - **timing** (可选, 但有默认): ``connect_timeout`` (3s) / ``read_timeout``
      (10s) / ``reconnect_initial`` (1s) / ``reconnect_max`` (30s)

    **default-deny 收窄 5 类** (API delta v3 决策 5):

    - 所有权: ``auth`` / ``tls`` 不可 None-or-X 二选一; 显式声明
    - 权限: 证书 PEM 不进 ``__repr__`` / ``str()`` (M6.1.5 脱敏要求前置)
    - 故障策略: ``reconnect_max`` 必须 ``>= reconnect_initial`` (避免退避
      上限 < 起始值的退化情况)
    - 资源上限: 5 个 data_id 不可再扩展 (data_id_for 5 类固定)
    - 跨进程语义: ``source_id`` 必须配置时显式给 (不允许自动生成)

    校验 (``__post_init__``):

    - 必填字段: ``source_id`` / ``server_addresses`` / ``namespace`` /
      ``group`` / ``data_id_prefix`` 非空
    - 超时与退避: > 0; ``reconnect_max`` >= ``reconnect_initial``
    - 5 个 data_id 后缀 (mapping): rule type 必须 ∈ {flow, degrade,
      param_flow, system, authority}
    """

    # identity (必填)
    source_id: str
    # endpoint (必填)
    server_addresses: tuple[str, ...]
    namespace: str
    group: str
    # rule binding (必填)
    data_id_prefix: str
    # auth / TLS (可选)
    auth: NacosAuth | None = None
    tls: NacosTLS | None = None
    # timing (默认; 用户可调)
    connect_timeout: timedelta = field(default=timedelta(seconds=3))
    read_timeout: timedelta = field(default=timedelta(seconds=10))
    reconnect_initial: timedelta = field(default=timedelta(seconds=1))
    reconnect_max: timedelta = field(default=timedelta(seconds=30))

    def __post_init__(self) -> None:
        # identity 校验
        if not isinstance(self.source_id, str) or not self.source_id:
            raise ValueError(
                "NacosRuleSourceConfig.source_id must be a non-empty str"
            )
        # endpoint 校验
        if not isinstance(self.server_addresses, tuple) or not self.server_addresses:
            raise ValueError(
                "NacosRuleSourceConfig.server_addresses must be a non-empty tuple"
            )
        for addr in self.server_addresses:
            if not isinstance(addr, str) or not addr:
                raise ValueError(
                    f"NacosRuleSourceConfig.server_addresses contains invalid "
                    f"address: {addr!r}"
                )
        if not isinstance(self.namespace, str) or not self.namespace:
            raise ValueError(
                "NacosRuleSourceConfig.namespace must be a non-empty str"
            )
        if not isinstance(self.group, str) or not self.group:
            raise ValueError(
                "NacosRuleSourceConfig.group must be a non-empty str"
            )
        # rule binding 校验
        if not isinstance(self.data_id_prefix, str) or not self.data_id_prefix:
            raise ValueError(
                "NacosRuleSourceConfig.data_id_prefix must be a non-empty str"
            )
        # timing 校验
        for name, td in (
            ("connect_timeout", self.connect_timeout),
            ("read_timeout", self.read_timeout),
            ("reconnect_initial", self.reconnect_initial),
            ("reconnect_max", self.reconnect_max),
        ):
            if not isinstance(td, timedelta) or td.total_seconds() <= 0:
                raise ValueError(
                    f"NacosRuleSourceConfig.{name} must be a positive timedelta"
                )
        if self.reconnect_max < self.reconnect_initial:
            raise ValueError(
                "NacosRuleSourceConfig.reconnect_max must be >= reconnect_initial"
            )

    def data_id_for(self, rule_type: str) -> str:
        """按 PLANNING M6.1 约定生成完整 data_id。

        - ``flow`` → ``{data_id_prefix}-flow-rules.json``
        - ``degrade`` → ``{data_id_prefix}-degrade-rules.json``
        - ``param_flow`` → ``{data_id_prefix}-param-flow-rules.json``
        - ``system`` → ``{data_id_prefix}-system-rules.json``
        - ``authority`` → ``{data_id_prefix}-authority-rules.json``

        5 类固定; 不可扩展 (PLANNING 资源上限 default-deny)。
        """
        suffix = _RULE_TYPE_DATA_ID_SUFFIX.get(rule_type)
        if suffix is None:
            raise ValueError(
                f"NacosRuleSourceConfig.data_id_for: unknown rule_type "
                f"{rule_type!r}; must be one of {sorted(_RULE_TYPE_DATA_ID_SUFFIX)}"
            )
        return f"{self.data_id_prefix}-{suffix}"

    def __repr__(self) -> str:
        # 脱敏: server_addresses / namespace / group 不算敏感但保留; auth / tls
        # 自动通过其 __repr__ 脱敏; 端点 + 数据 ID 是公开信息
        return (
            f"NacosRuleSourceConfig(source_id={self.source_id!r},"
            f" server_addresses={self.server_addresses!r},"
            f" namespace={self.namespace!r},"
            f" group={self.group!r},"
            f" data_id_prefix={self.data_id_prefix!r},"
            f" auth={self.auth!r},"
            f" tls={self.tls!r},"
            f" connect_timeout={self.connect_timeout!s},"
            f" read_timeout={self.read_timeout!s},"
            f" reconnect_initial={self.reconnect_initial!s},"
            f" reconnect_max={self.reconnect_max!s})"
        )
