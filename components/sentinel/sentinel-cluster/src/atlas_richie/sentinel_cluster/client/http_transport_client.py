"""Atlas Richie Sentinel Cluster — Client HTTP/1.1 + JSON Transport (M6.3.4).

中文
----
跟 Server 端 ``http_transport`` 配对的 Client 端, **严格** 1:1 实现 wire
protocol V1 (协议 §3):

- 单连接 + 单请求 + 单响应 (no keep-alive, 1.0 简化)
- 鉴权: ``X-Atlas-Cluster-Token`` header (1.0 shared secret)
- Content-Length 必填, ≤ 8 KB
- Body 严格 JSON, ``encode_envelope`` / ``decode_envelope`` 严格校验
- deadline 走 ``asyncio.wait_for`` (单请求硬超时)

**反例** (1.0 拒绝):

- ❌ 引入 aiohttp / httpx / gRPC (主包 0 依赖 + Cluster wheel 0 3rd-party)
- ❌ 连接池 / keep-alive (1.0 简化, M6.3.x future)
- ❌ 异步发送多请求并发 (1.0 单连接 + 单请求)

English
--------
Client-side ``http_transport`` paired with Server. **Strictly** 1:1 implements
wire protocol V1 (protocol §3):

- Single connection + single request + single response (no keep-alive,
  1.0 simplification)
- Auth: ``X-Atlas-Cluster-Token`` header (1.0 shared secret)
- Content-Length required, ≤ 8 KB
- Body strict JSON, ``encode_envelope`` / ``decode_envelope`` strict
- Deadline via ``asyncio.wait_for`` (per-request hard timeout)

Anti-patterns (1.0 forbidden):

- ❌ aiohttp / httpx / gRPC (main wheel 0 deps + Cluster wheel 0 3rd-party)
- ❌ Connection pool / keep-alive (1.0 simplification, M6.3.x future)
- ❌ Async multi-request pipelining (1.0 single conn + single request)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from atlas_richie.contracts.cluster.v1 import (
    ClusterProtocolError,
    ClusterTokenEnvelope,
    decode_envelope,
    encode_envelope,
)

from ..errors import ClusterConfigError, ClusterServerError
from .auth import AUTH_HEADER_NAME, build_auth_header

_log = logging.getLogger("atlas_richie.sentinel_cluster.client.http")

# HTTP/1.1 status text (mirror server side, 1.0 简化)
_STATUS_TEXT = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    408: "Request Timeout",
    411: "Length Required",
    413: "Payload Too Large",
    500: "Internal Server Error",
    503: "Service Unavailable",
}

# 单 envelope 字节上限 (协议 §3.4)
_MAX_PAYLOAD_BYTES = 8 * 1024  # 8 KB

# request line 末尾
_REQUEST_LINE_TPL = "POST /cluster/token HTTP/1.1\r\nHost: {host}\r\n"
_CRLF = b"\r\n"


class _TransportError(Exception):
    """Client 端 transport 内部异常 (含 reason, 供 retry / policy 决策)."""

    def __init__(self, reason: str, *, status: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


def _parse_response_status(line_bytes: bytes) -> int:
    """``b"HTTP/1.1 200 OK\\r\\n"`` → status code (int)."""
    s = line_bytes.decode("ascii", errors="replace").rstrip("\r\n")
    parts = s.split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("HTTP/"):
        raise _TransportError(f"invalid status line: {s!r}")
    try:
        return int(parts[1])
    except ValueError as e:
        raise _TransportError(f"invalid status code: {parts[1]!r}") from e


def _parse_headers_block(header_lines: list[bytes]) -> dict[str, str]:
    """读 header 列表 (每行已含 ``\\r\\n``); 返回 lowercase → value 字典."""
    headers: dict[str, str] = {}
    for raw in header_lines:
        try:
            line = raw.decode("ascii", errors="replace").rstrip("\r\n")
        except Exception:
            continue
        if not line:
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()
    return headers


class HttpTransportClient:
    """HTTP/1.1 + JSON Client transport (M6.3.4).

    1.0 公开 API:
    - ``await transport.send(envelope)`` — 同步 facade 内部协程化调
    - ``transport.close()`` — 释放资源 (1.0 单连接, no-op)
    """

    def __init__(
        self,
        *,
        server_address: str,
        auth_secret: str,
        request_timeout_s: float = 5.0,
        connect_timeout_s: float = 1.0,
    ) -> None:
        """初始化 Client transport.

        Args:
            server_address: ``"host:port"`` 形式 (e.g. ``"127.0.0.1:8765"``)
            auth_secret: 配 ``ClusterTokenConfig.auth_secret`` (1.0 shared secret)
            request_timeout_s: 单 request 总超时 (含连接 + 写 + 读 + 响应)
            connect_timeout_s: TCP connect 超时 (秒)

        Raises:
            ClusterConfigError: 参数非法
        """
        self._host, self._port = _parse_server_address(server_address)
        if not isinstance(request_timeout_s, (int, float)) or request_timeout_s <= 0:
            raise ClusterConfigError(
                f"request_timeout_s must be positive number, got {request_timeout_s!r}",
                code="CONFIG_ERROR",
            )
        if not isinstance(connect_timeout_s, (int, float)) or connect_timeout_s <= 0:
            raise ClusterConfigError(
                f"connect_timeout_s must be positive number, got {connect_timeout_s!r}",
                code="CONFIG_ERROR",
            )
        # secret 校验 (不写入 self 任何公开属性, 避免反射)
        self._auth_header_value: str = build_auth_header(auth_secret)[1]
        self._request_timeout_s = float(request_timeout_s)
        self._connect_timeout_s = float(connect_timeout_s)
        self._closed = False

    @property
    def server_address(self) -> str:
        """``"host:port"`` 形式 (供 debug / log)."""
        return f"{self._host}:{self._port}"

    async def send(self, envelope: ClusterTokenEnvelope) -> ClusterTokenEnvelope:
        """单次请求响应: envelope → wire → server → response envelope.

        Args:
            envelope: REQUEST envelope (Client 构造)

        Returns:
            响应 envelope (ACQUIRE_RESPONSE / RENEW_RESPONSE / ERROR_RESPONSE)

        Raises:
            ClusterServerError: 网络错 / 协议错 / Server 5xx (不含 200/400 业务)
            asyncio.TimeoutError: request 总超时 (供 retry / policy 决策)
            _TransportError: transport 内部错 (status != 200, 含 4xx/5xx)
        """
        if self._closed:
            raise ClusterServerError(
                "transport closed", code="LIFECYCLE_ERROR"
            )
        # 1. 序列化 envelope
        try:
            body = encode_envelope(envelope)
        except (ClusterProtocolError, ValueError, TypeError) as e:
            # 序列化错 = Client 端 bug, **不** retry
            raise ClusterServerError(
                f"client encode error: {type(e).__name__}: {e}",
                code="CLIENT_ENCODE_ERROR",
            ) from e
        if len(body) > _MAX_PAYLOAD_BYTES:
            raise ClusterServerError(
                f"envelope too large: {len(body)} > {_MAX_PAYLOAD_BYTES}",
                code="CLIENT_PAYLOAD_TOO_LARGE",
            )
        # 2. TCP connect + send + receive (单连接 + 单请求)
        try:
            async with asyncio.timeout(self._request_timeout_s):
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=self._connect_timeout_s,
                )
                try:
                    return await self._round_trip(reader, writer, body)
                finally:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:  # pragma: no cover (defensive)
                        pass
        except asyncio.TimeoutError as e:
            # 超时 = transport 级 retry trigger
            raise _TransportError(f"request timeout: {e!r}") from e
        except (ConnectionRefusedError, OSError) as e:
            # Server 不可达 = transport 级 retry trigger
            raise _TransportError(f"connection error: {e!r}") from e

    async def _round_trip(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        body: bytes,
    ) -> ClusterTokenEnvelope:
        """在已建立的连接上发 request + 收 response."""
        # 1. 写 HTTP request
        request_line = _REQUEST_LINE_TPL.format(host=self._host).encode("ascii")
        auth_header_line = f"{AUTH_HEADER_NAME}: {self._auth_header_value}\r\n".encode("ascii")
        headers_block = (
            request_line
            + auth_header_line
            + b"Content-Type: application/json; charset=utf-8\r\n"
            + f"Content-Length: {len(body)}\r\n".encode("ascii")
            + b"Connection: close\r\n"
            + b"\r\n"
        )
        writer.write(headers_block)
        writer.write(body)
        await writer.drain()
        # 2. 读 status line
        status_line = await reader.readline()
        if not status_line:
            raise _TransportError("server closed connection without response")
        status = _parse_response_status(status_line)
        # 3. 读 headers
        header_lines: list[bytes] = []
        while True:
            line = await reader.readline()
            if not line or line == b"\r\n" or line == b"\n":
                break
            header_lines.append(line)
        headers = _parse_headers_block(header_lines)
        # 4. 读 body
        content_length_str = headers.get("content-length")
        if content_length_str is None:
            # Server 走 "无 body 错误" 路径 (e.g. 401 简化)
            if status == 200:
                raise _TransportError("missing Content-Length on 200")
            # 非 200 + 无 body → 当作 401 / 5xx 走 policy 决策
            raise _TransportError(
                f"server returned status {status} without body", status=status
            )
        try:
            content_length = int(content_length_str)
        except ValueError as e:
            raise _TransportError(f"invalid Content-Length: {content_length_str!r}") from e
        if content_length <= 0 or content_length > _MAX_PAYLOAD_BYTES:
            raise _TransportError(
                f"invalid Content-Length: {content_length}"
            )
        body_bytes = await reader.readexactly(content_length)
        # 5. 状态码 + body 翻译
        if status == 200:
            try:
                return decode_envelope(body_bytes)
            except ClusterProtocolError as e:
                # Server 返回 200 但 envelope 坏 = wire 协议 bug, **不** retry
                raise ClusterServerError(
                    f"server returned 200 but envelope invalid: {e!r}",
                    code="WIRE_DECODE_ERROR",
                ) from e
        # 4xx / 5xx: 业务错, **不** retry, 走 policy 决策
        if 400 <= status < 500:
            # 尝试解析 body 成 error envelope (跟 server 401 不同, 401 是 plain text)
            try:
                return decode_envelope(body_bytes)
            except (ClusterProtocolError, ValueError, json.JSONDecodeError):
                # 401 / 405 / 411 / 413 走 plain text 路径
                text = body_bytes.decode("utf-8", errors="replace")
                # 不带 body 内容进异常 (避免反射 secret / 内部信息)
                raise _TransportError(
                    f"server returned status {status} (body not JSON envelope)",
                    status=status,
                ) from None
        # 5xx: server 内部错
        raise _TransportError(f"server returned status {status}", status=status)

    async def close(self) -> None:
        """关闭 transport (1.0 单连接 + 每次新连接, close 是 no-op)."""
        self._closed = True


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_server_address(addr: str) -> tuple[str, int]:
    """``"127.0.0.1:8765"`` → ``("127.0.0.1", 8765)``."""
    if not isinstance(addr, str) or ":" not in addr:
        raise ClusterConfigError(
            f"server_address must be 'host:port', got {addr!r}",
            code="CONFIG_ERROR",
        )
    host, port_str = addr.rsplit(":", 1)
    if not host:
        raise ClusterConfigError(
            f"server_address host must be non-empty, got {addr!r}",
            code="CONFIG_ERROR",
        )
    try:
        port = int(port_str)
    except ValueError as e:
        raise ClusterConfigError(
            f"server_address port must be int, got {port_str!r}",
            code="CONFIG_ERROR",
        ) from e
    if port < 0 or port > 65535:
        raise ClusterConfigError(
            f"server_address port out of range: {port}",
            code="CONFIG_ERROR",
        )
    return host, port


__all__ = ["HttpTransportClient"]
