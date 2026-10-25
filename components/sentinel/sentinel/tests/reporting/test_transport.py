"""``ReportingTransport`` 单元测试 (M6.5.2).

中文
----
覆盖:

1. **HTTP/1.1 + JSON over TCP 完整 round-trip** — 启动一个简单 TCP server,
   验证 request/response
2. **X-Atlas-Reporting-Token header 透传** — server 端能读到 token
3. **鉴权失败 (401) → ReporterAuthError**
4. **Content-Length 解析** — 大 body / 缺 Content-Length
5. **4xx 不重试 + 5xx retry** — 用 mock / fake server 模拟

**测试策略**: 启动一个轻量级 TCP server (asyncio.start_server), 解析
HTTP request 后返回响应; 不用 pytest fixture 共享 (每个测试独立
启停, 避免时序).

English
--------
Coverage:

1. **HTTP/1.1 + JSON over TCP full round-trip** — start a simple TCP
   server, verify request/response
2. **X-Atlas-Reporting-Token header passthrough** — server can read token
3. **Auth failure (401) → ReporterAuthError**
4. **Content-Length parsing** — large body / missing Content-Length
5. **4xx no retry + 5xx retry** — mock / fake server

Test strategy: start a lightweight TCP server (asyncio.start_server),
parse HTTP request then return response; no shared pytest fixtures
(each test starts/stops independently to avoid timing issues).
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    ReportingBatch,
    decode_envelope,
    decode_batch,
    encode_ack,
    AckEnvelope,
    AckSequence,
    encode_batch,
)
from atlas_richie.contracts.reporting.v1.codec import ReportingErrorCode
from atlas_richie.contracts.reporting.v1 import ErrorEnvelope, ErrorDetails

from atlas_richie.sentinel.reporting.auth import (
    X_ATLAS_REPORTING_TOKEN_HEADER,
)
from atlas_richie.sentinel.reporting.config import AgentReporterConfig, OverflowPolicy
from atlas_richie.sentinel.reporting.errors import (
    ReporterAuthError,
    ReporterConnectionError,
    ReporterProtocolError,
)
from atlas_richie.sentinel.reporting.outbox import ReportingOutbox
from atlas_richie.sentinel.reporting.transport import ReportingTransport


INSTANCE_ID = "00000000-0000-4000-8000-000000000001"
STARTUP_EPOCH = 12345
TEST_TOKEN = "0123456789abcdef"


def _make_config(port: int) -> AgentReporterConfig:
    return AgentReporterConfig(
        collector_address=f"127.0.0.1:{port}",
        auth_token=TEST_TOKEN,
        instance_id_persistence_path=None,
        outbox_max_size=100,
        outbox_overflow_policy=OverflowPolicy.BLOCK_WITH_TIMEOUT,
        batch_max_events=256,
        batch_max_bytes=64 * 1024,
        batch_send_interval_ns=100_000_000,
        max_contiguous_sequence=0,
        connect_timeout_ns=5_000_000_000,
        request_timeout_ns=5_000_000_000,
        reconnect_initial_ns=100_000_000,
        reconnect_max_ns=30_000_000_000,
        reconnect_jitter_ns=0,  # 测试时关掉 jitter
    )


def _make_batch(events: list[Any] | None = None) -> ReportingBatch:
    """构造测试 batch (走 outbox.emit 路径更真实, 但 1.0 测试简化)."""
    from atlas_richie.contracts.reporting.v1 import ReportingEnvelope
    import uuid
    if events is None:
        events = [
            ReportingEnvelope(
                protocol_version=PROTOCOL_VERSION,
                event_kind="rule_applied",
                event_payload={
                    "resource": "test",
                    "rule_id": "rule-1",
                    "exec_result": "applied",
                    "failure_class": None,
                    "rule_version_epoch": 1,
                    "rule_version_revision": 0,
                    "rule_version_checksum": "sha256:" + "0" * 64,
                },
                instance_id=INSTANCE_ID,
                startup_epoch=STARTUP_EPOCH,
                sequence=0,
                captured_at="2026-09-13T12:00:00.000000Z",
            )
        ]
    return ReportingBatch(
        protocol_version=PROTOCOL_VERSION,
        instance_id=INSTANCE_ID,
        startup_epoch=STARTUP_EPOCH,
        batch_id=str(uuid.uuid4()),
        sent_at="2026-09-13T12:00:00.000000Z",
        events=events,
        dropped_count=0,
    )


async def _find_free_port() -> int:
    """找一个可用的 loopback 端口."""
    server = await asyncio.start_server(
        lambda r, w: None, host="127.0.0.1", port=0
    )
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return port


class _FakeServer:
    """轻量级 fake HTTP/1.1 server, 单次响应.

    中文
    ----
    ``handler(request_bytes) -> response_bytes``: 测试用, 解析
    request (含 status line + headers + body) 后返回 response bytes.
    异步启动, 测试结束 aclose.

    English
    --------
    ``handler(request_bytes) -> response_bytes``: for tests, parse
    request (status line + headers + body) then return response bytes.
    Async start, aclose at end of test.
    """

    def __init__(self, handler: Any) -> None:
        self._handler = handler
        self._server: asyncio.AbstractServer | None = None
        self.port: int = 0
        # 记录 request (供 assert)
        self.last_request: bytes = b""
        self.request_count: int = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._on_client, host="127.0.0.1", port=0
        )
        self.port = self._server.sockets[0].getsockname()[1]

    async def aclose(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _on_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            # 读 status line
            status_line = await reader.readline()
            if not status_line:
                writer.close()
                return
            # 读 headers
            headers: dict[bytes, bytes] = {}
            while True:
                line = await reader.readline()
                if not line or line == b"\r\n":
                    break
                if b":" in line:
                    k, _, v = line.rstrip(b"\r\n").partition(b":")
                    headers[k.strip().lower()] = v.strip()
            # 读 body
            cl = headers.get(b"content-length")
            if cl is not None:
                body = await reader.readexactly(int(cl))
            else:
                body = b""
            request = status_line + b"\r\n" + b"\r\n".join(
                f"{k.decode()}: {v.decode()}".encode()
                for k, v in headers.items()
            ) + b"\r\n\r\n" + body
            self.last_request = request
            self.request_count += 1
            # 调 handler (支持同步 + 异步)
            response = self._handler(status_line, headers, body)
            if asyncio.iscoroutine(response):
                response = await response
            writer.write(response)
            await writer.drain()
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass


def _ok_ack_response() -> bytes:
    """构造 200 + ack response bytes."""
    ack = AckEnvelope(
        protocol_version=PROTOCOL_VERSION,
        batch_id="00000000-0000-4000-8000-000000000099",
        received_at="2026-09-13T12:00:00.000000Z",
        ack_sequences=[
            AckSequence(
                instance_id=INSTANCE_ID,
                startup_epoch=STARTUP_EPOCH,
                max_contiguous_sequence=0,
            )
        ],
        duplicate_count=0,
    )
    body = encode_ack(ack)
    return (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json; charset=utf-8\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n"
        b"\r\n" + body
    )


def _error_response(status: int, body_text: str) -> bytes:
    """构造 4xx / 5xx + error envelope response bytes."""
    err = ErrorEnvelope(
        protocol_version=PROTOCOL_VERSION,
        error_code=ReportingErrorCode.MALFORMED_ENVELOPE,
        message=body_text,
        details=ErrorDetails(field=None, got_type=None),
    )
    from atlas_richie.contracts.reporting.v1 import encode_error_envelope
    body = encode_error_envelope(err)
    return (
        f"HTTP/1.1 {status} {body_text}\r\n".encode()
        + b"Content-Type: application/json; charset=utf-8\r\n"
        + b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        + b"Connection: close\r\n"
        + b"\r\n" + body
    )


def _parse_request_headers(request: bytes) -> dict[bytes, bytes]:
    """解析 fake server 收到的 request (status line + headers)."""
    lines = request.split(b"\r\n")
    headers: dict[bytes, bytes] = {}
    for line in lines[1:]:
        if not line:
            break
        if b":" in line:
            k, _, v = line.partition(b":")
            headers[k.strip().lower()] = v.strip()
    return headers


def _parse_request_body(request: bytes) -> bytes:
    """解析 fake server 收到的 request body."""
    _, _, rest = request.partition(b"\r\n\r\n")
    return rest


class RoundTripTest(unittest.IsolatedAsyncioTestCase):
    """HTTP/1.1 + JSON over TCP 完整 round-trip."""

    async def test_round_trip_succeeds(self) -> None:
        server = _FakeServer(lambda sl, h, b: _ok_ack_response())
        await server.start()
        try:
            config = _make_config(server.port)
            transport = ReportingTransport(config=config)
            batch = _make_batch()
            result = await transport.submit(batch)
            self.assertEqual(result.http_status, 200)
            assert result.ack is not None
            self.assertEqual(result.ack.ack_sequences[0].instance_id, INSTANCE_ID)
            self.assertEqual(result.attempts, 1)
        finally:
            await server.aclose()


class AuthHeaderTest(unittest.IsolatedAsyncioTestCase):
    """X-Atlas-Reporting-Token header 透传."""

    async def test_auth_header_passthrough(self) -> None:
        async def handler(status_line: bytes, headers: dict[bytes, bytes], body: bytes) -> bytes:
            # 验证 token header 存在 + 值正确
            token = headers.get(X_ATLAS_REPORTING_TOKEN_HEADER.encode("ascii").lower())
            self.assertEqual(token, TEST_TOKEN.encode())
            return _ok_ack_response()

        server = _FakeServer(handler)
        await server.start()
        try:
            config = _make_config(server.port)
            transport = ReportingTransport(config=config)
            batch = _make_batch()
            result = await transport.submit(batch)
            self.assertEqual(result.http_status, 200)
            self.assertEqual(server.request_count, 1)
        finally:
            await server.aclose()

    async def test_token_with_control_char_rejected(self) -> None:
        """token 含换行符 → SentinelConfigurationError (header injection 防护)."""
        from atlas_richie.sentinel.errors import SentinelConfigurationError
        config = _make_config(12345)
        # 直接构造带换行的 token, 模拟用户错误
        from dataclasses import replace as dc_replace
        bad_config = dc_replace(config, auth_token="bad\ntoken\nwith\ncontrol")
        transport = ReportingTransport(config=bad_config)
        batch = _make_batch()
        with self.assertRaises(SentinelConfigurationError):
            await transport.submit(batch)


class AuthFailureTest(unittest.IsolatedAsyncioTestCase):
    """鉴权失败 (401) → ReporterAuthError."""

    async def test_401_returns_auth_error(self) -> None:
        async def handler(status_line: bytes, headers: dict[bytes, bytes], body: bytes) -> bytes:
            return _error_response(401, "Unauthorized")

        server = _FakeServer(handler)
        await server.start()
        try:
            config = _make_config(server.port)
            transport = ReportingTransport(config=config)
            batch = _make_batch()
            with self.assertRaises(ReporterAuthError) as cm:
                await transport.submit(batch)
            self.assertEqual(cm.exception.code, "AUTH_FAILED")
            # 401 不重试, 1 次
            self.assertEqual(server.request_count, 1)
        finally:
            await server.aclose()


class ContentLengthTest(unittest.IsolatedAsyncioTestCase):
    """Content-Length 解析."""

    async def test_content_length_parsed_correctly(self) -> None:
        """验证 server 收到的 Content-Length 跟 body 实际长度一致."""
        async def handler(status_line: bytes, headers: dict[bytes, bytes], body: bytes) -> bytes:
            cl = headers.get(b"content-length")
            assert cl is not None
            self.assertEqual(int(cl), len(body))
            # 验证 body 是有效 JSON
            json.loads(body)
            return _ok_ack_response()

        server = _FakeServer(handler)
        await server.start()
        try:
            config = _make_config(server.port)
            transport = ReportingTransport(config=config)
            batch = _make_batch()
            result = await transport.submit(batch)
            self.assertEqual(result.http_status, 200)
        finally:
            await server.aclose()


class RetryPolicyTest(unittest.IsolatedAsyncioTestCase):
    """4xx 不重试 + 5xx retry."""

    async def test_4xx_no_retry(self) -> None:
        """4xx (除 401) 立即 raise, 不重试."""
        call_count = 0

        async def handler(status_line: bytes, headers: dict[bytes, bytes], body: bytes) -> bytes:
            nonlocal call_count
            call_count += 1
            return _error_response(400, "Bad Request")

        server = _FakeServer(handler)
        await server.start()
        try:
            config = _make_config(server.port)
            transport = ReportingTransport(config=config)
            batch = _make_batch()
            with self.assertRaises(ReporterProtocolError) as cm:
                await transport.submit(batch)
            # 4xx 不重试
            self.assertEqual(server.request_count, 1)
            self.assertEqual(cm.exception.code, "MALFORMED_ENVELOPE")
        finally:
            await server.aclose()

    async def test_5xx_retries_3_times(self) -> None:
        """5xx 重试 3 次 (4 attempts: 1 initial + 3 retries)."""
        call_count = 0

        async def handler(status_line: bytes, headers: dict[bytes, bytes], body: bytes) -> bytes:
            nonlocal call_count
            call_count += 1
            return _error_response(500, "Internal Server Error")

        server = _FakeServer(handler)
        await server.start()
        try:
            config = _make_config(server.port)
            transport = ReportingTransport(config=config)
            batch = _make_batch()
            with self.assertRaises(ReporterConnectionError):
                await transport.submit(batch)
            # 5xx retry: 1 initial + 3 retries = 4 attempts
            self.assertEqual(server.request_count, 4)
        finally:
            await server.aclose()

    async def test_5xx_then_2xx_succeeds(self) -> None:
        """5xx 第 1 次, 2xx 第 2 次 — retry 成功."""
        call_count = 0

        async def handler(status_line: bytes, headers: dict[bytes, bytes], body: bytes) -> bytes:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _error_response(500, "Internal Server Error")
            return _ok_ack_response()

        server = _FakeServer(handler)
        await server.start()
        try:
            config = _make_config(server.port)
            transport = ReportingTransport(config=config)
            batch = _make_batch()
            result = await transport.submit(batch)
            self.assertEqual(result.http_status, 200)
            self.assertEqual(result.attempts, 2)
        finally:
            await server.aclose()


class ConnectionRefusedTest(unittest.IsolatedAsyncioTestCase):
    """连接拒绝 (TCP RST) → ReporterConnectionError."""

    async def test_connection_refused_raises_connection_error(self) -> None:
        port = await _find_free_port()
        # 端口空闲, 没人监听
        config = _make_config(port)
        transport = ReportingTransport(config=config)
        batch = _make_batch()
        with self.assertRaises(ReporterConnectionError):
            await transport.submit(batch)
