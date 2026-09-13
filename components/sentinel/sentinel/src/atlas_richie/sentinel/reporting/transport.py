"""Atlas Richie Sentinel — Agent Reporting V1 transport (M6.5.2).

中文
----
HTTP/1.1 + JSON over TCP, asyncio 原生实现, **不**依赖 aiohttp /
gRPC / httpx / WebSocket (跟 M6.3 实施一致).

- **POST /reporting/v1/events** — body = batch JSON, response = 200 + ack
  OR 4xx / 5xx + error envelope
- **Auth Header**: ``X-Atlas-Reporting-Token: <auth_token>`` (协议 §5.1)
- **Content-Type**: ``application/json; charset=utf-8``
- **Connection: close** (协议 §3.5 keep-alive 不支持)
- **TLS 不支持, 仅 loopback** (协议 §3.5 强制, Mavis 治理)
- **失败 retry**: 3 次 exponential backoff (50ms / 200ms / 1s) + 抖动;
  4xx (除 AUTH_FAILED) 不重试

**不**暴露在 ``__all__`` (Mavis 治理: transport 私有, 不进 public API).

English
--------
HTTP/1.1 + JSON over TCP, asyncio-native, **no** aiohttp / gRPC /
httpx / WebSocket (matching M6.3 implementation).

- **POST /reporting/v1/events** — body = batch JSON, response = 200 +
  ack OR 4xx / 5xx + error envelope
- **Auth Header**: ``X-Atlas-Reporting-Token: <auth_token>`` (protocol §5.1)
- **Content-Type**: ``application/json; charset=utf-8``
- **Connection: close** (protocol §3.5 no keep-alive)
- **No TLS, loopback only** (protocol §3.5 mandatory, Mavis governance)
- **Retry**: 3 attempts exponential backoff (50ms / 200ms / 1s) + jitter;
  4xx (except AUTH_FAILED) does not retry

Not in ``__all__`` (Mavis governance: transport is private, not public).
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    AckEnvelope,
    ErrorEnvelope,
    ReportingBatch,
    decode_ack,
    decode_error_envelope,
)

from .auth import (
    X_ATLAS_REPORTING_TOKEN_HEADER,
    render_auth_header_value,
)
from .config import AgentReporterConfig
from .errors import (
    ReporterAuthError,
    ReporterConnectionError,
    ReporterProtocolError,
    ReporterSendTimeoutError,
)


# POST /reporting/v1/events (协议 transport §3.4)
_REPORTING_PATH: bytes = b"/reporting/v1/events"

# 协议 transport §3.5: HTTP/1.1, Connection: close
_HTTP_VERSION: bytes = b"HTTP/1.1"

# 协议 transport §5.1: Content-Type
_CONTENT_TYPE: bytes = b"application/json; charset=utf-8"

# 协议 transport §3.4: 最大响应 body = 16 KiB (ack 跟 error envelope 都 ≤ 16 KiB)
_MAX_RESPONSE_BYTES: int = 16 * 1024

# 协议 transport §6: 3 次重试 (50ms / 200ms / 1s)
_RETRY_DELAYS_NS: tuple[int, ...] = (50_000_000, 200_000_000, 1_000_000_000)

# 协议 transport §6: 4xx 不重试; AUTH_FAILED 单独标记
_AUTH_FAILED_HTTP_STATUS: int = 401
_AUTH_FAILED_WIRE_CODE: str = "AUTH_FAILED"


# ---------------------------------------------------------------------------
# 内部 result DTO
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class TransportResult:
    """Transport 单次投递结果 (Reporter 内部使用).

    中文
    ----
    成功: ``ack=AckEnvelope`` (协议 §9.2 5 字段); 失败: ``error_code``
    + ``http_status`` (4xx / 5xx). 注意 4xx 不重试 (除 5xx 走 retry);
    AUTH_FAILED 单独 catch (不重试, 触发 reporter 关闭).

    English
    --------
    Success: ``ack=AckEnvelope`` (protocol §9.2 5 fields); failure:
    ``error_code`` + ``http_status`` (4xx / 5xx). Note 4xx does not
    retry (5xx does); AUTH_FAILED is caught separately (no retry,
    triggers reporter close).
    """

    http_status: int
    ack: AckEnvelope | None
    error: ErrorEnvelope | None
    attempts: int  # 总尝试次数 (含 retry)


# ---------------------------------------------------------------------------
# Transport 主体
# ---------------------------------------------------------------------------


Sleeper = Callable[[float], Awaitable[None]]


async def _default_sleeper(seconds: float) -> None:
    await asyncio.sleep(seconds)


class ReportingTransport:
    """HTTP/1.1 + JSON over TCP 投递层 (私有).

    中文
    ----
    行为契约 (跟 M6.3 实施一致):

    1. 解析 Server 响应 (含 HTTP status line + Content-Length + body)
    2. 4xx (除 401 AUTH_FAILED) → ``ReporterProtocolError``, 不重试
    3. 5xx / 网络错 → ``ReporterConnectionError``, 3 次 retry
    4. 超时 → ``ReporterSendTimeoutError``, 3 次 retry
    5. 401 / AUTH_FAILED → ``ReporterAuthError``, 不重试
    6. 200 → 解 ack (协议 §9.2 5 字段), 透传给 Reporter

    协议 V1 强制 Connection: close; 每次 submit 都新建 TCP 连接.
    """

    def __init__(
        self,
        *,
        config: AgentReporterConfig,
        sleeper: Sleeper | None = None,
    ) -> None:
        # 解析 host / port (config 已 validate 过 loopback, 这里不再
        # 二次校验, 信任 config 路径)
        host, _, port_str = config.collector_address.rpartition(":")
        self._host: str = host
        self._port: int = int(port_str)
        self._auth_token: str = config.auth_token
        self._connect_timeout_ns: int = config.connect_timeout_ns
        self._request_timeout_ns: int = config.request_timeout_ns
        self._sleeper: Sleeper = sleeper or _default_sleeper
        self._jitter_ns: int = config.reconnect_jitter_ns
        # state
        self._closed: bool = False

    @property
    def closed(self) -> bool:
        return self._closed

    def aclose(self) -> None:
        """Transport 不持有长连接, aclose 只置位 flag. 幂等."""
        self._closed = True

    async def submit(self, batch: ReportingBatch) -> TransportResult:
        """投递 batch, 3 次 retry (4xx 不重试), 返回 TransportResult.

        中文
        ----
        1. ``encode_batch(batch)`` → wire JSON bytes
        2. 3 次尝试: 第 1 次立即, 第 2/3 次按 50ms / 200ms + jitter 退避
        3. 4xx (除 401) → raise ``ReporterProtocolError`` (不重试)
        4. 401 / AUTH_FAILED → raise ``ReporterAuthError`` (不重试)
        5. 5xx / 网络错 / 超时 → raise ``ReporterConnectionError`` /
           ``ReporterSendTimeoutError`` (重试 3 次后抛)

        English
        --------
        1. ``encode_batch(batch)`` → wire JSON bytes
        2. 3 attempts: immediate / 50ms+jitter / 200ms+jitter
        3. 4xx (except 401) → raise ``ReporterProtocolError`` (no retry)
        4. 401 / AUTH_FAILED → raise ``ReporterAuthError`` (no retry)
        5. 5xx / network / timeout → raise ``ReporterConnectionError`` /
           ``ReporterSendTimeoutError`` (after 3 retries)
        """
        if self._closed:
            raise RuntimeError("transport is closed")
        from atlas_richie.contracts.reporting.v1 import encode_batch
        body: bytes = encode_batch(batch)
        last_exc: BaseException | None = None
        attempts = 0
        for attempt in range(len(_RETRY_DELAYS_NS) + 1):  # 1 initial + 3 retries
            attempts = attempt + 1
            try:
                return await self._submit_once(body, attempts=attempts)
            except (ReporterAuthError, ReporterProtocolError):
                # 4xx 不重试; 立刻 raise
                raise
            except (ReporterConnectionError, ReporterSendTimeoutError) as e:
                last_exc = e
                if attempt >= len(_RETRY_DELAYS_NS):
                    # 3 次都失败, raise 最后一个
                    raise
                # backoff + jitter
                delay_s = _RETRY_DELAYS_NS[attempt] / 1_000_000_000
                # 抖动: ± jitter_ns, 但不能小于 0
                import random
                jitter_s = (random.randint(0, self._jitter_ns) / 1_000_000_000) if self._jitter_ns > 0 else 0.0
                await self._sleeper(max(0.0, delay_s + jitter_s))
        # 不可达 (for 循环总会 raise 或 return)
        raise ReporterConnectionError(
            f"transport exhausted retries, last error: {last_exc}"
        )

    async def _submit_once(self, body: bytes, *, attempts: int) -> TransportResult:
        """单次 HTTP POST (含 TCP 连接 + 请求 + 响应解析)."""
        # 1. 建 TCP 连接 (loopback only, 协议 §3.5)
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._connect_timeout_ns / 1_000_000_000,
            )
        except (asyncio.TimeoutError, OSError) as e:
            raise ReporterConnectionError(
                f"connect to {self._host}:{self._port} failed: {e}"
            ) from e
        try:
            # 2. 拼 HTTP request
            auth_value = render_auth_header_value(self._auth_token)
            request: bytes = (
                b"POST " + _REPORTING_PATH + b" " + _HTTP_VERSION + b"\r\n"
                b"Host: " + self._host.encode("ascii") + b":" + str(self._port).encode("ascii") + b"\r\n"
                b"Content-Type: " + _CONTENT_TYPE + b"\r\n"
                b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                b"Connection: close\r\n"
                b"" + X_ATLAS_REPORTING_TOKEN_HEADER.encode("ascii") + b": " + auth_value.encode("utf-8") + b"\r\n"
                b"\r\n"
                + body
            )
            # 3. 写请求 (request_timeout 覆盖整个 send 阶段)
            try:
                await asyncio.wait_for(
                    writer.drain(),
                    timeout=self._request_timeout_ns / 1_000_000_000,
                )
                writer.write(request)
                await asyncio.wait_for(
                    writer.drain(),
                    timeout=self._request_timeout_ns / 1_000_000_000,
                )
            except (asyncio.TimeoutError, ConnectionError) as e:
                raise ReporterSendTimeoutError(
                    f"send request to {self._host}:{self._port} failed: {e}"
                ) from e
            # 4. 读响应 (request_timeout 覆盖整个 recv 阶段)
            try:
                response = await asyncio.wait_for(
                    _read_http_response(reader),
                    timeout=self._request_timeout_ns / 1_000_000_000,
                )
            except asyncio.TimeoutError as e:
                raise ReporterSendTimeoutError(
                    f"read response from {self._host}:{self._port} timed out: {e}"
                ) from e
        finally:
            # 5. 关闭连接 (协议 §3.5 Connection: close, 每次新建)
            try:
                writer.close()
                await writer.wait_closed()
            except (OSError, ConnectionError):
                # 关闭阶段失败不算错 (协议 §3.5)
                pass
        # 6. 解析响应
        status_line, headers, resp_body = response
        return self._parse_response(status_line, headers, resp_body, attempts=attempts)

    def _parse_response(
        self,
        status_line: bytes,
        headers: dict[bytes, bytes],
        body: bytes,
        *,
        attempts: int,
    ) -> TransportResult:
        """解析 HTTP 响应, 区分 200 ack / 4xx error / 5xx error."""
        # 1. 解析 status line
        # e.g. b"HTTP/1.1 200 OK\r\n"
        parts = status_line.split(b" ", 2)
        if len(parts) < 2 or not parts[0].startswith(b"HTTP/"):
            raise ReporterProtocolError(
                f"invalid HTTP status line: {status_line!r}",
                code="MALFORMED_ENVELOPE",
            )
        try:
            status_code = int(parts[1])
        except ValueError as e:
            raise ReporterProtocolError(
                f"invalid HTTP status code: {parts[1]!r}"
            ) from e
        # 2. 2xx → 200 success
        if 200 <= status_code < 300:
            try:
                ack = decode_ack(body)
            except Exception as e:  # noqa: BLE001 (decode 抛 ReportingProtocolError)
                # 200 + 错 body → 协议错 (跟 M6.3 决策一致)
                code = getattr(e, "code", None)
                code_str = code.value if hasattr(code, "value") else str(code or "PROTOCOL_ERROR")
                raise ReporterProtocolError(
                    f"failed to decode 200 ack: {e}",
                    code=code_str,
                ) from e
            return TransportResult(
                http_status=status_code,
                ack=ack,
                error=None,
                attempts=attempts,
            )
        # 3. 401 → AUTH_FAILED
        if status_code == _AUTH_FAILED_HTTP_STATUS:
            err: ErrorEnvelope | None = None
            try:
                err = decode_error_envelope(body)
            except Exception:
                # 401 + 不可解析 body → 仍按 AUTH_FAILED 处理
                err = None
            raise ReporterAuthError(
                f"401 Unauthorized: auth token rejected (protocol §5.1)",
                code=_AUTH_FAILED_WIRE_CODE,
            )
        # 4. 4xx (除 401) → ProtocolError (不重试)
        if 400 <= status_code < 500:
            err = None
            try:
                err = decode_error_envelope(body)
            except Exception:
                err = None
            code_str = (
                err.error_code if err is not None else f"HTTP_{status_code}"
            )
            raise ReporterProtocolError(
                f"server returned 4xx: {status_code} {err.message if err else ''}",
                code=code_str,
            )
        # 5. 5xx → ConnectionError (重试)
        if 500 <= status_code < 600:
            err = None
            try:
                err = decode_error_envelope(body)
            except Exception:
                err = None
            code_str = (
                err.error_code if err is not None else f"HTTP_{status_code}"
            )
            raise ReporterConnectionError(
                f"server returned 5xx: {status_code} {err.message if err else ''}",
                code=code_str,
            )
        # 6. 1xx / 3xx (不应出现, 协议 §3.5 Connection: close, 不重定向)
        raise ReporterProtocolError(
            f"unexpected HTTP status: {status_code} (protocol §3.5 "
            f"rejects 1xx/3xx; expected 2xx/4xx/5xx)",
            code=f"HTTP_{status_code}",
        )


# ---------------------------------------------------------------------------
# 私有 HTTP/1.1 解析 helper (不依赖任何 3rd-party 库)
# ---------------------------------------------------------------------------


async def _read_http_response(
    reader: asyncio.StreamReader,
) -> tuple[bytes, dict[bytes, bytes], bytes]:
    """Read full HTTP/1.1 response: status line + headers + body.

    中文
    ----
    协议 transport §3.5 强制 Connection: close, server 关闭连接表示
    response 结束 (本类不依赖 Content-Length, 但读 header 后看
    Content-Length 决定 body 长度; 缺失时读 EOF).

    Raises:
        ReporterConnectionError: 协议错 / EOF 早 / body 超 16 KiB
    """
    # 1. status line
    try:
        status_line = await reader.readline()
    except (ConnectionError, asyncio.IncompleteReadError) as e:
        raise ReporterConnectionError(f"read status line failed: {e}") from e
    if not status_line or not status_line.endswith(b"\r\n"):
        raise ReporterConnectionError(
            f"invalid status line (no CRLF): {status_line!r}"
        )
    status_line = status_line.rstrip(b"\r\n")
    # 2. headers
    headers: dict[bytes, bytes] = {}
    while True:
        try:
            line = await reader.readline()
        except (ConnectionError, asyncio.IncompleteReadError) as e:
            raise ReporterConnectionError(f"read header failed: {e}") from e
        if not line or line == b"\r\n":
            break
        if not line.endswith(b"\r\n"):
            raise ReporterConnectionError(
                f"header line missing CRLF: {line!r}"
            )
        line = line.rstrip(b"\r\n")
        if b":" not in line:
            raise ReporterConnectionError(
                f"header line missing colon: {line!r}"
            )
        k, _, v = line.partition(b":")
        headers[k.strip().lower()] = v.strip()
    # 3. body — 优先 Content-Length
    content_length_bytes = headers.get(b"content-length")
    if content_length_bytes is not None:
        try:
            content_length = int(content_length_bytes)
        except ValueError as e:
            raise ReporterConnectionError(
                f"invalid Content-Length: {content_length_bytes!r}"
            ) from e
        if content_length < 0:
            raise ReporterConnectionError(
                f"negative Content-Length: {content_length}"
            )
        if content_length > _MAX_RESPONSE_BYTES:
            raise ReporterConnectionError(
                f"Content-Length {content_length} exceeds "
                f"{_MAX_RESPONSE_BYTES} bytes (协议 §3.4)"
            )
        try:
            body = await reader.readexactly(content_length)
        except (asyncio.IncompleteReadError, ConnectionError) as e:
            raise ReporterConnectionError(
                f"read body (Content-Length={content_length}) failed: {e}"
            ) from e
    else:
        # 无 Content-Length: 读 EOF (协议 §3.5 Connection: close)
        try:
            body = await reader.read(_MAX_RESPONSE_BYTES + 1)
        except ConnectionError as e:
            raise ReporterConnectionError(f"read body (EOF) failed: {e}") from e
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ReporterConnectionError(
                f"response body exceeds {_MAX_RESPONSE_BYTES} bytes "
                f"(no Content-Length, EOF read)"
            )
    return status_line, headers, body


__all__: list[str] = []  # 全部私有, Reporter 内部使用
