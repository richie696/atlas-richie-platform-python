"""Nacos :class:`RuleSource` 实现 (M6.1.7 — SDK 3.2.0 + polling 架构)。

中文
----
**职责**: 把 :class:`NacosRuleSourceConfig` 配置 + Nacos 5 个 data-id
包装成主包 :class:`SnapshotRuleSource` Protocol。

**架构 (M6.1.7 改造, 替代 M6.1.0-1.6 push 路径)**:

- **SDK 升级**: ``nacos-sdk-python`` 0.1.16 → 3.2.0 (模块 ``v2.nacos``,
  async + gRPC)
- **长轮询 push 不可用**: SDK 3.2.0 gRPC listener 跟 Nacos 3.2.3 server
  协议 drift, 30 秒等待仍 0 events。改 polling 模式: 后台
  ``asyncio.create_task`` 每 ``poll_interval`` 秒拉一次 5 个 data_id,
  checksum 比对, 变化则 yield snapshot
- **SDK 端取消**: 不再调 ``add_listener`` / ``add_config_watcher``; 适配层
  只暴露 ``fetch_all`` + ``aclose`` 两个公开方法

**3 个子任务 (M6.1.0 时代命名沿用, 实质已重写)**:

- **M6.1.3 生命周期**: 启动 → 首次全量拉取 → 解码 → yield
  → 状态 ``READY`` → 启动 ``_poll_loop`` background task
  → 每次 tick: 重新拉 5 个 data_id → 跟上次 checksum 比对 → 变化 yield
- **M6.1.4 错误分类**: 5 类 (:class:`NacosSourceError`):
  AUTH / NOT_FOUND / EMPTY / DECODE / NETWORK, 不同恢复策略
- **M6.1.5 关闭管理**: ``aclose()`` 幂等, 取消 ``_poll_task``, 停 SDK 客户端

**不**做的事:

- **不** import 主包 C 层 ``_supervisor.*`` (C 层物理隔离)
- **不** 泄漏 nacos SDK 类型到公开 API
- **不** 在公开 API 暴露 push 路径的 callback type (``NacosCallbackParams``
  在 M6.1.7 中删除, 不在 ``__all__``)
- **不** 缓存凭据到 ``last_error_message`` (脱敏)
- **不** 在错误时 yield 新 snapshot (last-known-good 由 caller 侧
  Repository 保留)

English
--------
Nacos-backed implementation of :class:`SnapshotRuleSource` (M6.1.7).

Wraps :class:`NacosRuleSourceConfig` + 5 Nacos data-ids into the
main-package ``SnapshotRuleSource`` Protocol. Covers M6.1.3 polling
lifecycle, M6.1.4 5-way error classification, M6.1.5 idempotent aclose.

**M6.1.7 architecture (replaces M6.1.0-1.6 push path)**:

- ``nacos-sdk-python`` upgraded to 3.2.0 (``v2.nacos`` module, async + gRPC).
- Long-poll push is **not** used: SDK 3.2.0 gRPC listener is incompatible
  with Nacos 3.2.3 server (0 events / 30s). A background
  ``asyncio.create_task`` polls 5 data-ids every ``poll_interval`` seconds,
  compares checksums, yields a new :class:`RuleSnapshot` on change.
- SDK ``add_listener`` / ``add_config_watcher`` are **not** called. Adapter
  exposes only ``fetch_all`` and ``aclose``.

**Does not**: import main-package C-layer ``_supervisor.*``; leak
nacos SDK types into public API; cache credentials in
``last_error_message`` (redacted); yield a new snapshot on error
(last-known-good preserved by the caller's ``RuleRepository``).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any, AsyncIterator, Callable
from urllib.error import HTTPError, URLError

from atlas_richie.sentinel.rules.snapshot import RuleSnapshot, RuleVersion
from atlas_richie.sentinel.source.rule_source import SnapshotRuleSource

from .codec import NacosCodecError, decode_rule_snapshot
from .config import NacosRuleSourceConfig, NacosSourceError, NacosSourceState


_logger = logging.getLogger("atlas_richie.sentinel_source_nacos")


# ---------------------------------------------------------------------------
# 脱敏 (M6.1.5 前置要求, M6.1.7 沿用)
# ---------------------------------------------------------------------------

# 敏感字段名 / 关键字: 出现在消息中应替换为 "***"
_REDACT_KEYS: tuple[str, ...] = (
    "server_addresses",
    "server",
    "server-addr",
    "namespace",
    "username",
    "password",
    "accessKey",
    "secretKey",
    "token",
    "access_token",
    "ak=",
    "sk=",
    "cert",
    "key",
    "tls",
)

_REDACT_VALUE_PATTERNS: tuple[str, ...] = (
    # 匹配形如: 192.168.1.1:8848 / nacos-1:8848 / hostname:port
    r"[A-Za-z0-9_\-\.]+:\d{2,5}",
)


def _redact(message: str, config: NacosRuleSourceConfig) -> str:
    """脱敏 helper: 把 ``message`` 中的敏感字段替换为 ``***``。

    中文
    ----
    - 任何 ``<key>=<value>`` 或 ``<key>:<value>`` 形式, 命中敏感 key
      列表 → value 替换为 ``***``
    - 任何 ``host:port`` 形如 ``nacos-1:8848`` → ``host:***`` (保留主机
      名便于诊断, 抹端口避免暴露内部端口)
    - ``server_addresses`` tuple 整体不出现
    """
    if not message:
        return message

    out = message

    # 1) key=value / key: value / key:value
    for k in _REDACT_KEYS:
        # k=v
        i = 0
        while True:
            i = out.lower().find(k + "=", i)
            if i < 0:
                break
            # find value end (whitespace, comma, brace, etc.)
            j = i + len(k) + 1
            while j < len(out) and out[j] not in " \t\n,;}])\"'`":
                j += 1
            out = out[: i + len(k) + 1] + "***" + out[j:]
            i = j
        # k: v
        i = 0
        while True:
            i = out.lower().find(k + ":", i)
            if i < 0:
                break
            j = i + len(k) + 1
            if j < len(out) and out[j] == " ":
                j += 1
            while j < len(out) and out[j] not in " \t\n,;}])\"'`":
                j += 1
            out = out[: i + len(k) + 1] + "***" + out[j:]
            i = j

    # 2) host:port → ***:***  (PLANNING: 整个 server_addresses 不出现)
    import re

    def _host_port_repl(m: re.Match[str]) -> str:
        return "***:***"

    out = re.sub(r"[A-Za-z0-9_\-\.]+:\d{2,5}", _host_port_repl, out)

    return out


# ---------------------------------------------------------------------------
# 内部: 5 个 data_id → 字符串
# ---------------------------------------------------------------------------


def _all_data_ids(config: NacosRuleSourceConfig) -> list[tuple[str, str]]:
    """返回 ``[(rule_type, data_id)]`` 列表。"""
    return [
        (rt, config.data_id_for(rt))
        for rt in ("flow", "degrade", "param_flow", "system", "authority")
    ]


# ---------------------------------------------------------------------------
# Nacos SDK 适配层 (M6.1.7: v2.nacos async API)
# ---------------------------------------------------------------------------


class _NacosAdapter:
    """``NacosConfigService`` (SDK 3.2.0) 的薄包装; 屏蔽 async / 异常细节。

    中文
    ----
    把 nacos-sdk-python 3.2.0 的 async API 包装成内部 async 接口, 把 SDK
    抛的 ``NacosException`` / 网络错误转换成 5 类 :class:`NacosSourceError`
    分类。**不**在公开 API 暴露, 只在本模块内部使用。

    M6.1.7 改造点 (vs M6.1.0-1.6):
    - 删 ``register_watchers`` (push 路径); 仅保留 ``fetch_all`` / ``aclose``
    - 删 SDK 同步 ``NacosClient`` 调用, 改 async ``NacosConfigService`` 调用
    - 用 ``ClientConfigBuilder`` + ``GRPCConfig`` 构造客户端

    English
    --------
    Thin wrapper around ``NacosConfigService`` (SDK 3.2.0 async).
    Exposes ``fetch_all`` + ``aclose``; converts SDK exceptions into
    5-way :class:`NacosSourceError` taxonomy.
    """

    def __init__(
        self,
        config: NacosRuleSourceConfig,
        *,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        # 注入点: 测试用 fake service
        if client_factory is None:
            from v2.nacos import NacosConfigService  # 顶层 lazy import
            client_factory = NacosConfigService.create_config_service
        self._client_factory = client_factory
        self._client: Any | None = None

    async def _ensure_client(self) -> Any:
        """懒构造 NacosConfigService (async)。"""
        if self._client is not None:
            return self._client
        cfg = self._config
        # M6.1.7: SDK 3.2.0 用 ClientConfigBuilder 构造
        from v2.nacos import ClientConfigBuilder, GRPCConfig

        grpc_cfg = GRPCConfig(
            port_offset=1000,  # Nacos 2.x+ gRPC 端口 = HTTP 端口 + 1000
            grpc_timeout=int(cfg.read_timeout.total_seconds() * 1000),
        )
        client_config = (
            ClientConfigBuilder()
            .server_address(",".join(cfg.server_addresses))
            .namespace_id(cfg.namespace)
            .username(cfg.auth.username if cfg.auth else None)
            .password(cfg.auth.password if cfg.auth else None)
            .grpc_config(grpc_cfg)
            .timeout_ms(int(cfg.read_timeout.total_seconds() * 1000))
            .build()
        )
        # SDK 3.2.0 默认 fail-over cache 行为: get_config 优先读
        # `get_fail_over_config_cache` (磁盘), 空走 `query_config` (gRPC).
        # 在 Nacos 3.2.3 server 跨 client publish + get 场景下, 1 秒
        # 稳定可见, 跟 Java sentinel-datasource-nacos 行为近似.
        self._client = await self._client_factory(client_config)
        return self._client

    async def aclose(self) -> None:
        """停 SDK 客户端。SDK 失败只 log warn。"""
        if self._client is None:
            return
        try:
            await self._client.shutdown()
        except Exception as e:
            _logger.warning(
                "nacos service shutdown failed: %s",
                _redact(str(e), self._config),
            )
        finally:
            self._client = None

    async def fetch_all(
        self,
    ) -> tuple[dict[str, str], list[tuple[str, NacosSourceError, str]]]:
        """拉取 5 个 data_id 全部内容。

        返回 ``(data_ids_content, errors)``:
        - ``data_ids_content``: data_id → content (缺失 / 空都**不**进 map)
        - ``errors``: [(data_id, error, message), ...] 5 类错误分类
        """
        client = await self._ensure_client()
        cfg = self._config

        result: dict[str, str] = {}
        errors: list[tuple[str, NacosSourceError, str]] = []

        # M6.1.7: SDK 3.2.0 用 ConfigParam + async get_config
        from v2.nacos.config.model.config_param import ConfigParam
        from v2.nacos import NacosException

        for rule_type, data_id in _all_data_ids(cfg):
            try:
                content = await client.get_config(
                    ConfigParam(data_id=data_id, group=cfg.group)
                )
            except NacosException as e:
                # SDK 抛 NacosException(error_code, message);
                # 401/403 → AUTH; 400/404 → NOT_FOUND; 其它 → DECODE
                msg = str(e)
                code = getattr(e, "error_code", None)
                if code in (401, 403) or "401" in msg or "403" in msg or "Insufficient privilege" in msg:
                    errors.append((data_id, NacosSourceError.AUTH, msg))
                elif code in (400, 404) or "404" in msg or "not found" in msg.lower():
                    errors.append((data_id, NacosSourceError.NOT_FOUND, msg))
                else:
                    # SDK V3 protocol 错 (5xx / 其它 4xx 业务错); 视为 DECODE
                    errors.append((data_id, NacosSourceError.DECODE, msg))
                continue
            except (URLError, TimeoutError, ConnectionError, OSError) as e:
                errors.append(
                    (data_id, NacosSourceError.NETWORK, f"nacos network error: {e!r}")
                )
                continue
            except HTTPError as e:
                if e.code in (401, 403):
                    errors.append(
                        (data_id, NacosSourceError.AUTH, f"nacos {e.code}")
                    )
                elif e.code == 404:
                    errors.append(
                        (data_id, NacosSourceError.NOT_FOUND, "nacos 404")
                    )
                else:
                    errors.append(
                        (data_id, NacosSourceError.NETWORK, f"nacos http {e.code}")
                    )
                continue
            except Exception as e:
                # 其它 (例如 SDK 内部 gRPC 失败) → NETWORK
                errors.append(
                    (data_id, NacosSourceError.NETWORK, f"nacos error: {e!r}")
                )
                continue

            # SDK 3.2.0 行为: data_id 不存在 或 内容为空 → 返回空字符串 ''
            # (旧 SDK 0.1.16 缺失返回 None, Nacos 3.x 删 V1 endpoint 后 SDK 3.2.0
            # 走 V3 protocol, 不区分 "不存在" vs "空内容")。
            # 按 PLANNING M6.1.4 语义:
            #   - NOT_FOUND: 服务端 404 (NacosException error_code 400/404)
            #   - EMPTY:    服务端有这条配置但内容是空 ("" / "[]" / "null")
            if content is None:
                errors.append(
                    (data_id, NacosSourceError.NOT_FOUND, "nacos missing (None content)")
                )
                continue
            if content == "" or content.strip() in ("[]", "null"):
                # "" 或 "[]" / "null" → EMPTY (PLANNING: "[]" 也算 EMPTY, 保留 last-known-good)
                errors.append(
                    (data_id, NacosSourceError.EMPTY, "nacos empty content")
                )
                continue
            if not content.strip():
                # 纯空白
                errors.append(
                    (data_id, NacosSourceError.EMPTY, "nacos empty (whitespace) content")
                )
                continue
            result[data_id] = content

        return result, errors


# ---------------------------------------------------------------------------
# 公开: NacosRuleSource
# ---------------------------------------------------------------------------


class NacosRuleSource(SnapshotRuleSource):
    """Nacos 配置中心驱动的 :class:`SnapshotRuleSource` (M6.1.7 polling 模式)。

    中文
    ----
    实现主包 :class:`SnapshotRuleSource` Protocol; 通过后台 polling task
    (每 ``poll_interval`` 秒一次) 拉 5 个 Nacos data-id, 跟上次
    checksum 比对, 变化则 yield 新 :class:`RuleSnapshot`。

    **生命周期** (M6.1.7 polling, 替代 M6.1.0-1.6 push):

    1. ``__init__``: 校验 config (由 :class:`NacosRuleSourceConfig` 自身
       做, 这里只存字段)
    2. ``snapshots()`` 第一次 ``__anext__`` 触发: 状态 ``CONNECTING``
       → 拉 5 个 data_id → 全部成功 → 解码 → yield
       → 状态 ``READY`` → 启动 ``_poll_loop`` 后台 task
    3. Poll tick: 重新拉 5 个 data_id → 解码 → 跟上次 yield 的
       snapshot.checksum 比对 → 变化则 yield 新 snapshot
    4. 任何错误 → 状态转移 (``STALE`` / ``DISCONNECTED``); **不**yield
       新 snapshot (last-known-good 由 caller 侧 Repository 保留)
    5. ``aclose()``: 取消 ``_poll_task`` + 停 SDK 客户端; 状态 ``CLOSED``;
       后续 ``snapshots()`` 迭代立即结束

    **错误分类** (M6.1.4): 详见 :class:`NacosSourceError` 枚举 docstring
    + :class:`NacosRuleSourceConfig` 错误恢复策略表。

    **关闭语义** (M6.1.5): ``aclose()`` 幂等, **不**抛错; 即使 SDK
    内部 ``shutdown`` 失败, 也只 log warn, 不影响状态机转移。
    """

    source_id: str

    def __init__(
        self,
        config: NacosRuleSourceConfig,
        *,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        # config 不可变 dataclass 已在 __post_init__ 校验
        self._config = config
        self.source_id = config.source_id
        self._adapter = _NacosAdapter(config, client_factory=client_factory)

        # 状态机
        self._state: NacosSourceState = NacosSourceState.CONNECTING
        self._lock = asyncio.Lock()

        # 观测
        self._last_yielded_version: RuleVersion | None = None
        # M6.1.7 polling 内部状态: 上次 _load_snapshot() 拉到的 candidate
        # version; _poll_loop 用它跟 _last_yielded_version 比较, 决定
        # 是否触发新 snapshot. 不能跟 _last_yielded_version 合并, 否则
        # _load_snapshot 写 _last_yielded_version 后 _poll_loop 立刻读
        # 出来比较, 永远相等, polling 推不出新 snapshot.
        self._last_pulled_version: RuleVersion | None = None
        self._last_error: NacosSourceError | None = None
        self._last_error_message: str | None = None
        self._error_counts: dict[NacosSourceError, int] = {
            e: 0 for e in NacosSourceError
        }
        # 内部 reconnect 状态 (退避)
        self._reconnect_attempt: int = 0
        self._reconnect_initial_sec: float = config.reconnect_initial.total_seconds()
        self._reconnect_max_sec: float = config.reconnect_max.total_seconds()

        # M6.1.7 polling: 后台 task
        self._poll_task: asyncio.Task[None] | None = None
        self._poll_event: asyncio.Event | None = None
        self._poll_interval_sec: float = config.poll_interval.total_seconds()

        # 关闭
        self._closed: bool = False

    # --- 公开属性 (operator observability) ---

    @property
    def state(self) -> NacosSourceState:
        return self._state

    @property
    def last_success_version(self) -> RuleVersion | None:
        """上次 **成功 yield 给 caller** 的 :class:`RuleSnapshot` version.

        中文
        ----
        这是"caller 真正收到过" 的版本 (caller-side observable), 不等于
        "上次 poll 拉到的" (_last_pulled_version, 内部状态)。两者分开
        是因为 polling 模式下:
        - ``_load_snapshot()`` 拉 candidate, 写 _last_pulled_version
        - ``_poll_loop()`` 比较 candidate vs _last_yielded_version, 变化
          则把 candidate 提升为 yielded (写 _last_yielded_version)
        - 写 _last_yielded_version 后, ``_poll_event.set()`` 通知 caller

        如果合二为一, 写 _last_pulled_version 时也写 _last_yielded_version,
        ``_poll_loop`` 比较永远相等, 推不出新 snapshot (M6.1.7 polling
        bug 修复 1, 2026-09-13)。
        """
        return self._last_yielded_version

    @property
    def last_error(self) -> NacosSourceError | None:
        return self._last_error

    @property
    def last_error_message(self) -> str | None:
        return self._last_error_message  # 已在内部 _set_error 脱敏

    def error_count(self, error: NacosSourceError) -> int:
        """返回指定 :class:`NacosSourceError` 自 source 创建以来的累计次数。"""
        return self._error_counts.get(error, 0)

    # --- 内部: 状态 / 观测 维护 ---

    def _set_state(self, new_state: NacosSourceState) -> None:
        if new_state is not self._state:
            _logger.debug(
                "nacos source %r state: %s -> %s",
                self.source_id, self._state.value, new_state.value,
            )
            self._state = new_state

    def _set_error(
        self, error: NacosSourceError, raw_message: str | None = None,
    ) -> None:
        redacted = _redact(raw_message or "", self._config) if raw_message else None
        self._last_error = error
        self._last_error_message = redacted
        self._error_counts[error] = self._error_counts.get(error, 0) + 1
        if redacted:
            _logger.warning(
                "nacos source %r: %s — %s",
                self.source_id, error.value, redacted,
            )

    def _clear_error(self) -> None:
        self._last_error = None
        self._last_error_message = None

    # --- 退避 ---

    def _backoff_seconds(self) -> float:
        """指数退避: initial * 2^attempt, cap at max。"""
        if self._reconnect_attempt <= 0:
            return self._reconnect_initial_sec
        delay = self._reconnect_initial_sec * (2 ** (self._reconnect_attempt - 1))
        if delay > self._reconnect_max_sec:
            delay = self._reconnect_max_sec
        return float(delay)

    # --- 拉取 + 解码 + 错误分类 ---

    async def _load_snapshot(self) -> tuple[RuleSnapshot | None, list[NacosSourceError]]:
        """拉 5 个 data_id → 解码 → (snapshot, warnings)。

        错误分类:

        - **NETWORK**: 直接进入 ``DISCONNECTED``; 触发退避
        - **AUTH**: 直接进入 ``DISCONNECTED``; **不**自动重试, 等人工
        - **NOT_FOUND / EMPTY / DECODE**: 进入 ``STALE``;
          snapshot **不**含缺失的 data_id 类; 仍可 yield (last-known
          -good 由 Repository 保留语义)
        """
        try:
            data_ids_content, errors = await self._adapter.fetch_all()
        except Exception as e:
            # 极端: _ensure_client 失败 / SDK 内部 panic
            self._set_error(NacosSourceError.AUTH, repr(e))
            self._set_state(NacosSourceState.DISCONNECTED)
            return None, [NacosSourceError.AUTH]

        # 5 类错误分类决策
        has_network = any(err is NacosSourceError.NETWORK for _, err, _ in errors)
        has_auth = any(err is NacosSourceError.AUTH for _, err, _ in errors)
        if has_auth:
            self._set_state(NacosSourceState.DISCONNECTED)
            for _, err, msg in errors:
                self._set_error(err, msg)
            return None, [NacosSourceError.AUTH]
        if has_network:
            self._set_state(NacosSourceState.DISCONNECTED)
            for _, err, msg in errors:
                self._set_error(err, msg)
            return None, [NacosSourceError.NETWORK]

        # NOT_FOUND / EMPTY / DECODE — 生成 snapshot, 标记 STALE
        try:
            snapshot, warnings = decode_rule_snapshot(
                data_ids_content,
                RuleVersion(
                    epoch=int(time.time()),
                    revision=self._reconnect_attempt,
                    checksum=hashlib.sha256(
                        ("\n".join(
                            f"{k}={v}" for k, v in sorted(data_ids_content.items())
                        )).encode("utf-8")
                    ).hexdigest(),
                ),
                config=self._config,
            )
        except NacosCodecError as e:
            self._set_error(NacosSourceError.DECODE, str(e))
            self._set_state(NacosSourceState.STALE)
            return None, [NacosSourceError.DECODE]

        for _, err, msg in errors:
            self._set_error(err, msg)
        if errors or warnings:
            self._set_state(NacosSourceState.STALE)
        else:
            self._set_state(NacosSourceState.READY)
            self._clear_error()
        # M6.1.7 polling bug 修复 1: 写 _last_pulled_version (candidate),
        # **不**写 _last_yielded_version. _poll_loop 比较
        # candidate vs _last_yielded_version, 变化时才把 candidate
        # 提升为 yielded (写 _last_yielded_version).
        # STALE 状态 (部分 data_id 缺失) 也算拉取成功, last-known-good 保留
        self._last_pulled_version = snapshot.version

        return snapshot, warnings

    # --- 公开: snapshots() 异步迭代器 (M6.1.7 polling 模式) ---

    async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        """异步迭代器: 持续 yield :class:`RuleSnapshot` (M6.1.7 polling)。

        中文
        ----
        1. 首次 ``__anext__`` 触发: 拉 5 个 data_id → yield 首个 snapshot
           → 启动 ``_poll_loop`` 后台 task
        2. 后续 yield: 由 ``_poll_loop`` 推入 ``_poll_queue``,
           snapshots() 循环 await ``_poll_queue.get()``
        3. Poll tick (后台): 每 ``poll_interval`` 秒拉一次,
           跟上次 checksum 比对, 变化则 put 新 snapshot 到 ``_poll_queue``
        4. 错误: **不**yield; 状态转移, 退避后继续 poll
        5. ``aclose()`` 后: 取消 ``_poll_task``, 立即 ``StopAsyncIteration``
        """
        if self._closed:
            return

        # 1) 首次拉取 — 失败进入退避循环; 成功才 yield
        snapshot, _warnings = await self._initial_load_with_backoff()
        if snapshot is not None:
            # M6.1.7 polling bug 修复 1: yield 前把 candidate 提升为 yielded.
            # _load_snapshot 写 _last_pulled_version, 但 _last_yielded_version
            # 必须由 yield 路径写, 否则 _poll_loop 比较时永远相等.
            self._last_yielded_version = snapshot.version
            yield snapshot
        if self._closed:
            return

        # 2) 启动 polling 后台 task
        self._poll_event = asyncio.Event()
        self._poll_task = asyncio.create_task(
            self._poll_loop(),
            name=f"nacos-source-{self.source_id}-poll",
        )

        # 3) 主循环: 等 poll task 推入新 snapshot
        while not self._closed:
            try:
                next_snapshot = await self._wait_for_next_snapshot()
            except asyncio.CancelledError:
                return
            if next_snapshot is None or self._closed:
                return
            # _poll_loop 在 set event 前已经写 _last_yielded_version
            # (candidate 提升为 yielded), 不需要这里再写
            yield next_snapshot

    async def _wait_for_next_snapshot(self) -> RuleSnapshot | None:
        """等待 poll loop 推入下一个 snapshot; aclose 立即返回 None。"""
        assert self._poll_event is not None
        await self._poll_event.wait()
        if self._closed:
            return None
        self._poll_event.clear()
        return self._pending_snapshot

    async def _poll_loop(self) -> None:
        """M6.1.7 polling 后台 task。

        中文
        ----
        每 ``poll_interval`` 秒:
        1. ``_load_snapshot()`` 拉 5 个 data_id
        2. 错误: 状态转移 + 退避; 不 yield
        3. 成功: 跟上次 yield 的 snapshot.checksum 比对
        4. 变化: 写 ``_pending_snapshot`` + ``_poll_event.set()``
        5. 无变化: skip
        """
        while not self._closed:
            try:
                await asyncio.sleep(self._poll_interval_sec)
            except asyncio.CancelledError:
                return
            if self._closed:
                return

            snapshot, _warnings = await self._load_snapshot()
            if snapshot is None:
                # 错误: 已设置 _last_error + state; 退避后继续
                err = self._last_error
                if err is NacosSourceError.AUTH:
                    # AUTH 不自动重试, 等人工干预
                    continue
                self._reconnect_attempt += 1
                await self._sleep_with_cancel(self._backoff_seconds())
                continue

            # 成功: 跟上次 yielded snapshot 比对 (不是 _last_pulled_version!
            # 那是刚 _load_snapshot 写的; 见上方 M6.1.7 polling bug 修复 1)
            self._reconnect_attempt = 0
            if (
                self._last_yielded_version is None
                or snapshot.version.checksum != self._last_yielded_version.checksum
            ):
                # candidate 提升为 yielded
                self._last_yielded_version = snapshot.version
                self._pending_snapshot = snapshot
                if self._poll_event is not None:
                    self._poll_event.set()
            # else: 内容未变, skip

    async def _initial_load_with_backoff(
        self,
    ) -> tuple[RuleSnapshot | None, list[NacosSourceError]]:
        """首次拉取; 失败按退避重试, 直到成功 / 关闭 / 命中 AUTH。"""
        self._reconnect_attempt = 0
        while not self._closed:
            snapshot, _warnings = await self._load_snapshot()
            if snapshot is not None:
                return snapshot, _warnings
            # 错误: 决定是否继续重试
            err = self._last_error
            if err is NacosSourceError.AUTH:
                # AUTH 不自动重试
                return None, [NacosSourceError.AUTH]
            # NETWORK / DECODE: 退避重试
            self._reconnect_attempt += 1
            delay = self._backoff_seconds()
            _logger.info(
                "nacos source %r: retrying after %.2fs (attempt %d)",
                self.source_id, delay, self._reconnect_attempt,
            )
            await self._sleep_with_cancel(delay)
        return None, []

    async def _sleep_with_cancel(self, delay: float) -> None:
        """可被 aclose 取消的 sleep。"""
        if delay <= 0:
            return
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise

    # --- 公开: aclose ---

    async def aclose(self) -> None:
        """幂等关闭: 取消 polling task, 停 SDK 客户端, 状态 → CLOSED。

        中文
        ----
        - 多次调**不**抛错
        - 内部 SDK 错误只 log warn
        - 关闭后 ``snapshots()`` 迭代立即结束
        - 状态保持 ``CLOSED``
        """
        if self._closed:
            return
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            # 唤醒可能在等的 _poll_event
            if self._poll_event is not None:
                try:
                    self._poll_event.set()
                except Exception:
                    pass
            # 取消 polling task
            if self._poll_task is not None and not self._poll_task.done():
                self._poll_task.cancel()
                try:
                    await self._poll_task
                except (asyncio.CancelledError, Exception):
                    pass
            await self._adapter.aclose()
            self._set_state(NacosSourceState.CLOSED)
            _logger.debug("nacos source %r closed", self.source_id)


__all__ = [
    "NacosRuleSource",
    "_redact",  # 内部 helper, 不应外部用; 暴露便于测试
]
