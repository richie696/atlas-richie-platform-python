"""Nacos :class:`RuleSource` 实现 (M6.1.3 + M6.1.4 + M6.1.5)。

中文
----
**职责**: 把 :class:`NacosRuleSourceConfig` 配置 + Nacos 5 个 data-id
包装成主包 :class:`SnapshotRuleSource` Protocol。

**3 个子任务**:

- **M6.1.3 生命周期**: 启动 → 首次全量拉取 → 解码 → yield
  → 进入 :class:`NacosSourceState.READY` → 订阅 long-poll
  → 推送到达 → 重读 5 个 data_id → 解码 → yield
- **M6.1.4 错误分类**: 5 类 (:class:`NacosSourceError`):
  AUTH / NOT_FOUND / EMPTY / DECODE / NETWORK, 不同恢复策略
- **M6.1.5 关闭管理**: ``aclose()`` 幂等, 取消 listener task, 停 SDK 订阅

**不**做的事:

- **不** import 主包 C 层 ``_supervisor.*`` (C 层物理隔离)
- **不** 泄漏 nacos SDK 类型到公开 API
- **不** 阻塞事件循环: 同步 SDK 调用经
  ``loop.run_in_executor`` 包装
- **不** 缓存凭据到 ``last_error_message`` (脱敏)
- **不** 在错误时 yield 新 snapshot (last-known-good 由 caller 侧
  Repository 保留)

English
--------
Nacos-backed implementation of :class:`SnapshotRuleSource`.

Wraps :class:`NacosRuleSourceConfig` + 5 Nacos data-ids into the
main-package ``SnapshotRuleSource`` Protocol. Covers M6.1.3 lifecycle,
M6.1.4 5-way error classification, M6.1.5 idempotent aclose.

**Does not**: import main-package C-layer ``_supervisor.*``; leak
nacos SDK types into public API; block the event loop (sync SDK
calls go through ``loop.run_in_executor``); cache credentials in
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
# 脱敏 (M6.1.5 前置要求)
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
# Nacos SDK 适配层
# ---------------------------------------------------------------------------

# SDK 回调签名 (从 nacos-sdk-python 源码确认):
#   cb({"data_id", "group", "namespace", "raw_content", "content"})
NacosCallbackParams = dict[str, Any]


class _NacosAdapter:
    """``NacosClient`` 的薄包装; 屏蔽同步 / 异常细节。

    中文
    ----
    把 nacos-sdk-python 的同步 API 包装成 ``await`` 形式, 把 HTTPError
    转换成 5 类 :class:`NacosSourceError` 分类。

    **不**在公开 API 暴露, 只在本模块内部使用。
    """

    def __init__(
        self,
        config: NacosRuleSourceConfig,
        *,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        # 注入点: 测试用 fake client
        if client_factory is None:
            from nacos import NacosClient  # 同步 import; 在 IO 边界外
            client_factory = NacosClient
        self._client_factory = client_factory
        self._client: Any | None = None
        # 缓存已注册的 watcher 回调
        self._registered_callbacks: list[tuple[str, str, Callable[..., None]]] = []

    async def _ensure_client(self) -> Any:
        """懒构造 NacosClient (IO 边界用 run_in_executor)。"""
        if self._client is not None:
            return self._client
        cfg = self._config
        loop = asyncio.get_running_loop()

        def _build() -> Any:
            # nacos-sdk-python 2.x 的 server_addresses 接受 str / tuple[str]
            # 内部会做 round-robin; 多个地址直接传 tuple
            auth = cfg.auth
            return self._client_factory(
                server_addresses=list(cfg.server_addresses)
                or [str(cfg.server_addresses[0])],
                namespace=cfg.namespace,
                username=auth.username if auth else None,
                password=auth.password if auth else None,
            )

        self._client = await loop.run_in_executor(None, _build)
        return self._client

    async def aclose(self) -> None:
        """停止订阅 + 清理 client。SDK 失败只 log warn。"""
        if self._client is None:
            return
        loop = asyncio.get_running_loop()

        def _stop() -> None:
            try:
                self._client.stop_subscribe()
            except Exception as e:
                _logger.warning(
                    "nacos client stop_subscribe failed: %s",
                    _redact(str(e), self._config),
                )
            # 取消所有注册的 watcher
            for data_id, group, cb in self._registered_callbacks:
                try:
                    self._client.remove_config_watcher(data_id, group, cb)
                except Exception as e:
                    _logger.warning(
                        "nacos remove watcher failed for %s: %s",
                        data_id,
                        _redact(str(e), self._config),
                    )
            self._registered_callbacks.clear()

        try:
            await loop.run_in_executor(None, _stop)
        except Exception as e:
            _logger.warning(
                "nacos adapter aclose failed: %s",
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
        loop = asyncio.get_running_loop()

        result: dict[str, str] = {}
        errors: list[tuple[str, NacosSourceError, str]] = []

        for rule_type, data_id in _all_data_ids(cfg):
            try:
                content = await loop.run_in_executor(
                    None, client.get_config, data_id, cfg.group,
                )
            except HTTPError as e:
                # SDK 在 no_snapshot=False 时不会 raise, 但 no_snapshot=True
                # 时会 raise; 我们走 no_snapshot=False (默认) 走"静默
                # 失败 + 返回 None"路径, 这里仅是防御
                if e.code == 403:
                    errors.append(
                        (data_id, NacosSourceError.AUTH, "nacos 403 forbidden")
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
            except (URLError, TimeoutError, ConnectionError, OSError) as e:
                errors.append(
                    (data_id, NacosSourceError.NETWORK, f"nacos network error: {e!r}")
                )
                continue
            except Exception as e:
                # SDK NacosException (其他) — 大概率是 auth / config 错误
                msg = str(e)
                if "Insufficient privilege" in msg or "401" in msg or "403" in msg:
                    errors.append((data_id, NacosSourceError.AUTH, msg))
                else:
                    errors.append(
                        (data_id, NacosSourceError.NETWORK, f"nacos error: {msg}")
                    )
                continue

            if content is None:
                # 404: Nacos SDK 把 404 → None (官方 no_snapshot=False 行为)
                errors.append(
                    (data_id, NacosSourceError.NOT_FOUND, "nacos 404 (None content)")
                )
                continue
            if not content.strip():
                # 真正空: 视为 EMPTY (last-known-good 保留)
                errors.append(
                    (data_id, NacosSourceError.EMPTY, "nacos empty content")
                )
                # **不**进入 result, 由 codec 跳过
                continue
            if content.strip() in ("[]", "null"):
                # PLANNING: "[]" 也算 EMPTY, 保留 last-known-good
                errors.append(
                    (data_id, NacosSourceError.EMPTY, "nacos '[]' or 'null' content")
                )
                continue
            result[data_id] = content

        return result, errors

    async def register_watchers(
        self,
        callback: Callable[[NacosCallbackParams], None],
    ) -> None:
        """注册 5 个 data_id 的 watcher。SDK long-poll 推送触发 callback。"""
        client = await self._ensure_client()
        cfg = self._config
        loop = asyncio.get_running_loop()

        def _register() -> None:
            for rule_type, data_id in _all_data_ids(cfg):
                self._registered_callbacks.append(
                    (data_id, cfg.group, callback)
                )
                client.add_config_watcher(
                    data_id, cfg.group, callback,
                )

        await loop.run_in_executor(None, _register)


# ---------------------------------------------------------------------------
# 公开: NacosRuleSource
# ---------------------------------------------------------------------------


class NacosRuleSource(SnapshotRuleSource):
    """Nacos 配置中心驱动的 :class:`SnapshotRuleSource`。

    中文
    ----
    实现主包 :class:`SnapshotRuleSource` Protocol; 通过 SDK long-poll
    订阅 + 全量重读策略实现"近实时"规则同步。

    **生命周期** (M6.1.3):

    1. ``__init__``: 校验 config (由 :class:`NacosRuleSourceConfig` 自身
       做, 这里只存字段)
    2. ``snapshots()`` 第一次 ``__anext__`` 触发: 状态 ``CONNECTING``
       → 拉 5 个 data_id → 全部成功 → 解码 → yield
       → 状态 ``READY`` → 注册 5 个 watcher
    3. SDK 回调触发: 把回调 marshal 到 asyncio 事件循环
       → 重新拉 5 个 data_id → 解码 → yield
    4. 任何错误 → 状态转移 (``STALE`` / ``DISCONNECTED``); **不**yield
       新 snapshot (last-known-good 由 caller 侧 Repository 保留)
    5. ``aclose()``: 取消 SDK 回调注册 + 状态 ``CLOSED``;
       后续 ``snapshots()`` 迭代立即结束

    **错误分类** (M6.1.4): 详见 :class:`NacosSourceError` 枚举 docstring
    + :class:`NacosRuleSourceConfig` 错误恢复策略表。

    **关闭语义** (M6.1.5): ``aclose()`` 幂等, **不**抛错; 即使 SDK
    内部 ``stop_subscribe`` / ``remove_config_watcher`` 失败, 也只
    log warn, 不影响状态机转移。
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
        self._last_success_version: RuleVersion | None = None
        self._last_error: NacosSourceError | None = None
        self._last_error_message: str | None = None
        self._error_counts: dict[NacosSourceError, int] = {
            e: 0 for e in NacosSourceError
        }
        # 内部 reconnect 状态 (退避)
        self._reconnect_attempt: int = 0
        self._reconnect_initial_sec: float = config.reconnect_initial.total_seconds()
        self._reconnect_max_sec: float = config.reconnect_max.total_seconds()

        # SDK 回调 marshal 用
        self._loop: asyncio.AbstractEventLoop | None = None
        self._change_event: asyncio.Event | None = None
        self._change_pending: bool = False

        # 关闭
        self._closed: bool = False

    # --- 公开属性 (operator observability) ---

    @property
    def state(self) -> NacosSourceState:
        return self._state

    @property
    def last_success_version(self) -> RuleVersion | None:
        return self._last_success_version

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

    # --- SDK 回调 marshal ---

    def _on_sdk_change(self, params: NacosCallbackParams) -> None:
        """Nacos SDK 线程池回调; marshal 到 asyncio loop。

        中文
        ----
        ``add_config_watcher`` 回调在 SDK 自己的 thread pool 触发
        (``self.callback_tread_pool.apply``); 我们**不**在 callback 内
        做任何阻塞 IO, 只把"有变化"信号扔到 asyncio loop。
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        # 同一 data_id 多次变化 → 只触发一次重读
        self._change_pending = True
        if self._change_event is not None:
            loop.call_soon_threadsafe(self._change_event.set)

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
        # NOTE: snapshot 已成功生成 → 记 last_success_version
        # STALE 状态 (部分 data_id 缺失) 也算成功, last-known-good 保留
        self._last_success_version = snapshot.version

        return snapshot, warnings

    # --- 公开: snapshots() 异步迭代器 ---

    async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        """异步迭代器: 持续 yield :class:`RuleSnapshot`。

        中文
        ----
        1. 首次 ``__anext__`` 触发: 拉 5 个 data_id → yield 首个
           snapshot → 注册 5 个 watcher
        2. 后续: 等 SDK 回调 (marshal 到 asyncio.Event) → 拉 → yield
        3. 错误: **不**yield; 等待下次推送 / 退避
        4. ``aclose()`` 后: 立即 ``StopAsyncIteration``
        """
        if self._closed:
            return
        self._loop = asyncio.get_running_loop()
        self._change_event = asyncio.Event()

        # 1) 首次拉取 — 失败进入退避循环; 成功才 yield
        snapshot, _warnings = await self._initial_load_with_backoff()
        if snapshot is not None:
            yield snapshot
        if self._closed:
            return

        # 2) 注册 5 个 watcher (SDK long-poll)
        try:
            await self._adapter.register_watchers(self._on_sdk_change)
        except Exception as e:
            self._set_error(NacosSourceError.AUTH, repr(e))
            self._set_state(NacosSourceState.DISCONNECTED)
            return

        # 3) 主循环
        while not self._closed:
            # 等 SDK 推送或 aclose
            assert self._change_event is not None
            try:
                await self._change_event.wait()
            except asyncio.CancelledError:
                return
            self._change_event.clear()
            if self._closed:
                return
            self._change_pending = False

            # 重新拉取 + 解码
            snapshot, _warnings = await self._load_snapshot()
            if snapshot is None:
                # 错误分类已经处理; 退避后继续等下次 change_event
                await self._sleep_with_cancel(
                    self._backoff_seconds(),
                )
                self._reconnect_attempt += 1
                continue

            # 成功 yield
            self._reconnect_attempt = 0
            if not self._closed:
                yield snapshot

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
        """幂等关闭: 取消监听, 停 SDK 订阅, 状态 → CLOSED。

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
            # 唤醒可能在等的 change_event
            if self._change_event is not None:
                try:
                    self._change_event.set()
                except Exception:
                    pass
            await self._adapter.aclose()
            self._set_state(NacosSourceState.CLOSED)
            _logger.debug("nacos source %r closed", self.source_id)


__all__ = [
    "NacosRuleSource",
    "_redact",  # 内部 helper, 不应外部用; 暴露便于测试
]
