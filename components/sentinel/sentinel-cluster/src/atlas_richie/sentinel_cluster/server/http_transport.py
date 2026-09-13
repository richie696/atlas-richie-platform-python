"""Atlas Richie Sentinel Cluster — HTTP/1.1 + JSON Transport (M6.3.3 + M6.3.4 决策).

中文
----
Server 端 HTTP/1.1 + JSON 传输层, 手动解析 HTTP request line + Content-Length
头。**不**引入 aiohttp / httpx / gRPC (主包 0 依赖 + Cluster wheel 也 0
3rd-party, M6.3.4 决策)。

**协议**:
- 单连接 + 单请求 + 单响应 (request/response 模式, 无 server-push)
- 鉴权: HTTP header ``X-Atlas-Cluster-Token: <secret>`` (1.0 shared secret)
- 缺失 / 错误 secret → 401 + ERROR_RESPONSE + INTERNAL_ERROR
- envelope size ≤ 8 KB (协议 §3.4)
- Body: 严格 JSON, ``decode_envelope`` 严格校验

**线程模型**: 单 asyncio event loop, ``asyncio.start_server`` accept,
每个连接起一个 task; 读 → 路由 → 写 → 关闭。

**关键决策**:
- 手动 HTTP 解析, 不依赖标准库 ``http.server`` (后者是同步 + 单线程)
- Connection: close (单请求响应后立即关闭, 1.0 简化)
- 鉴权失败 / 解码失败 / 内部错误都返回 ERROR_RESPONSE 形式 (除 401)
- 401 是 HTTP 状态码 + 简单 text body (避免 1.0 引入 HTML 错误页)

English
--------
Server-side HTTP/1.1 + JSON transport, hand-rolled HTTP request line +
Content-Length header parsing. **No** aiohttp / httpx / gRPC (main wheel
0 deps + Cluster wheel also 0 3rd-party, M6.3.4 decision).

Protocol:
- Single connection + single request + single response (no server-push)
- Auth: HTTP header ``X-Atlas-Cluster-Token: <secret>`` (1.0 shared secret)
- Missing / wrong secret → 401 + ERROR_RESPONSE + INTERNAL_ERROR
- envelope size ≤ 8 KB (protocol §3.4)
- Body: strict JSON, ``decode_envelope`` strict validation

Threading model: single asyncio event loop, ``asyncio.start_server``
accepts, one task per connection; read → route → write → close.

Key decisions:
- Hand-rolled HTTP parsing, no stdlib ``http.server`` (which is sync + single-thread)
- Connection: close (close immediately after single request/response, 1.0 simplification)
- Auth failure / decode failure / internal errors all return ERROR_RESPONSE
  form (except 401)
- 401 is HTTP status + simple text body (1.0 doesn't ship HTML error pages)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from atlas_richie.contracts.cluster.v1 import (
    ClusterErrorCode,
    ClusterMessageKind,
    ClusterProtocolError,
    ClusterTokenEnvelope,
    decode_envelope,
    encode_envelope,
)

from ..errors import (
    ClusterConfigError,
    ClusterLeaseExpired,
    ClusterLeaseNotFound,
    ClusterResourceNotConfigured,
    ClusterServerError,
    ClusterStaleEpoch,
)
from .token_server import TokenServer

_log = logging.getLogger("atlas_richie.sentinel_cluster.http_transport")

# HTTP status text
_STATUS_TEXT = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    413: "Payload Too Large",
    500: "Internal Server Error",
    503: "Service Unavailable",
}

_AUTH_HEADER = "X-Atlas-Cluster-Token"
_CONTENT_TYPE_JSON = "application/json; charset=utf-8"


class HttpTransport:
    """HTTP/1.1 + JSON transport for TokenServer (M6.3.3).

    1.0 公开 API:
    - ``await transport.start(bind_address)``
    - ``await transport.stop()``
    - ``transport.token_server`` (注入的 TokenServer)
    - ``transport.bound_port`` (实际绑定的端口, ``port=0`` 时有用)
    """

    def __init__(
        self,
        token_server: TokenServer,
        *,
        max_payload_bytes: int,
        read_timeout_s: float = 30.0,
    ) -> None:
        """初始化 HTTP transport.

        Args:
            token_server: 注入的 TokenServer (handler 来源)
            max_payload_bytes: envelope size 上限 (协议 §3.4)
            read_timeout_s: 单请求读超时 (秒)
        """
        if not isinstance(max_payload_bytes, int) or max_payload_bytes <= 0:
            raise ClusterConfigError(
                f"max_payload_bytes must be positive int, got {max_payload_bytes!r}",
                code="CONFIG_ERROR",
            )
        self._token_server = token_server
        self._max_payload_bytes = max_payload_bytes
        self._read_timeout_s = read_timeout_s
        self._server: asyncio.base_events.Server | None = None
        self._bound_port: int | None = None
        self._bound_host: str | None = None
        self._active_connections: set[asyncio.Task[None]] = set()
        self._closed = False

    @property
    def token_server(self) -> TokenServer:
        return self._token_server

    @property
    def bound_port(self) -> int | None:
        return self._bound_port

    @property
    def bound_host(self) -> str | None:
        return self._bound_host

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def start(self, bind_address: str) -> None:
        """启动 HTTP server, 监听 ``bind_address`` (e.g. "0.0.0.0:8765")."""
        if self._closed:
            raise ClusterServerError(
                "transport already closed", code="LIFECYCLE_ERROR"
            )
        host, port = _parse_bind(bind_address)
        self._server = await asyncio.start_server(
            self._handle_connection,
            host=host,
            port=port,
        )
        # 拿真实绑定端口 (port=0 时)
        socks = self._server.sockets or []
        if socks:
            self._bound_host, self._bound_port = socks[0].getsockname()[:2]
        else:  # pragma: no cover (defensive)
            self._bound_host = host
            self._bound_port = port
        _log.info("HttpTransport listening on %s:%d", self._bound_host, self._bound_port)

    async def stop(self) -> None:
        """停止 HTTP server: 拒新连接, 等 in-flight."""
        self._closed = True
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception as e:  # pragma: no cover (defensive)
                _log.warning("server.wait_closed error: %s", e)
        # 等所有 in-flight 连接关闭
        if self._active_connections:
            await asyncio.gather(*self._active_connections, return_exceptions=True)
        _log.info("HttpTransport stopped")

    # ------------------------------------------------------------------
    # connection handling
    # ------------------------------------------------------------------

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """每个 TCP 连接一个 task; 单请求响应后关闭 (1.0 简化)."""
        task = asyncio.current_task()
        if task is not None:
            self._active_connections.add(task)
        try:
            await self._handle_single_request(reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        except Exception as e:  # pragma: no cover (defensive)
            _log.exception("connection handler error: %s", e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # pragma: no cover
                pass
            if task is not None:
                self._active_connections.discard(task)

    async def _handle_single_request(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """解析单 HTTP 请求 → 路由 → 写响应."""
        # 1. 读 request line
        try:
            request_line = await asyncio.wait_for(
                reader.readline(), timeout=self._read_timeout_s
            )
        except asyncio.TimeoutError:
            await _write_simple(writer, 408, "Request Timeout")
            return
        if not request_line:
            return
        try:
            method, path, _version = _parse_request_line(request_line)
        except ValueError as e:
            await _write_simple(writer, 400, f"Bad Request: {e}")
            return
        # 1.0 简化: 只接受 POST /cluster/token (单 endpoint)
        if method != "POST":
            await _write_simple(writer, 405, "Method Not Allowed")
            return
        if path != "/cluster/token":
            await _write_simple(writer, 404, "Not Found")
            return
        # 2. 读 headers
        headers = await _read_headers(reader, timeout_s=self._read_timeout_s)
        if headers is None:
            await _write_simple(writer, 408, "Request Timeout")
            return
        if "transfer-encoding" in headers:
            # 1.0 不支持 chunked
            await _write_simple(writer, 411, "Length Required")
            return
        content_length_str = headers.get("content-length")
        if content_length_str is None:
            await _write_simple(writer, 411, "Length Required")
            return
        try:
            content_length = int(content_length_str)
        except ValueError:
            await _write_simple(writer, 400, "Invalid Content-Length")
            return
        if content_length <= 0 or content_length > self._max_payload_bytes:
            await _write_simple(
                writer, 413, f"Payload Too Large (max {self._max_payload_bytes})"
            )
            return
        # 3. 鉴权
        auth_header = headers.get(_AUTH_HEADER.lower(), "")
        if not auth_header or auth_header != self._token_server.config.auth_secret:
            self._token_server._stats["error_responses"] += 1
            await _write_simple(
                writer,
                401,
                "Unauthorized: missing or invalid X-Atlas-Cluster-Token",
            )
            return
        # 4. 读 body
        try:
            body = await asyncio.wait_for(
                reader.readexactly(content_length), timeout=self._read_timeout_s
            )
        except asyncio.TimeoutError:
            await _write_simple(writer, 408, "Request Timeout")
            return
        except asyncio.IncompleteReadError:
            await _write_simple(writer, 400, "Bad Request: incomplete body")
            return
        # 5. 解码 envelope
        try:
            envelope = decode_envelope(body)
        except ClusterProtocolError as e:
            self._token_server._stats["error_responses"] += 1
            error_code = e.code
            # 用 e.message 脱敏, 截断 64 bytes
            err_message = e.message[:64]
            err_envelope = self._token_server.build_error_envelope(
                request_id="00000000-0000-0000-0000-000000000000",
                instance_id="00000000-0000-0000-0000-000000000000",
                startup_epoch=0,
                resource="",
                permits=0.0,
                deadline_ns=0,
                error_code=error_code,
                error_message=err_message,
            )
            await _write_envelope(writer, 400, err_envelope)
            return
        # 6. 路由到 handler
        response_envelope = await self._route(envelope)
        # 7. 写响应
        await _write_envelope(writer, 200, response_envelope)

    async def _route(
        self, envelope: ClusterTokenEnvelope
    ) -> ClusterTokenEnvelope:
        """按 ``envelope.message_kind`` 路由到 TokenServer handler.

        错误处理:
        - ``ClusterStaleEpoch`` → ERROR_RESPONSE + STALE_EPOCH
        - ``ClusterLeaseNotFound`` → ERROR_RESPONSE + LEASE_NOT_FOUND
        - ``ClusterLeaseExpired`` → ERROR_RESPONSE + LEASE_EXPIRED
        - ``ClusterResourceNotConfigured`` → ERROR_RESPONSE + RESOURCE_NOT_CONFIGURED
        - ``ClusterServerError`` (max_inflight / not ready) → ERROR_RESPONSE +
          SERVER_OVERLOADED 或 INTERNAL_ERROR
        - 其他 → ERROR_RESPONSE + INTERNAL_ERROR
        """
        kind = envelope.message_kind
        try:
            if kind is ClusterMessageKind.ACQUIRE_REQUEST:
                return await self._token_server.handle_acquire(envelope)
            elif kind is ClusterMessageKind.RELEASE_REQUEST:
                return await self._token_server.handle_release(envelope)
            elif kind is ClusterMessageKind.RENEW_REQUEST:
                return await self._token_server.handle_renew(envelope)
            else:
                # Client 不应发 RESPONSE; 但 server 端容错
                self._token_server._stats["error_responses"] += 1
                return self._token_server.build_error_envelope(
                    request_id=envelope.request_id,
                    instance_id=envelope.instance_id,
                    startup_epoch=envelope.startup_epoch,
                    resource=envelope.resource,
                    permits=envelope.permits,
                    deadline_ns=envelope.deadline_ns,
                    error_code=ClusterErrorCode.UNKNOWN_MESSAGE_KIND,
                    error_message=f"unexpected message_kind: {kind.value}",
                )
        except ClusterStaleEpoch as e:
            self._token_server._stats["error_responses"] += 1
            return self._token_server.build_error_envelope(
                request_id=envelope.request_id,
                instance_id=envelope.instance_id,
                startup_epoch=envelope.startup_epoch,
                resource=envelope.resource,
                permits=envelope.permits,
                deadline_ns=envelope.deadline_ns,
                error_code=ClusterErrorCode.STALE_EPOCH,
                error_message=str(e),
            )
        except ClusterLeaseNotFound as e:
            self._token_server._stats["error_responses"] += 1
            return self._token_server.build_error_envelope(
                request_id=envelope.request_id,
                instance_id=envelope.instance_id,
                startup_epoch=envelope.startup_epoch,
                resource=envelope.resource,
                permits=envelope.permits,
                deadline_ns=envelope.deadline_ns,
                error_code=ClusterErrorCode.LEASE_NOT_FOUND,
                error_message=str(e),
            )
        except ClusterLeaseExpired as e:
            self._token_server._stats["error_responses"] += 1
            return self._token_server.build_error_envelope(
                request_id=envelope.request_id,
                instance_id=envelope.instance_id,
                startup_epoch=envelope.startup_epoch,
                resource=envelope.resource,
                permits=envelope.permits,
                deadline_ns=envelope.deadline_ns,
                error_code=ClusterErrorCode.LEASE_EXPIRED,
                error_message=str(e),
            )
        except ClusterResourceNotConfigured as e:
            self._token_server._stats["error_responses"] += 1
            return self._token_server.build_error_envelope(
                request_id=envelope.request_id,
                instance_id=envelope.instance_id,
                startup_epoch=envelope.startup_epoch,
                resource=envelope.resource,
                permits=envelope.permits,
                deadline_ns=envelope.deadline_ns,
                error_code=ClusterErrorCode.RESOURCE_NOT_CONFIGURED,
                error_message=str(e),
            )
        except ClusterServerError as e:
            self._token_server._stats["error_responses"] += 1
            # max_inflight 触发 → SERVER_OVERLOADED; 其他 → INTERNAL_ERROR
            code = (
                ClusterErrorCode.SERVER_OVERLOADED
                if e.code == "SERVER_OVERLOADED"
                else ClusterErrorCode.INTERNAL_ERROR
            )
            return self._token_server.build_error_envelope(
                request_id=envelope.request_id,
                instance_id=envelope.instance_id,
                startup_epoch=envelope.startup_epoch,
                resource=envelope.resource,
                permits=envelope.permits,
                deadline_ns=envelope.deadline_ns,
                error_code=code,
                error_message=str(e),
            )
        except Exception as e:  # pragma: no cover (defensive)
            self._token_server._stats["error_responses"] += 1
            _log.exception("handler unexpected error: %s", e)
            return self._token_server.build_error_envelope(
                request_id=envelope.request_id,
                instance_id=envelope.instance_id,
                startup_epoch=envelope.startup_epoch,
                resource=envelope.resource,
                permits=envelope.permits,
                deadline_ns=envelope.deadline_ns,
                error_code=ClusterErrorCode.INTERNAL_ERROR,
                error_message="internal error",
            )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_bind(bind_address: str) -> tuple[str, int]:
    """``"0.0.0.0:8765"`` → ``("0.0.0.0", 8765)``."""
    if not isinstance(bind_address, str) or ":" not in bind_address:
        raise ClusterConfigError(
            f"bind_address must be 'host:port', got {bind_address!r}",
            code="CONFIG_ERROR",
        )
    host, port_str = bind_address.rsplit(":", 1)
    try:
        port = int(port_str)
    except ValueError as e:
        raise ClusterConfigError(
            f"bind_address port must be int, got {port_str!r}",
            code="CONFIG_ERROR",
        ) from e
    if port < 0 or port > 65535:
        raise ClusterConfigError(
            f"bind_address port out of range: {port}",
            code="CONFIG_ERROR",
        )
    return host, port


def _parse_request_line(line: bytes) -> tuple[str, str, str]:
    """``b"POST /path HTTP/1.1\\r\\n"`` → ``("POST", "/path", "HTTP/1.1")``."""
    s = line.decode("ascii", errors="replace").rstrip("\r\n")
    parts = s.split(" ", 2)
    if len(parts) != 3:
        raise ValueError(f"invalid request line: {s!r}")
    return parts[0], parts[1], parts[2]


async def _read_headers(
    reader: asyncio.StreamReader, *, timeout_s: float
) -> dict[str, str] | None:
    """读 headers 直到空行; 返回 lowercase → value 字典; 超时返回 None."""
    headers: dict[str, str] = {}
    while True:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return None
        if not line or line == b"\r\n" or line == b"\n":
            break
        try:
            text = line.decode("ascii", errors="replace").rstrip("\r\n")
        except Exception:
            continue
        if ":" not in text:
            continue
        k, _, v = text.partition(":")
        headers[k.strip().lower()] = v.strip()
    return headers


async def _write_simple(
    writer: asyncio.StreamWriter, status: int, reason: str
) -> None:
    """写最小 HTTP 响应 (无 body, 1.0 简化路径)."""
    if status not in _STATUS_TEXT:
        status_text = f"{status} {_STATUS_TEXT.get(500, 'Internal Server Error')}"
    else:
        status_text = f"{status} {_STATUS_TEXT[status]}"
    payload = (reason or "").encode("utf-8")
    response = (
        f"HTTP/1.1 {status_text}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(payload)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode("ascii") + payload
    try:
        writer.write(response)
        await writer.drain()
    except Exception:  # pragma: no cover (defensive)
        pass


async def _write_envelope(
    writer: asyncio.StreamWriter,
    status: int,
    envelope: ClusterTokenEnvelope,
) -> None:
    """写 HTTP 响应: 200/4xx/5xx + JSON envelope body."""
    body = encode_envelope(envelope)
    if status not in _STATUS_TEXT:
        status = 500
    status_text = f"{status} {_STATUS_TEXT[status]}"
    headers = (
        f"HTTP/1.1 {status_text}\r\n"
        f"Content-Type: {_CONTENT_TYPE_JSON}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode("ascii")
    try:
        writer.write(headers)
        writer.write(body)
        await writer.drain()
    except Exception:  # pragma: no cover (defensive)
        pass


__all__ = ["HttpTransport"]
