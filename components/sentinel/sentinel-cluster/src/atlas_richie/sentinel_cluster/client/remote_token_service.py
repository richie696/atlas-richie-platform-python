"""Atlas Richie Sentinel Cluster — Client ``RemoteTokenService`` (M6.3.4).

中文
----
``RemoteTokenService`` 是 ``TokenService`` Port 的**远程**实现, 把同步
``acquire(resource, permits)`` / ``release(token)`` 翻译成
``ClusterTokenEnvelope`` over HTTP/1.1 + JSON wire protocol。

**实现要点**:

- 同步 facade: 内部 ``asyncio.new_event_loop()`` + ``loop.run_until_complete(...)``
  一次, **不**复用 Engine event loop (M6.7 决策: 跨线程 / 跨 loop 行为
  未定义, 1.x 不支持).
- 鉴权: ``X-Atlas-Cluster-Token`` header (1.0 shared secret, 跟 Server 配对)
- 重试: 同一 ``request_id`` 最多 3 次, exponential backoff (50ms / 200ms / 1s)
- 错误翻译 (协议 §6):
    * ``PROTOCOL_VERSION_MISMATCH`` / ``MALFORMED_ENVELOPE`` / ``UNKNOWN_MESSAGE_KIND``
      → ``deny_reason=REMOTE_UNAVAILABLE`` + ClusterFailurePolicy 决策
    * ``STALE_EPOCH`` → log warn, **不**抛异常 (正常 race 现象)
    * ``LEASE_NOT_FOUND`` / ``LEASE_EXPIRED`` → log warn, release 业务继续
    * ``RESOURCE_NOT_CONFIGURED`` → ``deny_reason=RESOURCE_NOT_CONFIGURED``
    * ``SERVER_OVERLOADED`` → ``deny_reason=SERVER_OVERLOADED`` + 决策
    * ``INTERNAL_ERROR`` → retry 一次, 仍失败按 ClusterFailurePolicy
- ``Token.lease_id`` / ``Token.owner_epoch`` 透传 Server 字段
  (Client 不可伪造).

**反例** (1.0 拒绝):

- ❌ 复用 Engine event loop (M6.7 决策)
- ❌ ``asgiref.sync_to_async`` / ``nest_asyncio`` / 线程池 (1.0 不引入)
- ❌ 跨 call 共享 backoff 状态 (stateless 重试)
- ❌ release 抛异常 (永远 best-effort, 失败仅 log warn)

English
--------
``RemoteTokenService`` is the **remote** implementation of ``TokenService``
Port, translating sync ``acquire(resource, permits)`` / ``release(token)``
into ``ClusterTokenEnvelope`` over HTTP/1.1 + JSON wire protocol.

Implementation:

- Sync facade: internal ``asyncio.new_event_loop()`` + ``loop.run_until_complete(...)``
  one-shot, **not** reusing Engine event loop (M6.7 decision: cross-thread /
  cross-loop behavior undefined, 1.x unsupported).
- Auth: ``X-Atlas-Cluster-Token`` header (1.0 shared secret, paired with
  Server).
- Retry: same ``request_id`` at most 3 times, exponential backoff
  (50ms / 200ms / 1s).
- Error translation (protocol §6):
    * ``PROTOCOL_VERSION_MISMATCH`` / ``MALFORMED_ENVELOPE`` / ``UNKNOWN_MESSAGE_KIND``
      → ``deny_reason=REMOTE_UNAVAILABLE`` + ClusterFailurePolicy
    * ``STALE_EPOCH`` → log warn, **no** raise (normal race)
    * ``LEASE_NOT_FOUND`` / ``LEASE_EXPIRED`` → log warn, release business continues
    * ``RESOURCE_NOT_CONFIGURED`` → ``deny_reason=RESOURCE_NOT_CONFIGURED``
    * ``SERVER_OVERLOADED`` → ``deny_reason=SERVER_OVERLOADED`` + decision
    * ``INTERNAL_ERROR`` → retry once, still fail → ClusterFailurePolicy
- ``Token.lease_id`` / ``Token.owner_epoch`` pass through Server fields
  (Client cannot forge).

Anti-patterns (1.0 forbidden):

- ❌ Reusing Engine event loop (M6.7)
- ❌ ``asgiref.sync_to_async`` / ``nest_asyncio`` / thread pool (1.0 no 3rd-party)
- ❌ Cross-call shared backoff state (stateless retry)
- ❌ release raising (always best-effort, failure only log warn)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from atlas_richie.contracts.cluster.v1 import (
    ClusterDenyReason,
    ClusterErrorCode,
    ClusterMessageKind,
    ClusterTokenEnvelope,
    ISO_8601_UTC_MICRO,
    PROTOCOL_VERSION,
)
from atlas_richie.sentinel.ports.token import (
    ClusterFailurePolicy,
    LocalTokenService,
    Token,
    TokenDecision,
    TokenDenyReason,
    TokenResponse,
    TokenService,
)

from ..config import ClusterTokenConfig
from ..errors import (
    ClusterConfigError,
    ClusterServerError,
    ClusterStaleEpoch,
)
from .http_transport_client import HttpTransportClient, _TransportError
from .policy import decide_failure
from .retry import MAX_RETRIES, backoff_for_attempt, should_retry

_log = logging.getLogger("atlas_richie.sentinel_cluster.client.remote_token_service")


# ---------------------------------------------------------------------------
# Public value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClientIdentity:
    """Client 端唯一身份 (frozen slots, 1.0 公开).

    Attributes:
        instance_id: UUID v4 字符串, Client 进程唯一 (重启用同)
        startup_epoch: 进程启动期序号 (单调递增; 旧 epoch 迟到 release
            / renew 通过 Server 端 epoch_index fencing 静默忽略)
    """

    instance_id: str
    startup_epoch: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.instance_id, str) or not self.instance_id:
            raise ClusterConfigError(
                "ClientIdentity.instance_id must be non-empty str",
                code="CONFIG_ERROR",
            )
        if not isinstance(self.startup_epoch, int) or self.startup_epoch < 0:
            raise ClusterConfigError(
                f"ClientIdentity.startup_epoch must be non-negative int, got {self.startup_epoch!r}",
                code="CONFIG_ERROR",
            )


# ---------------------------------------------------------------------------
# RemoteTokenService
# ---------------------------------------------------------------------------


def _now_iso_utc_micro(now_ns: int) -> str:
    """``now_ns`` → ISO 8601 UTC microsecond 字符串 (协议 §3.3 格式)."""
    dt = datetime.fromtimestamp(now_ns / 1_000_000_000, tz=timezone.utc)
    return dt.strftime(ISO_8601_UTC_MICRO)


def _make_request_id() -> str:
    """生成 UUID v4 string 作为 ``request_id`` (协议 §3.3)."""
    return str(uuid.uuid4())


def _parse_iso_utc_micro(s: str | None) -> int:
    """ISO 8601 UTC microsecond 字符串 → 纳秒 (``time.time_ns()`` 基准).

    失败返回 0 (defensive; 不抛异常, 1.0 容错).
    """
    if not isinstance(s, str) or not s:
        return 0
    try:
        # 形如 "2026-09-13T19:25:02.123456Z"
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    except (ValueError, TypeError):
        return 0


class RemoteTokenService:
    """``TokenService`` Port 的远程 Proxy (M6.3.4, 1.0 公开).

    同步 ``acquire`` / ``release`` facade 跟 ``LocalTokenService`` 同形,
    可直接替换 Engine 的 ``token_service`` 字段 (M6.3.7 contract suite 验证).

    Threading:
        内部用 ``asyncio.new_event_loop()`` 一次, **不**复用 Engine event
        loop (M6.7 决策). 同步 facade 跟 Engine 主线程同 thread OK; 跨线程
        行为 1.x 未定义.
    """

    def __init__(
        self,
        config: ClusterTokenConfig,
        *,
        identity: ClientIdentity,
        local_fallback: LocalTokenService | None = None,
    ) -> None:
        """初始化 ``RemoteTokenService``.

        Args:
            config: Server 配置 (含 ``auth_secret`` / ``server_addresses`` /
                ``failure_policy_per_resource``)
            identity: Client 端身份 (frozen, frozen slots)
            local_fallback: ``ClusterFailurePolicy.LOCAL_FALLBACK`` 用的
                ``LocalTokenService`` 实例; 其他 policy 时**不**使用, 可
                传 ``None``. 1.0 接受限制: 没传且触发 LOCAL_FALLBACK →
                降级 FAIL_CLOSED 行为 (见 ``policy.decide_failure``).
        """
        if not isinstance(config, ClusterTokenConfig):
            raise ClusterConfigError(
                "config must be ClusterTokenConfig", code="CONFIG_ERROR"
            )
        if not isinstance(identity, ClientIdentity):
            raise ClusterConfigError(
                "identity must be ClientIdentity", code="CONFIG_ERROR"
            )
        if not config.server_addresses:
            raise ClusterConfigError(
                "RemoteTokenService requires config.server_addresses non-empty "
                "(use ClusterTokenMode.CLIENT_ONLY or supply server_addresses)",
                code="CONFIG_ERROR",
            )
        if local_fallback is not None and not isinstance(local_fallback, LocalTokenService):
            raise ClusterConfigError(
                f"local_fallback must be LocalTokenService, got {type(local_fallback).__name__}",
                code="CONFIG_ERROR",
            )
        self._config = config
        self._identity = identity
        self._local_fallback = local_fallback
        # 1.0 简化: 只连第 1 个 server_addresses (M6.3.x 未来支持 HA / load-balance)
        self._server_address = config.server_addresses[0]
        self._transport = HttpTransportClient(
            server_address=self._server_address,
            auth_secret=config.auth_secret,
            request_timeout_s=5.0,  # 1.0 简化: 5 s
            connect_timeout_s=1.0,  # 1.0 简化: 1 s
        )
        self._started = False
        self._closed = False
        # 运行时统计 (1.0 stub, 完整 M6.5.1-6 实施)
        self._stats: dict[str, int] = {
            "acquire_total": 0,
            "acquire_remote_granted": 0,
            "acquire_denied": 0,
            "acquire_fail_open": 0,
            "acquire_local_fallback": 0,
            "acquire_fail_closed": 0,
            "release_total": 0,
            "release_stale_epoch": 0,
            "release_lease_expired": 0,
            "retries": 0,
        }

    # ------------------------------------------------------------------
    # 1.0 公开 lifecycle API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """初始化 transport (1.0 简化: 单连接 + lazy, start 仅 mark)."""
        if self._closed:
            raise ClusterServerError(
                "RemoteTokenService already closed", code="LIFECYCLE_ERROR"
            )
        self._started = True

    async def aclose(self) -> None:
        """关闭 transport + 释放资源 (1.0 简化: 单连接 + 幂等)."""
        if self._closed:
            return  # 幂等
        self._closed = True
        try:
            await self._transport.close()
        except Exception:  # pragma: no cover (defensive)
            pass

    # ------------------------------------------------------------------
    # 1.0 公开 TokenService Port 同步 facade
    # ------------------------------------------------------------------

    def acquire(self, resource: str, permits: float) -> TokenResponse:
        """同步 acquire facade (1.0 跟 ``LocalTokenService.acquire`` 同形).

        Args:
            resource: 资源名
            permits: 申请 permit 数 (≥ 0)

        Returns:
            ``TokenResponse`` (必填 ``decision`` + ``token`` / ``deny_reason``)

        Raises:
            ClusterServerError: Client 端 / wire 不可恢复错 (启动 fail-fast
                配套, 1.0 接受业务受影响)
            ClusterConfigError: 配置错 (启动期已 fail-fast, 单测少见)
        """
        self._stats["acquire_total"] += 1
        # 启动期未 start 或已 close → 走 policy 决策 (跟 Server 不可达一致)
        if not self._started or self._closed:
            return self._acquire_unavailable_decision(
                resource, permits, reason="client not started or closed"
            )
        # 1. 构造 REQUEST envelope
        policy = self._policy_for(resource)
        request_id = _make_request_id()
        now_ns = time.time_ns()
        deadline_ns = self._derive_deadline_ns()
        envelope = self._build_acquire_envelope(
            resource=resource,
            permits=permits,
            request_id=request_id,
            deadline_ns=deadline_ns,
            now_ns=now_ns,
        )
        # 2. 同步 facade: 起一次性 event loop, 不复用 Engine event loop
        try:
            response_envelope = self._run_async(self._acquire_with_retry(envelope))
        except ClusterStaleEpoch:
            # STALE_EPOCH 在 ``_acquire_with_retry`` 内部已转 DENIED
            # 兜底: 业务受影响
            return self._acquire_unavailable_decision(
                resource, permits, reason="stale_epoch_unhandled"
            )
        except (ClusterServerError, OSError) as e:
            # 不可恢复: 走 policy 决策
            return self._acquire_unavailable_decision(
                resource, permits, reason=f"server error: {type(e).__name__}"
            )
        # 3. 翻译 response envelope → TokenResponse
        return self._translate_acquire_response(
            response_envelope, resource=resource, permits=permits, now_ns=now_ns,
        )

    def release(self, token: Token | None) -> None:
        """同步 release facade (1.0 永远 best-effort, **不**抛异常).

        ``Token.lease_id is None`` → 本地 stub (FAIL_OPEN), 1.0 不发到 Server
        (避免"本地 stub 释放 server 配额"逻辑错位).

        ``token is None`` (e.g. acquire 返 DENIED 时业务误调 release) → 静默 no-op.

        Args:
            token: ``acquire(...)`` 返回的 ``Token`` (含 ``lease_id`` /
                ``owner_epoch``) 或 None
        """
        # release 永远不抛异常 (业务继续), 失败仅 log warn
        try:
            self._do_release(token)  # type: ignore[arg-type]
        except Exception as e:
            _log.warning(
                "cluster.release.unexpected_error: error=%s",
                type(e).__name__,
            )

    # ------------------------------------------------------------------
    # 内部 helpers
    # ------------------------------------------------------------------

    def _do_release(self, token: Token) -> None:
        """release 主逻辑 (catch 所有异常, 不外抛)."""
        self._stats["release_total"] += 1
        # 0. token=None: 防御性, 业务上 acquire DENIED 时不应调 release
        if token is None:
            _log.debug("cluster.release.skip_none_token")
            return
        # 1. 本地 stub (FAIL_OPEN) 或 LocalTokenService token: 1.0 不发到 Server
        if token.lease_id is None:
            _log.debug("cluster.release.skip_stub_token: resource=%s", token.resource)
            return
        # 2. 启动期未 start 或已 close: 业务继续 (release 永远 best-effort)
        if not self._started or self._closed:
            _log.debug(
                "cluster.release.skip_not_started: lease_id=%s",
                token.lease_id,
            )
            return
        # 3. 构造 RELEASE_REQUEST envelope
        now_ns = time.time_ns()
        envelope = self._build_release_envelope(
            resource=token.resource,
            permits=token.permits,
            lease_id=token.lease_id,
            deadline_ns=self._derive_deadline_ns(),
            now_ns=now_ns,
        )
        # 4. 同步 facade: 1.0 简化不 retry (release 永远 best-effort)
        try:
            response_envelope = self._run_async(self._transport.send(envelope))
        except Exception as e:
            _log.warning(
                "cluster.release.transport_error: lease_id=%s error=%s",
                token.lease_id,
                type(e).__name__,
            )
            return
        # 5. 翻译 response (仅 STALE_EPOCH / LEASE_NOT_FOUND / LEASE_EXPIRED 静默)
        if response_envelope.message_kind is ClusterMessageKind.ERROR_RESPONSE:
            error_code_str = response_envelope.payload.get("error_code")
            try:
                error_code = ClusterErrorCode(error_code_str) if error_code_str else None
            except ValueError:
                error_code = None
            if error_code is ClusterErrorCode.STALE_EPOCH:
                self._stats["release_stale_epoch"] += 1
                _log.debug(
                    "cluster.release.stale_epoch_ignored: lease_id=%s",
                    token.lease_id,
                )
                return
            if error_code is ClusterErrorCode.LEASE_NOT_FOUND:
                # lease 已被 Server 端 scrub (e.g. 重启 / 显式 release)
                _log.debug(
                    "cluster.release.lease_not_found_ignored: lease_id=%s",
                    token.lease_id,
                )
                return
            if error_code is ClusterErrorCode.LEASE_EXPIRED:
                self._stats["release_lease_expired"] += 1
                _log.debug(
                    "cluster.release.lease_expired_ignored: lease_id=%s",
                    token.lease_id,
                )
                return
            # 其他 ERROR_RESPONSE (e.g. SERVER_OVERLOADED) 走 best-effort 静默
            _log.debug(
                "cluster.release.error_ignored: lease_id=%s code=%s",
                token.lease_id,
                error_code_str,
            )
            return
        # 成功响应 (ACQUIRE_RESPONSE / RENEW_RESPONSE 复用语义, 1.0 wire 简化)
        _log.debug("cluster.release.ok: lease_id=%s", token.lease_id)

    # ------------------------------------------------------------------
    # 同步 facade → async 桥
    # ------------------------------------------------------------------

    def _run_async(self, coro: Any) -> Any:
        """同步 facade: 起一次性 event loop, ``run_until_complete`` 一次.

        **不**复用 Engine event loop (M6.7 决策).
        **不**用 ``asyncio.run`` (其内部复用策略不透明).
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            try:
                loop.close()
            except Exception:  # pragma: no cover (defensive)
                pass

    # ------------------------------------------------------------------
    # acquire retry + 错误翻译
    # ------------------------------------------------------------------

    async def _acquire_with_retry(
        self, envelope: ClusterTokenEnvelope
    ) -> ClusterTokenEnvelope:
        """同一 request_id 最多 retry 3 次, exponential backoff.

        行为契约:
        - 200 OK + ACQUIRE_RESPONSE: 直接返回 (成功 / 业务 DENIED 都 OK)
        - 200 OK + RENEW_RESPONSE: 不期待 (acquire 不发 renew), 视作
          wire 协议 bug → ClusterServerError
        - 200 OK + ERROR_RESPONSE: 不期待 (acquire 不发会让 Server 返
          ERROR_RESPONSE, 业务错应该走 4xx), 视作 wire 协议 bug
        - 4xx (含 401): 业务错, **不** retry, 走 policy 决策 (调用方处理)
        - 5xx: 内部错, retry 一次, 仍失败走 policy (调用方处理)
        - 网络错 / 超时: retry 3 次, 仍失败抛 ``_TransportError`` 给调用方
        """
        last_exc: BaseException | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await self._transport.send(envelope)
                # 200 OK + 业务 envelope
                if response.message_kind in (
                    ClusterMessageKind.ACQUIRE_RESPONSE,
                    ClusterMessageKind.RENEW_RESPONSE,
                ):
                    return response
                if response.message_kind is ClusterMessageKind.ERROR_RESPONSE:
                    # acquire 不期待 ERROR_RESPONSE (业务错应该走 4xx),
                    # 视作 wire 协议 bug, **不** retry
                    raise ClusterServerError(
                        f"unexpected ERROR_RESPONSE on acquire: "
                        f"{response.payload.get('error_code')!r}",
                        code="WIRE_UNEXPECTED_ERROR",
                    )
                # 未知 message_kind: 视作 wire bug
                raise ClusterServerError(
                    f"unexpected message_kind on acquire: {response.message_kind!r}",
                    code="WIRE_UNEXPECTED_KIND",
                )
            except _TransportUnretryable:
                # 4xx 业务错: 不 retry, 直接抛给调用方
                raise
            except _TransportInternalError:
                # 5xx: 内部错, retry 一次 (attempt 0 → 0.05s, attempt 1 → 0.20s)
                last_exc = ClusterServerError(
                    "server internal error after retries",
                    code="SERVER_INTERNAL_AFTER_RETRY",
                )
                if should_retry(attempt + 1):
                    self._stats["retries"] += 1
                    await asyncio.sleep(backoff_for_attempt(attempt + 1))
                    continue
                raise last_exc
            except _TransportError as e:
                # 4xx/5xx/网络错/超时: 走 retry 策略
                # - status 5xx: 内部错 (retry 一次)
                # - status 4xx: 业务错 (注: 1.0 简化不区分, retry 一次)
                # - 无 status (网络/超时): retry 3 次
                if e.status is not None and 400 <= e.status < 500:
                    # 4xx 业务错: 不 retry, 抛给调用方
                    raise
                last_exc = e
                if should_retry(attempt + 1):
                    self._stats["retries"] += 1
                    await asyncio.sleep(backoff_for_attempt(attempt + 1))
                    continue
                # 3 次 retry 后仍失败 → 抛给调用方走 policy 决策
                raise ClusterServerError(
                    f"acquire transport error after {MAX_RETRIES} retries: "
                    f"{e.reason!r}",
                    code="TRANSPORT_ERROR_AFTER_RETRY",
                ) from e
            except (
                asyncio.TimeoutError,
                ConnectionRefusedError,
                OSError,
            ) as e:
                # 网络错 / 超时 (没被 _TransportError 包装): retry 3 次
                last_exc = e
                if should_retry(attempt + 1):
                    self._stats["retries"] += 1
                    await asyncio.sleep(backoff_for_attempt(attempt + 1))
                    continue
                # 3 次 retry 后仍失败 → 抛给调用方走 policy 决策
                raise ClusterServerError(
                    f"acquire transport error after {MAX_RETRIES} retries: "
                    f"{type(e).__name__}",
                    code="TRANSPORT_ERROR_AFTER_RETRY",
                ) from e
        # 不可达
        raise ClusterServerError(
            "acquire retry loop exhausted unexpectedly",
            code="RETRY_LOOP_BUG",
        ) from last_exc

    def _translate_acquire_response(
        self,
        response: ClusterTokenEnvelope,
        *,
        resource: str,
        permits: float,
        now_ns: int,
    ) -> TokenResponse:
        """把 Server ACQUIRE_RESPONSE 翻译成 ``TokenResponse``.

        字段映射 (Server 端格式见 ``token_server.handle_acquire``):
        - ``decision`` ("REMOTE_GRANTED" / "DENIED")
        - ``lease_id`` (str | None)
        - ``lease_expires_at`` (ISO 8601 str | None) → 转 ``ttl_ns``
        - ``permits_granted`` (float | None)
        - ``retry_after_ns`` (int) → 透传
        - ``deny_reason`` (str | None)
        """
        payload = response.payload
        decision_str = payload.get("decision")
        if decision_str == "REMOTE_GRANTED":
            lease_id = payload.get("lease_id")
            if not isinstance(lease_id, str) or not lease_id:
                # Server 返回 grant 但 lease_id 缺失 = wire bug
                _log.error(
                    "cluster.acquire.wire_bug_missing_lease_id: resource=%s",
                    resource,
                )
                return self._acquire_unavailable_decision(
                    resource, permits, reason="wire_bug_missing_lease_id"
                )
            expires_at_ns = _parse_iso_utc_micro(payload.get("lease_expires_at"))
            ttl_ns = max(0, expires_at_ns - now_ns) if expires_at_ns > 0 else 0
            permits_granted = payload.get("permits_granted")
            if not isinstance(permits_granted, (int, float)):
                permits_granted = permits
            retry_after_ns = payload.get("retry_after_ns", 0) or 0
            self._stats["acquire_remote_granted"] += 1
            return TokenResponse(
                decision=TokenDecision.REMOTE_GRANTED,
                token=Token(
                    resource=resource,
                    permits=float(permits_granted),
                    issued_at_ns=now_ns,
                    ttl_ns=ttl_ns,
                    lease_id=lease_id,
                    owner_epoch=self._identity.startup_epoch,
                ),
                deny_reason=None,
                wait_ns=0,
                retry_after_ns=int(retry_after_ns) if isinstance(retry_after_ns, int) else 0,
            )
        if decision_str == "DENIED":
            deny_reason_str = payload.get("deny_reason")
            retry_after_ns = payload.get("retry_after_ns", 0) or 0
            deny_reason = self._map_deny_reason(deny_reason_str)
            self._stats["acquire_denied"] += 1
            return TokenResponse(
                decision=TokenDecision.DENIED,
                token=None,
                deny_reason=deny_reason,
                wait_ns=0,
                retry_after_ns=int(retry_after_ns) if isinstance(retry_after_ns, int) else 0,
            )
        # 未知 decision: wire bug
        _log.error(
            "cluster.acquire.wire_bug_unknown_decision: resource=%s decision=%s",
            resource,
            decision_str,
        )
        return self._acquire_unavailable_decision(
            resource, permits, reason=f"wire_bug_unknown_decision:{decision_str!r}"
        )

    def _acquire_unavailable_decision(
        self, resource: str, permits: float, *, reason: str
    ) -> TokenResponse:
        """Server 不可达 / wire 不可恢复错: 按 per-resource ClusterFailurePolicy 决策."""
        policy = self._policy_for(resource)
        decision = decide_failure(
            resource=resource,
            permits=permits,
            policy=policy,
            reason=reason,
            local_fallback=self._local_fallback,
        )
        if decision.fail_open:
            self._stats["acquire_fail_open"] += 1
        elif decision.local_fallback:
            self._stats["acquire_local_fallback"] += 1
        else:
            self._stats["acquire_fail_closed"] += 1
        return decision.response

    def _policy_for(self, resource: str) -> ClusterFailurePolicy:
        """查 per-resource 失败策略; 缺失按 1.0 fail-closed 默认."""
        policy = self._config.failure_policy_per_resource.get(resource)
        if policy is None:
            # 1.0 接受: resource 未配 policy → 默认 fail-closed (跟 Server 启动期
            # fail-fast 一致, Client 端用同样保守策略, 避免静默放行)
            return ClusterFailurePolicy.FAIL_CLOSED
        return policy

    @staticmethod
    def _map_deny_reason(reason_str: Any) -> TokenDenyReason:
        """把 Server 返回的 ``deny_reason`` 字符串翻译成 ``TokenDenyReason`` enum.

        已知 Server 返回 ``ClusterDenyReason`` 4 选 1 (QUEUE_FULL / RATE_LIMITED /
        SHUTTING_DOWN / STALE_EPOCH / UNKNOWN); Client 端 7 选 1.
        """
        if reason_str == ClusterDenyReason.QUEUE_FULL.value:
            return TokenDenyReason.QUEUE_FULL
        if reason_str == ClusterDenyReason.RATE_LIMITED.value:
            return TokenDenyReason.RATE_LIMITED
        if reason_str == ClusterDenyReason.SHUTTING_DOWN.value:
            return TokenDenyReason.SHUTTING_DOWN
        if reason_str == ClusterDenyReason.STALE_EPOCH.value:
            return TokenDenyReason.REMOTE_UNAVAILABLE
        # "LEASE_RELEASED" (1.0 占位) / "LEASE_EXPIRED" / "LEASE_NOT_FOUND" /
        # 其它 → 保守归类 REMOTE_UNAVAILABLE (避免映射到不存在的 enum)
        return TokenDenyReason.REMOTE_UNAVAILABLE

    # ------------------------------------------------------------------
    # envelope 构造
    # ------------------------------------------------------------------

    def _build_acquire_envelope(
        self,
        *,
        resource: str,
        permits: float,
        request_id: str,
        deadline_ns: int,
        now_ns: int,
    ) -> ClusterTokenEnvelope:
        return ClusterTokenEnvelope(
            protocol_version=PROTOCOL_VERSION,
            message_kind=ClusterMessageKind.ACQUIRE_REQUEST,
            request_id=request_id,
            instance_id=self._identity.instance_id,
            startup_epoch=self._identity.startup_epoch,
            resource=resource,
            permits=permits,
            deadline_ns=deadline_ns,
            client_requested_at=_now_iso_utc_micro(now_ns),
            server_received_at=_now_iso_utc_micro(now_ns),
            payload={
                "rule_version_epoch": 1,
                "rule_version_revision": 0,
                "rule_version_checksum": "sha256:" + "a" * 64,
                "priority": 0,
            },
        )

    def _build_release_envelope(
        self,
        *,
        resource: str,
        permits: float,
        lease_id: str,
        deadline_ns: int,
        now_ns: int,
    ) -> ClusterTokenEnvelope:
        return ClusterTokenEnvelope(
            protocol_version=PROTOCOL_VERSION,
            message_kind=ClusterMessageKind.RELEASE_REQUEST,
            request_id=_make_request_id(),
            instance_id=self._identity.instance_id,
            startup_epoch=self._identity.startup_epoch,
            resource=resource,
            permits=permits,
            deadline_ns=deadline_ns,
            client_requested_at=_now_iso_utc_micro(now_ns),
            server_received_at=_now_iso_utc_micro(now_ns),
            payload={
                "lease_id": lease_id,
                "permits_released": permits,
            },
        )

    def _derive_deadline_ns(self) -> int:
        """单 request deadline 纳秒 (1.0 简化: 5 s)."""
        return 5_000_000  # 5 ms in 1.0 简化; 实际业务可注入 config


# ---------------------------------------------------------------------------
# 内部 transport error 类型 (供 retry 策略分类)
# ---------------------------------------------------------------------------


class _TransportUnretryable(Exception):
    """4xx 业务错: 不 retry, 直接给 policy 决策.

    实际通过 ``ClusterServerError`` 抛, 走 ``except`` 路径.
    """


class _TransportInternalError(Exception):
    """5xx 内部错: 内部 retry 一次.

    实际通过 ``ClusterServerError`` 抛, 走 ``except`` 路径.
    """


__all__ = ["ClientIdentity", "RemoteTokenService"]
