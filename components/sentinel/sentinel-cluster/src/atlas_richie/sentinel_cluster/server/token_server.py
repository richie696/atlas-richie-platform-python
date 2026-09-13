"""Atlas Richie Sentinel Cluster — Token Server 状态机 (M6.3.3, 核心).

中文
----
``TokenServer`` 是 Cluster 模式的资源分配 Server, 维护 lease 状态机
(acquire / release / renew / lease expiry / owner epoch fencing /
startup config fail-fast)。

**状态机** (见 IMPLEMENTATION-PLAN §2.4 状态表):

```
CREATED --await start()--> READY --await stop()--> SHUTTING_DOWN --in-flight == 0--> SHUTDOWN
                              |
                              +-- expired lease scan (background task)
```

**核心方法** (内部, 由 ``http_transport`` 在收到 envelope 后调用):

- ``handle_acquire(envelope) -> envelope``: ACQUIRE_REQUEST 处理
  - idempotency cache 命中 → 返回缓存响应
  - resource 未配 → 抛 ``ClusterResourceNotConfigured`` (调用方决定
    是否转 ERROR_RESPONSE)
  - 配额满 → 返回 ACQUIRE_RESPONSE + DENIED + QUEUE_FULL
  - 配额未满 → 分配 lease (UUID) + 返回 ACQUIRE_RESPONSE + REMOTE_GRANTED
- ``handle_release(envelope) -> envelope``: RELEASE_REQUEST 处理
  - idempotency cache 命中 → 返回缓存响应
  - ``(lease_id, instance_id, startup_epoch)`` 不匹配 → 抛
    ``ClusterStaleEpoch`` (调用方决定转 ERROR_RESPONSE STALE_EPOCH)
  - lease 不存在 → 抛 ``ClusterLeaseNotFound``
  - 成功 → 配额恢复 + 返回空 ACQUIRE_RESPONSE (denoted by 200 + no body
    或一个 dedicated response kind; 1.0 选: 复用 ACQUIRE_RESPONSE schema
    with decision=DENIED + deny_reason=LEASE_NOT_FOUND 当不存在
    时更友好; 1.0 简化为: 成功 → 返回 ACQUIRE_RESPONSE + DENIED +
    deny_reason=LEASE_RELEASED (新, 加 V1.1))

**实际 1.0 设计** (避免 V1 wire protocol 修改): Server 对 release / renew
处理结果用 **ERROR_RESPONSE** (lease 错误) 或 **ACQUIRE_RESPONSE** (语义
复用) 表达。详细见各 handler docstring。

**线程模型**: 单 asyncio event loop, ``asyncio.Lock`` 保护 lease_store
跟 idempotency_cache。所有 ``handle_*`` 都是 coroutine。

English
--------
``TokenServer`` is the Cluster-mode resource allocation Server, maintaining
the lease state machine (acquire / release / renew / lease expiry / owner
epoch fencing / startup config fail-fast).

State machine (see IMPLEMENTATION-PLAN §2.4 state table):

```
CREATED --await start()--> READY --await stop()--> SHUTTING_DOWN --in-flight == 0--> SHUTDOWN
                              |
                              +-- expired lease scan (background task)
```

Core methods (internal, called by ``http_transport`` after envelope decode):

- ``handle_acquire(envelope) -> envelope``
- ``handle_release(envelope) -> envelope``
- ``handle_renew(envelope) -> envelope``

Threading model: single asyncio event loop, ``asyncio.Lock`` protects
``lease_store`` and ``idempotency_cache``. All ``handle_*`` are coroutines.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from atlas_richie.contracts.cluster.v1 import (
    ClusterDenyReason,
    ClusterErrorCode,
    ClusterMessageKind,
    ClusterTokenEnvelope,
    DEFAULT_LEASE_TTL_NS,
    IDEMPOTENCY_CACHE_TTL_NS,
    ISO_8601_UTC_MICRO,
    PROTOCOL_VERSION,
)
from atlas_richie.sentinel.ports.token import ClusterFailurePolicy

from ..config import ClusterTokenConfig
from ..errors import (
    ClusterConfigError,
    ClusterLeaseNotFound,
    ClusterResourceNotConfigured,
    ClusterServerError,
    ClusterStaleEpoch,
)
from .idempotency_cache import IdempotencyCache
from .lease_store import Lease, LeaseStore

_log = logging.getLogger("atlas_richie.sentinel_cluster.token_server")


class TokenServerState(StrEnum):
    """TokenServer 状态机 (公开 enum, 1.0)."""

    CREATED = "created"
    READY = "ready"
    SHUTTING_DOWN = "shutting_down"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True, slots=True)
class TokenServerStats:
    """TokenServer 运行时统计 (snapshot, 单测 / 运维用)."""

    acquire_total: int = 0
    acquire_granted: int = 0
    acquire_denied: int = 0
    release_total: int = 0
    renew_total: int = 0
    renew_extended: int = 0
    idempotency_hits: int = 0
    error_responses: int = 0


def _now_iso_utc_micro(now_ns: int) -> str:
    """``now_ns`` → ISO 8601 UTC microsecond ``YYYY-MM-DDTHH:MM:SS.ffffffZ``."""
    dt = datetime.fromtimestamp(now_ns / 1_000_000_000, tz=timezone.utc)
    return dt.strftime(ISO_8601_UTC_MICRO)


def _make_envelope(
    *,
    request_id: str,
    instance_id: str,
    startup_epoch: int,
    resource: str,
    permits: float,
    deadline_ns: int,
    message_kind: ClusterMessageKind,
    payload: dict[str, Any],
    now_ns: int,
) -> ClusterTokenEnvelope:
    """构造 Server 出向 envelope (request/received 时间 + payload)."""
    iso = _now_iso_utc_micro(now_ns)
    return ClusterTokenEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_kind=message_kind,
        request_id=request_id,
        instance_id=instance_id,
        startup_epoch=startup_epoch,
        resource=resource,
        permits=permits,
        deadline_ns=deadline_ns,
        client_requested_at=iso,  # Server 回显 client 时间 (用于诊断)
        server_received_at=iso,  # Server 自己的接收时间 (单测注入 now_ns)
        payload=payload,
    )


class TokenServer:
    """Cluster Token Server 状态机 (M6.3.3).

    1.0 公开 API:

    - ``await token_server.start()``: CREATED → READY
    - ``await token_server.stop()``: READY → SHUTTING_DOWN → SHUTDOWN
    - ``await token_server.handle_acquire(envelope) -> envelope``
    - ``await token_server.handle_release(envelope) -> envelope``
    - ``await token_server.handle_renew(envelope) -> envelope``
    - ``token_server.state`` / ``token_server.lease_store`` /
      ``token_server.idempotency_cache`` / ``token_server.stats``
    """

    def __init__(
        self,
        config: ClusterTokenConfig,
        *,
        clock: "callable[[], int] | None" = None,
    ) -> None:
        """初始化 TokenServer; **不**做 fail-fast 校验, 仅在 ``start()`` 触发.

        Args:
            config: 启动配置 (frozen)
            clock: 时钟函数 (返回 int 纳秒), 用于单测注入
        """
        if not isinstance(config, ClusterTokenConfig):
            raise ClusterConfigError(
                f"config must be ClusterTokenConfig, got {type(config).__name__}",
                code="CONFIG_ERROR",
            )
        self._config = config
        self._clock = clock if clock is not None else time.time_ns
        self._state: TokenServerState = TokenServerState.CREATED
        self._inflight = 0
        self._max_inflight_reached = False
        self._scrub_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        # 启动期 fail-fast: 校验每个 resource 在 failure_policy_per_resource 中
        missing = config.resource_names() - set(config.failure_policy_per_resource.keys())
        if missing:
            # 设计 §2.4: 启动期 fail-fast 抛 ClusterConfigError("RESOURCE_NOT_CONFIGURED")
            raise ClusterConfigError(
                f"RESOURCE_NOT_CONFIGURED: failure_policy_per_resource missing keys: "
                f"{sorted(missing)}",
                code="RESOURCE_NOT_CONFIGURED",
            )
        self._lease_store = LeaseStore(
            config.resources,
            lease_ttl_ns=config.lease_ttl_ns,
            clock=self._clock,
        )
        self._idempotency = IdempotencyCache(
            ttl_ns=config.idempotency_cache_ttl_ns,
            clock=self._clock,
        )
        # 统计 (mutated in handlers; 公开 snapshot)
        self._stats = {
            "acquire_total": 0,
            "acquire_granted": 0,
            "acquire_denied": 0,
            "release_total": 0,
            "renew_total": 0,
            "renew_extended": 0,
            "idempotency_hits": 0,
            "error_responses": 0,
        }

    # ------------------------------------------------------------------
    # properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> TokenServerState:
        return self._state

    @property
    def config(self) -> ClusterTokenConfig:
        return self._config

    @property
    def lease_store(self) -> LeaseStore:
        return self._lease_store

    @property
    def idempotency_cache(self) -> IdempotencyCache:
        return self._idempotency

    @property
    def stats(self) -> TokenServerStats:
        return TokenServerStats(**self._stats)

    @property
    def is_ready(self) -> bool:
        return self._state is TokenServerState.READY

    @property
    def is_shutting_down(self) -> bool:
        return self._state is TokenServerState.SHUTTING_DOWN

    @property
    def is_shutdown(self) -> bool:
        return self._state is TokenServerState.SHUTDOWN

    @property
    def inflight(self) -> int:
        return self._inflight

    async def wait_ready(self, timeout_s: float | None = None) -> None:
        """等待 Server 进入 READY 状态 (单测用)."""
        if timeout_s is None:
            await self._ready_event.wait()
        else:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout_s)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动 Server: CREATED → READY, 启动 lease scrub 后台 task.

        Raises:
            ClusterConfigError: 启动期 fail-fast (resource 未配, 1.0 接受
                这种情况: __init__ 已校验过; 重复校验防御性)
            ClusterServerError: 当前状态不允许 start (非 CREATED / SHUTDOWN)
        """
        if self._state is TokenServerState.CREATED:
            pass
        elif self._state is TokenServerState.SHUTDOWN:
            # 允许 restart from SHUTDOWN; 1.0 接受 (设计未禁止)
            self._state = TokenServerState.CREATED
        else:
            raise ClusterServerError(
                f"start() not allowed in state {self._state.value}",
                code="LIFECYCLE_ERROR",
            )
        # 二次 fail-fast 校验
        missing = self._config.resource_names() - set(
            self._config.failure_policy_per_resource.keys()
        )
        if missing:
            raise ClusterConfigError(
                f"RESOURCE_NOT_CONFIGURED: failure_policy_per_resource missing keys: "
                f"{sorted(missing)}",
                code="RESOURCE_NOT_CONFIGURED",
            )
        # 启动后台 lease + idempotency scrub task
        self._scrub_task = asyncio.create_task(
            self._scrub_loop(), name="cluster-token-server-scrub"
        )
        self._state = TokenServerState.READY
        self._ready_event.set()
        _log.info(
            "TokenServer started: mode=%s bind=%s resources=%d",
            self._config.cluster_token_mode.value,
            self._config.bind_address,
            len(self._config.resources),
        )

    async def stop(self) -> None:
        """停止 Server: READY → SHUTTING_DOWN → SHUTDOWN.

        行为:
        - 进入 SHUTTING_DOWN, 新请求被拒 (调 ``_enter()`` 入口会抛)
        - 等所有 in-flight 请求完成, 或 ``shutdown_timeout_s`` 触发
        - 取消后台 scrub task
        - 进入 SHUTDOWN, 释放资源
        """
        if self._state is TokenServerState.SHUTDOWN:
            return
        if self._state is not TokenServerState.READY:
            raise ClusterServerError(
                f"stop() not allowed in state {self._state.value}",
                code="LIFECYCLE_ERROR",
            )
        self._state = TokenServerState.SHUTTING_DOWN
        _log.info("TokenServer entering SHUTTING_DOWN (inflight=%d)", self._inflight)
        # 等 in-flight == 0 或 shutdown_timeout
        try:
            await asyncio.wait_for(
                self._wait_inflight_zero(),
                timeout=self._config.shutdown_timeout_s,
            )
        except asyncio.TimeoutError:
            _log.warning(
                "TokenServer shutdown timeout (%ss) reached, forcing SHUTDOWN "
                "(inflight=%d will be cancelled by http_transport)",
                self._config.shutdown_timeout_s,
                self._inflight,
            )
        # 取消后台 scrub task
        if self._scrub_task is not None and not self._scrub_task.done():
            self._scrub_task.cancel()
            try:
                await self._scrub_task
            except (asyncio.CancelledError, Exception):
                pass
        self._state = TokenServerState.SHUTDOWN
        self._shutdown_event.set()
        _log.info("TokenServer SHUTDOWN complete")

    async def _wait_inflight_zero(self) -> None:
        """等待 in-flight 请求数 == 0 (内部 helper)."""
        while self._inflight > 0:
            await asyncio.sleep(0.001)

    async def _scrub_loop(self) -> None:
        """后台 task: 周期扫 lease + idempotency cache 过期 entry."""
        try:
            while self._state in (TokenServerState.READY, TokenServerState.SHUTTING_DOWN):
                try:
                    cleaned_leases = await self._lease_store.scrub_expired()
                    cleaned_idem = await self._idempotency.scrub_expired()
                    if cleaned_leases > 0 or cleaned_idem > 0:
                        _log.debug(
                            "scrub: leases=%d idempotency=%d",
                            cleaned_leases,
                            cleaned_idem,
                        )
                except Exception as e:  # pragma: no cover (defensive)
                    _log.exception("scrub loop error: %s", e)
                await asyncio.sleep(self._config.lease_scrub_interval_s)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # in-flight tracking (public for http_transport use)
    # ------------------------------------------------------------------

    async def _enter(self) -> int:
        """进入请求处理; 超过 max_inflight 或 Server 在 SHUTTING_DOWN 抛.

        Returns:
            进入 token (用于 _exit 配对)
        """
        if self._state is not TokenServerState.READY:
            raise ClusterServerError(
                f"server not ready (state={self._state.value})",
                code="SERVER_OVERLOADED",
            )
        if self._inflight >= self._config.max_inflight:
            raise ClusterServerError(
                f"max_inflight reached ({self._config.max_inflight})",
                code="SERVER_OVERLOADED",
            )
        self._inflight += 1
        return id(self)

    async def _exit(self, token: int) -> None:
        """退出请求处理 (配对 ``_enter``)."""
        self._inflight = max(0, self._inflight - 1)

    # ------------------------------------------------------------------
    # ACQUIRE handler
    # ------------------------------------------------------------------

    async def handle_acquire(self, envelope: ClusterTokenEnvelope) -> ClusterTokenEnvelope:
        """处理 ACQUIRE_REQUEST.

        行为:
        - 校验 envelope.message_kind == ACQUIRE_REQUEST (调方负责)
        - 校验 resource 在 config 中
        - idempotency cache 命中 → 返回缓存响应
        - 配额满 → DENIED + QUEUE_FULL
        - 配额未满 → 分配 lease (UUID) + REMOTE_GRANTED

        Raises:
            ClusterResourceNotConfigured: resource 未在 config 中
            ClusterServerError: Server 未 ready / 超 max_inflight
        """
        token = await self._enter()
        try:
            self._stats["acquire_total"] += 1
            # 1. 校验 resource 存在 (defence-in-depth; 启动期已 fail-fast)
            if envelope.resource not in self._lease_store.known_resources():
                raise ClusterResourceNotConfigured(
                    f"resource {envelope.resource!r} not configured",
                    code="RESOURCE_NOT_CONFIGURED",
                )
            # 2. idempotency cache 查
            cached = await self._idempotency.get(
                envelope.request_id, envelope.instance_id, envelope.startup_epoch
            )
            if cached is not None:
                self._stats["idempotency_hits"] += 1
                # 重建 envelope (cached 是 dict; 按 cached 的 message_kind 还原)
                return _envelope_from_cached(cached)
            # 3. 配额未满 → 分配 lease
            now_ns = self._clock()
            lease = await self._lease_store.acquire(
                resource=envelope.resource,
                permits=envelope.permits,
                instance_id=envelope.instance_id,
                startup_epoch=envelope.startup_epoch,
                now_ns=now_ns,
            )
            if lease is None:
                # 配额满
                self._stats["acquire_denied"] += 1
                response = _make_envelope(
                    request_id=envelope.request_id,
                    instance_id=envelope.instance_id,
                    startup_epoch=envelope.startup_epoch,
                    resource=envelope.resource,
                    permits=envelope.permits,
                    deadline_ns=envelope.deadline_ns,
                    message_kind=ClusterMessageKind.ACQUIRE_RESPONSE,
                    payload={
                        "decision": "DENIED",
                        "lease_id": None,
                        "lease_expires_at": None,
                        "permits_granted": None,
                        "retry_after_ns": 1_000_000,  # 1 ms hint
                        "deny_reason": ClusterDenyReason.QUEUE_FULL.value,
                    },
                    now_ns=now_ns,
                )
            else:
                self._stats["acquire_granted"] += 1
                response = _make_envelope(
                    request_id=envelope.request_id,
                    instance_id=envelope.instance_id,
                    startup_epoch=envelope.startup_epoch,
                    resource=envelope.resource,
                    permits=envelope.permits,
                    deadline_ns=envelope.deadline_ns,
                    message_kind=ClusterMessageKind.ACQUIRE_RESPONSE,
                    payload={
                        "decision": "REMOTE_GRANTED",
                        "lease_id": lease.lease_id,
                        "lease_expires_at": _now_iso_utc_micro(lease.expires_at_ns),
                        "permits_granted": lease.permits,
                        "retry_after_ns": 0,
                        "deny_reason": None,
                    },
                    now_ns=now_ns,
                )
            # 4. 写 idempotency cache (使用 envelope dict 形式)
            await self._idempotency.put(
                envelope.request_id,
                envelope.instance_id,
                envelope.startup_epoch,
                _envelope_to_cached(response),
            )
            return response
        finally:
            await self._exit(token)

    # ------------------------------------------------------------------
    # RELEASE handler
    # ------------------------------------------------------------------

    async def handle_release(self, envelope: ClusterTokenEnvelope) -> ClusterTokenEnvelope:
        """处理 RELEASE_REQUEST.

        行为:
        - idempotency cache 命中 → 返回缓存响应
        - ``(lease_id, instance_id, startup_epoch)`` 不匹配 → 抛
          ``ClusterStaleEpoch`` (调用方转 ERROR_RESPONSE)
        - lease 不存在 → 抛 ``ClusterLeaseNotFound`` (调用方转 ERROR_RESPONSE
          + error_code=LEASE_NOT_FOUND)
        - 成功 → 配额恢复 + 返回 ACQUIRE_RESPONSE (语义复用, decision=DENIED +
          deny_reason=LEASE_RELEASED 占位; 1.0 wire 协议不增加新 kind)

        Raises:
            ClusterStaleEpoch: epoch 不匹配
            ClusterLeaseNotFound: lease_id 不存在
            ClusterServerError: Server 未 ready
        """
        token = await self._enter()
        try:
            self._stats["release_total"] += 1
            # 1. idempotency cache 查
            cached = await self._idempotency.get(
                envelope.request_id, envelope.instance_id, envelope.startup_epoch
            )
            if cached is not None:
                self._stats["idempotency_hits"] += 1
                return _envelope_from_cached(cached)
            # 2. 校验 payload (lease_id 存在)
            payload = envelope.payload
            lease_id = payload.get("lease_id")
            if not isinstance(lease_id, str) or not lease_id:
                raise ClusterStaleEpoch(
                    "RELEASE_REQUEST missing lease_id",
                    code="STALE_EPOCH",
                )
            # 3. 校验 epoch
            if not await self._lease_store.has_epoch(
                lease_id, envelope.instance_id, envelope.startup_epoch
            ):
                raise ClusterStaleEpoch(
                    f"RELEASE stale epoch: lease_id={lease_id!r} "
                    f"instance_id={envelope.instance_id!r} "
                    f"startup_epoch={envelope.startup_epoch}",
                    code="STALE_EPOCH",
                )
            # 4. 校验 lease 存在
            lease = await self._lease_store.get(lease_id)
            if lease is None:
                # epoch 通过但 lease 已过期被 scrub; 视为 STALE_EPOCH (正常 race)
                raise ClusterStaleEpoch(
                    f"RELEASE on expired lease: lease_id={lease_id!r}",
                    code="STALE_EPOCH",
                )
            # 5. 释放 (幂等)
            released = await self._lease_store.release(
                lease_id, envelope.instance_id, envelope.startup_epoch
            )
            if not released:
                # 二次确认: race condition
                raise ClusterStaleEpoch(
                    f"RELEASE on gone lease: lease_id={lease_id!r}",
                    code="STALE_EPOCH",
                )
            now_ns = self._clock()
            # 6. 构造响应 (1.0 简化: ACQUIRE_RESPONSE with decision=DENIED +
            # deny_reason=LEASE_RELEASED 占位; 实际 client 不依赖 deny_reason,
            # 仅关心 status=200)
            response = _make_envelope(
                request_id=envelope.request_id,
                instance_id=envelope.instance_id,
                startup_epoch=envelope.startup_epoch,
                resource=envelope.resource,
                permits=envelope.permits,
                deadline_ns=envelope.deadline_ns,
                message_kind=ClusterMessageKind.ACQUIRE_RESPONSE,
                payload={
                    "decision": "DENIED",
                    "lease_id": None,
                    "lease_expires_at": None,
                    "permits_granted": None,
                    "retry_after_ns": 0,
                    "deny_reason": "LEASE_RELEASED",  # 1.0 占位, V1.1 改新 kind
                },
                now_ns=now_ns,
            )
            await self._idempotency.put(
                envelope.request_id,
                envelope.instance_id,
                envelope.startup_epoch,
                _envelope_to_cached(response),
            )
            return response
        finally:
            await self._exit(token)

    # ------------------------------------------------------------------
    # RENEW handler
    # ------------------------------------------------------------------

    async def handle_renew(self, envelope: ClusterTokenEnvelope) -> ClusterTokenEnvelope:
        """处理 RENEW_REQUEST.

        行为:
        - idempotency cache 命中 → 返回缓存响应
        - ``(lease_id, instance_id, startup_epoch)`` 不匹配 → 抛
          ``ClusterStaleEpoch`` (调用方转 ERROR_RESPONSE)
        - lease 不存在 / 已过期 → 抛 ``ClusterLeaseExpired`` (调用方转
          ERROR_RESPONSE + error_code=LEASE_EXPIRED)
        - 成功 → 延长 expires_at_ns + 返回 RENEW_RESPONSE

        Raises:
            ClusterStaleEpoch: epoch 不匹配
            ClusterLeaseExpired: lease 已过期 / 不存在
            ClusterServerError: Server 未 ready
        """
        token = await self._enter()
        try:
            self._stats["renew_total"] += 1
            # 1. idempotency cache 查
            cached = await self._idempotency.get(
                envelope.request_id, envelope.instance_id, envelope.startup_epoch
            )
            if cached is not None:
                self._stats["idempotency_hits"] += 1
                return _envelope_from_cached(cached)
            # 2. 校验 payload
            payload = envelope.payload
            lease_id = payload.get("lease_id")
            extends_for_ns = payload.get("extends_for_ns")
            if not isinstance(lease_id, str) or not lease_id:
                raise ClusterStaleEpoch(
                    "RENEW_REQUEST missing lease_id",
                    code="STALE_EPOCH",
                )
            if not isinstance(extends_for_ns, int) or extends_for_ns <= 0:
                raise ClusterStaleEpoch(
                    f"RENEW_REQUEST invalid extends_for_ns: {extends_for_ns!r}",
                    code="STALE_EPOCH",
                )
            # 3. 校验 epoch
            if not await self._lease_store.has_epoch(
                lease_id, envelope.instance_id, envelope.startup_epoch
            ):
                raise ClusterStaleEpoch(
                    f"RENEW stale epoch: lease_id={lease_id!r}",
                    code="STALE_EPOCH",
                )
            # 4. renew
            now_ns = self._clock()
            new_lease = await self._lease_store.renew(
                lease_id,
                envelope.instance_id,
                envelope.startup_epoch,
                extends_for_ns,
                now_ns=now_ns,
            )
            if new_lease is None:
                # lease 已过期被 scrub; 二次确认
                raise ClusterLeaseExpired(
                    f"renew on expired lease: lease_id={lease_id!r}",
                    code="LEASE_EXPIRED",
                )
            self._stats["renew_extended"] += 1
            response = _make_envelope(
                request_id=envelope.request_id,
                instance_id=envelope.instance_id,
                startup_epoch=envelope.startup_epoch,
                resource=envelope.resource,
                permits=envelope.permits,
                deadline_ns=envelope.deadline_ns,
                message_kind=ClusterMessageKind.RENEW_RESPONSE,
                payload={
                    "decision": "RENEWED",
                    "lease_id": new_lease.lease_id,
                    "lease_expires_at": _now_iso_utc_micro(new_lease.expires_at_ns),
                    "permits_granted": new_lease.permits,
                    "retry_after_ns": 0,
                    "deny_reason": None,
                },
                now_ns=now_ns,
            )
            await self._idempotency.put(
                envelope.request_id,
                envelope.instance_id,
                envelope.startup_epoch,
                _envelope_to_cached(response),
            )
            return response
        finally:
            await self._exit(token)

    # ------------------------------------------------------------------
    # error envelope helper (public, for http_transport use)
    # ------------------------------------------------------------------

    def build_error_envelope(
        self,
        *,
        request_id: str,
        instance_id: str,
        startup_epoch: int,
        resource: str,
        permits: float,
        deadline_ns: int,
        error_code: ClusterErrorCode,
        error_message: str = "",
    ) -> ClusterTokenEnvelope:
        """构造 ERROR_RESPONSE envelope (public helper for http_transport)."""
        now_ns = self._clock()
        message = error_message[:64] if error_message else ""
        return _make_envelope(
            request_id=request_id,
            instance_id=instance_id,
            startup_epoch=startup_epoch,
            resource=resource,
            permits=permits,
            deadline_ns=deadline_ns,
            message_kind=ClusterMessageKind.ERROR_RESPONSE,
            payload={
                "error_code": error_code.value,
                "error_message": message,
            },
            now_ns=now_ns,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _envelope_to_cached(env: ClusterTokenEnvelope) -> dict[str, Any]:
    """``ClusterTokenEnvelope`` → 缓存 dict (JSON-serializable shape)."""
    return {
        "protocol_version": env.protocol_version,
        "message_kind": env.message_kind.value,
        "request_id": env.request_id,
        "instance_id": env.instance_id,
        "startup_epoch": env.startup_epoch,
        "resource": env.resource,
        "permits": env.permits,
        "deadline_ns": env.deadline_ns,
        "client_requested_at": env.client_requested_at,
        "server_received_at": env.server_received_at,
        "payload": dict(env.payload),
    }


def _envelope_from_cached(cached: dict[str, Any]) -> ClusterTokenEnvelope:
    """缓存 dict → ``ClusterTokenEnvelope`` (恢复 ClusterMessageKind enum)."""
    return ClusterTokenEnvelope(
        protocol_version=cached["protocol_version"],
        message_kind=ClusterMessageKind(cached["message_kind"]),
        request_id=cached["request_id"],
        instance_id=cached["instance_id"],
        startup_epoch=cached["startup_epoch"],
        resource=cached["resource"],
        permits=cached["permits"],
        deadline_ns=cached["deadline_ns"],
        client_requested_at=cached["client_requested_at"],
        server_received_at=cached["server_received_at"],
        payload=dict(cached["payload"]),
    )


__all__ = [
    "TokenServer",
    "TokenServerState",
    "TokenServerStats",
]
