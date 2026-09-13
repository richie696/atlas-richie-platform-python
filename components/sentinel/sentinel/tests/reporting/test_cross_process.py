"""M6.5 跨进程验收测试 (M6.5 父任务 "真实验收" 段).

中文
----
PLANNING §M6.5 真实验收: 两个独立 Agent 进程向真实 Collector 上报;
注入重复、乱序、断线和重启后, 聚合结果不双计数, Reporter 也未阻塞
受保护请求. 验收 demo 只证明协议和 collector, 不宣称已交付聚合
Dashboard / Web UI.

测试范围:

1. **多 Reporter 实例**: 不同 instance_id + 不同 startup_epoch, 互不
   干扰; 同 instance + 同 epoch + 乱序 sequence 也不双计数
2. **重复 (duplicate)**: 同 (instance_id, startup_epoch, sequence) 重
   发, Collector 识别为 duplicate, Ack 返回 duplicate_count > 0
3. **乱序 (out-of-order)**: sequence 3, 1, 2 顺序到达, Collector 按
   instance 聚合并保留每个 sequence 一次
4. **断线 (disconnect)**: Collector 关闭 / 不可达, Reporter 不阻塞
   Engine / ASGI / HTTPX 路径, 重连后恢复
5. **重启 (restart)**: Reporter 重启, 新 instance_id 接管, Collector
   按新 identity 处理
6. **非阻塞 (no-blocking)**: Collector 慢 / 卡死, emit() 仍 < 50ms
   返回 (M6.5.3 决策)

实施方式: 1 个 fake Collector (asyncio HTTP server, 含 dedup 逻辑)
+ 2 个 AgentReporter (同进程, 不同 identity), 模拟"两个独立 Agent
进程"; 跨进程语义 (instance_id / startup_epoch 隔离) 由 identity
dataclass 保证, 不依赖 OS 进程隔离.

English
--------
M6.5 cross-process verification: two independent Agent processes report
to a real Collector; inject duplicate, out-of-order, disconnect, and
restart scenarios; verify Collector dedupes correctly and Reporter
does NOT block protected request paths.

Implementation: 1 fake Collector (asyncio HTTP server with dedup logic)
+ 2 AgentReporter instances (same process, different identity),
simulating "two independent Agent processes". Cross-process semantics
(instance_id / startup_epoch isolation) are enforced by the identity
dataclass, not by OS process isolation.
"""
from __future__ import annotations

import asyncio
import time
import unittest
import uuid
from dataclasses import replace
from typing import Any

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    AckEnvelope,
    AckSequence,
    ErrorDetails,
    ErrorEnvelope,
    ReportingBatch,
    ReportingEnvelope,
    ReportingEventKind,
    decode_batch,
    encode_ack,
    encode_batch,
    encode_error_envelope,
)
from atlas_richie.contracts.reporting.v1.codec import ReportingErrorCode

from atlas_richie.sentinel.reporting import (
    AgentReporter,
    AgentReporterConfig,
    OverflowPolicy,
    ReportingEvent,
)
from atlas_richie.sentinel.reporting.auth import X_ATLAS_REPORTING_TOKEN_HEADER
from atlas_richie.sentinel.reporting.config import (
    BATCH_MAX_BYTES,
    BATCH_MAX_EVENTS,
)
from atlas_richie.sentinel.reporting.reporter import _build_envelope_template
from atlas_richie.sentinel.reporting.transport import ReportingTransport


TEST_TOKEN = "0123456789abcdef"


def _make_config(
    port: int,
    *,
    outbox_max_size: int = 100,
    overflow_policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST,
    batch_send_interval_ns: int = 20_000_000,  # 20ms flush interval
    connect_timeout_ns: int = 2_000_000_000,
    request_timeout_ns: int = 2_000_000_000,
    reconnect_initial_ns: int = 10_000_000,
    reconnect_max_ns: int = 100_000_000,
    reconnect_jitter_ns: int = 0,
) -> AgentReporterConfig:
    return AgentReporterConfig(
        collector_address=f"127.0.0.1:{port}",
        auth_token=TEST_TOKEN,
        instance_id_persistence_path=None,
        outbox_max_size=outbox_max_size,
        outbox_overflow_policy=overflow_policy,
        batch_max_events=BATCH_MAX_EVENTS,
        batch_max_bytes=BATCH_MAX_BYTES,
        batch_send_interval_ns=batch_send_interval_ns,
        max_contiguous_sequence=0,
        connect_timeout_ns=connect_timeout_ns,
        request_timeout_ns=request_timeout_ns,
        reconnect_initial_ns=reconnect_initial_ns,
        reconnect_max_ns=reconnect_max_ns,
        reconnect_jitter_ns=reconnect_jitter_ns,
    )


def _make_event(
    source_id: str = "src-A",
    rule_id: str = "rule-1",
) -> ReportingEvent:
    """构造测试 event (RULE_APPLIED, 1.x 实施默认字段)."""
    return ReportingEvent(
        kind=ReportingEventKind.RULE_APPLIED.value,
        source_id=source_id,
        resource="test-resource",
        rule_id=rule_id,
        exec_result="APPLIED",
        failure_class=None,
        reason=None,
        previous_source_id=None,
        priority=None,
        health_class=None,
        reason_message=None,
        epoch=1,
        revision=0,
        checksum="sha256:" + "0" * 64,
    )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime())


# ---------------------------------------------------------------------------
# Fake Collector: asyncio HTTP server, dedup logic, Ack response
# ---------------------------------------------------------------------------


class _FakeCollector:
    """M6.5 跨进程验收用 fake Collector.

    模拟 Java/Go 真实 Collector 行为:
    - 接收 POST /atlas-richie/reporting/v1/envelopes
    - 按 (instance_id, startup_epoch, sequence) 去重
    - 返回 AckEnvelope (含 max_contiguous_sequence + duplicate_count)
    """

    def __init__(self) -> None:
        self.envelopes: list[ReportingEnvelope] = []
        self.sequences_by_instance: dict[tuple[str, int], set[int]] = {}
        self.duplicate_count = 0
        self.request_count = 0
        self._server: asyncio.AbstractServer | None = None
        self.port: int = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._on_client, host="127.0.0.1", port=0
        )
        self.port = self._server.sockets[0].getsockname()[1]

    async def aclose(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def _dedupe_envelope(self, env: ReportingEnvelope) -> bool:
        """True 表示新增, False 表示 duplicate."""
        key = (env.instance_id, env.startup_epoch)
        seqs = self.sequences_by_instance.setdefault(key, set())
        if env.sequence in seqs:
            self.duplicate_count += 1
            return False
        seqs.add(env.sequence)
        return True

    def _build_ack(self, batch: ReportingBatch) -> AckEnvelope:
        per_instance_in_batch: dict[tuple[str, int], int] = {}
        for env in batch.events:
            key = (env.instance_id, env.startup_epoch)
            cur = per_instance_in_batch.get(key, 0)
            if env.sequence > cur:
                per_instance_in_batch[key] = env.sequence

        ack_sequences: list[AckSequence] = []
        for key in per_instance_in_batch:
            all_seqs = sorted(self.sequences_by_instance.get(key, set()))
            # max_contiguous = 第一个 gap 之前的最大值
            # (从 0 起, sequence 1 之前的 max = 0)
            max_contiguous = 0
            for s in all_seqs:
                if s == max_contiguous + 1:
                    max_contiguous = s
                else:
                    break
            ack_sequences.append(
                AckSequence(
                    instance_id=key[0],
                    startup_epoch=key[1],
                    max_contiguous_sequence=max_contiguous,
                )
            )
        return AckEnvelope(
            protocol_version=PROTOCOL_VERSION,
            batch_id=batch.batch_id,
            received_at=_now_iso(),
            ack_sequences=ack_sequences,
            duplicate_count=self.duplicate_count,
        )

    async def _on_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            status_line = await reader.readline()
            if not status_line:
                return
            headers: dict[bytes, bytes] = {}
            while True:
                line = await reader.readline()
                if not line or line == b"\r\n":
                    break
                if b":" in line:
                    k, _, v = line.rstrip(b"\r\n").partition(b":")
                    headers[k.strip().lower()] = v.strip()
            cl = headers.get(b"content-length")
            body = await reader.readexactly(int(cl)) if cl else b""
            self.request_count += 1
            # 鉴权 (协议 §5.1 X-Atlas-Reporting-Token)
            token = headers.get(X_ATLAS_REPORTING_TOKEN_HEADER.lower().encode())
            if token is None or token.decode() != TEST_TOKEN:
                err = ErrorEnvelope(
                    protocol_version=PROTOCOL_VERSION,
                    error_code=ReportingErrorCode.AUTH_FAILED,
                    message="missing or invalid token",
                    details=ErrorDetails(field=None, got_type=None),
                )
                err_body = encode_error_envelope(err)
                response = (
                    b"HTTP/1.1 401 Unauthorized\r\n"
                    b"Content-Type: application/json; charset=utf-8\r\n"
                    b"Content-Length: " + str(len(err_body)).encode() + b"\r\n"
                    b"Connection: close\r\n\r\n" + err_body
                )
                writer.write(response)
                await writer.drain()
                return
            batch = decode_batch(body)
            for env in batch.events:
                if self._dedupe_envelope(env):
                    self.envelopes.append(env)
            ack = self._build_ack(batch)
            ack_body = encode_ack(ack)
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json; charset=utf-8\r\n"
                b"Content-Length: " + str(len(ack_body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + ack_body
            )
            writer.write(response)
            await writer.drain()
        except Exception as e:
            err = ErrorEnvelope(
                protocol_version=PROTOCOL_VERSION,
                error_code=ReportingErrorCode.MALFORMED_ENVELOPE,
                message=str(e),
                details=ErrorDetails(field=None, got_type=None),
            )
            err_body = encode_error_envelope(err)
            response = (
                b"HTTP/1.1 400 Bad Request\r\n"
                b"Content-Type: application/json; charset=utf-8\r\n"
                b"Content-Length: " + str(len(err_body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + err_body
            )
            try:
                writer.write(response)
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def wait_for_envelope_count(
        self, target: int, timeout: float = 5.0
    ) -> bool:
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if len(self.envelopes) >= target:
                return True
            await asyncio.sleep(0.02)
        return False


class _ManualTransport:
    """手动构造 envelope (指定 sequence) → 直接送 transport → Collector.

    中文
    ----
    M6.5 跨进程验收专用 helper: 跳过 AgentReporter.outbox 的 sequence
    自动分配, 用 ReportingTransport 直接发. 用于 duplicate / out-of-order
    / restart 等需要指定 sequence 的测试.
    """

    def __init__(self, port: int) -> None:
        from atlas_richie.sentinel.reporting._identity import ReporterIdentity
        from atlas_richie.sentinel.reporting.outbox import ReportingOutbox

        self.config = _make_config(port)
        self.identity = ReporterIdentity(
            instance_id="00000000-0000-4000-8000-000000000099",
            startup_epoch=0,
        )
        self.outbox = ReportingOutbox(
            config=self.config,
            instance_id=self.identity.instance_id,
            startup_epoch=self.identity.startup_epoch,
        )
        self.transport = ReportingTransport(config=self.config)

    def set_identity(self, instance_id: str, startup_epoch: int) -> None:
        from atlas_richie.sentinel.reporting._identity import ReporterIdentity
        from atlas_richie.sentinel.reporting.outbox import ReportingOutbox
        self.identity = ReporterIdentity(
            instance_id=instance_id, startup_epoch=startup_epoch
        )
        # 重建 outbox (新 identity)
        self.outbox = ReportingOutbox(
            config=self.config,
            instance_id=self.identity.instance_id,
            startup_epoch=self.identity.startup_epoch,
        )

    def build_envelope_with_seq(
        self, event: ReportingEvent, sequence: int
    ) -> ReportingEnvelope:
        kind = ReportingEventKind(event.kind)
        env = _build_envelope_template(
            event=event, identity=self.identity, kind=kind
        )
        return replace(env, sequence=sequence)

    async def submit_envelopes(
        self, envelopes: list[ReportingEnvelope]
    ) -> None:
        batch = ReportingBatch(
            protocol_version=PROTOCOL_VERSION,
            instance_id=self.identity.instance_id,
            startup_epoch=self.identity.startup_epoch,
            batch_id=str(uuid.uuid4()),
            sent_at=_now_iso(),
            events=envelopes,
            dropped_count=0,
        )
        await self.transport.submit(batch)

    async def aclose(self) -> None:
        # ReportingTransport.aclose 是同步方法 (returns None)
        self.transport.aclose()


# ---------------------------------------------------------------------------
# 场景 1: 多 Reporter 实例隔离
# ---------------------------------------------------------------------------


class MultiReporterIsolationTest(unittest.IsolatedAsyncioTestCase):
    """两个独立 Reporter 实例, 互不干扰."""

    async def test_two_reporters_distinct_instance_id(self) -> None:
        collector = _FakeCollector()
        await collector.start()
        try:
            r1 = AgentReporter(_make_config(collector.port))
            r2 = AgentReporter(_make_config(collector.port))
            await r1.start()
            await r2.start()
            try:
                # r1 用默认生成的 instance_id, r2 也用默认
                # 这里没法控制 instance_id, 但能验证"两个不同
                # AgentReporter 实例"互不干扰 (因为 UUID 不同)
                r1.emit(_make_event(rule_id="r1-rule-1"))
                r1.emit(_make_event(rule_id="r1-rule-2"))
                r1.emit(_make_event(rule_id="r1-rule-3"))
                r2.emit(_make_event(rule_id="r2-rule-1"))
                r2.emit(_make_event(rule_id="r2-rule-2"))
                r2.emit(_make_event(rule_id="r2-rule-3"))
                self.assertTrue(
                    await collector.wait_for_envelope_count(6, timeout=3.0)
                )
                self.assertEqual(collector.duplicate_count, 0)
                # 至少 2 个 instance 各 3 个
                instance_counts = [
                    len(s) for s in collector.sequences_by_instance.values()
                ]
                self.assertEqual(sorted(instance_counts), [3, 3])
            finally:
                await r1.aclose()
                await r2.aclose()
        finally:
            await collector.aclose()


# ---------------------------------------------------------------------------
# 场景 2: Duplicate
# ---------------------------------------------------------------------------


class DuplicateTest(unittest.IsolatedAsyncioTestCase):
    """同 (instance_id, startup_epoch, sequence) 重发 → Collector dedup."""

    async def test_duplicate_sequence_deduped(self) -> None:
        collector = _FakeCollector()
        await collector.start()
        try:
            tx = _ManualTransport(collector.port)
            tx.set_identity(
                "550e8400-e29b-41d4-a716-446655440010", 1
            )
            try:
                ev = _make_event(rule_id="dup-1")
                # 第一次: seq=1
                env1 = tx.build_envelope_with_seq(ev, sequence=1)
                await tx.submit_envelopes([env1])
                self.assertTrue(
                    await collector.wait_for_envelope_count(1, timeout=3.0)
                )
                self.assertEqual(collector.duplicate_count, 0)
                # 重复: 同 instance + 同 epoch + seq=1
                env1_dup = tx.build_envelope_with_seq(ev, sequence=1)
                await tx.submit_envelopes([env1_dup])
                await asyncio.sleep(0.1)
                self.assertEqual(len(collector.envelopes), 1)
                self.assertEqual(collector.duplicate_count, 1)
            finally:
                await tx.aclose()
        finally:
            await collector.aclose()


# ---------------------------------------------------------------------------
# 场景 3: Out-of-order
# ---------------------------------------------------------------------------


class OutOfOrderTest(unittest.IsolatedAsyncioTestCase):
    """sequence 3, 1, 2 到达: Collector 全部保留, 不算 duplicate."""

    async def test_out_of_order_all_accepted(self) -> None:
        collector = _FakeCollector()
        await collector.start()
        try:
            tx = _ManualTransport(collector.port)
            tx.set_identity(
                "550e8400-e29b-41d4-a716-446655440020", 1
            )
            try:
                ev = _make_event(rule_id="ooo-1")
                # 乱序发: 3, 1, 2
                for seq in (3, 1, 2):
                    env = tx.build_envelope_with_seq(ev, sequence=seq)
                    await tx.submit_envelopes([env])
                self.assertTrue(
                    await collector.wait_for_envelope_count(3, timeout=3.0)
                )
                seqs = collector.sequences_by_instance[
                    ("550e8400-e29b-41d4-a716-446655440020", 1)
                ]
                self.assertEqual(seqs, {1, 2, 3})
                self.assertEqual(collector.duplicate_count, 0)
            finally:
                await tx.aclose()
        finally:
            await collector.aclose()


# ---------------------------------------------------------------------------
# 场景 4: Disconnect
# ---------------------------------------------------------------------------


class DisconnectRecoverTest(unittest.IsolatedAsyncioTestCase):
    """Collector 关闭后, Reporter 不阻塞; 重启后恢复."""

    async def test_emit_does_not_block_when_collector_down(self) -> None:
        """Collector 不可达, emit() 仍 < 50ms 返回 (M6.5.3 决策)."""
        config = _make_config(19999)  # 未监听端口
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            t0 = time.perf_counter()
            reporter.emit(_make_event(rule_id="noblk-1"))
            elapsed = time.perf_counter() - t0
            # emit 同步, 必 < 50ms
            self.assertLess(
                elapsed, 0.05,
                f"emit() blocked {elapsed*1000:.1f}ms (M6.5.3 违反)",
            )
        finally:
            await reporter.aclose()

    async def test_collector_recovery_after_restart(self) -> None:
        """Collector 重启后, 新 Reporter 指向新 port 继续发送."""
        # 阶段 1: 第一个 Collector, 验证 happy path
        c1 = _FakeCollector()
        await c1.start()
        reporter1 = AgentReporter(_make_config(c1.port))
        await reporter1.start()
        try:
            reporter1.emit(_make_event(rule_id="recover-1"))
            self.assertTrue(
                await c1.wait_for_envelope_count(1, timeout=3.0)
            )
        finally:
            await reporter1.aclose()
            await c1.aclose()
        # 阶段 2: 第二个 Collector, 新 Reporter 指向新 port
        c2 = _FakeCollector()
        await c2.start()
        reporter2 = AgentReporter(_make_config(c2.port))
        await reporter2.start()
        try:
            reporter2.emit(_make_event(rule_id="recover-2"))
            self.assertTrue(
                await c2.wait_for_envelope_count(1, timeout=3.0)
            )
        finally:
            await reporter2.aclose()
            await c2.aclose()


# ---------------------------------------------------------------------------
# 场景 5: Restart (新 instance_id 接管)
# ---------------------------------------------------------------------------


class RestartIdentityTest(unittest.IsolatedAsyncioTestCase):
    """Reporter 重启, 新 instance_id 接管; Collector 按新 identity 处理."""

    async def test_restart_new_instance_id(self) -> None:
        collector = _FakeCollector()
        await collector.start()
        try:
            tx1 = _ManualTransport(collector.port)
            tx1.set_identity(
                "550e8400-e29b-41d4-a716-446655440030", 1
            )
            try:
                ev = _make_event(rule_id="rstrt-1")
                await tx1.submit_envelopes([
                    tx1.build_envelope_with_seq(ev, sequence=s)
                    for s in (1, 2)
                ])
                self.assertTrue(
                    await collector.wait_for_envelope_count(2, timeout=3.0)
                )
            finally:
                await tx1.aclose()
            # 模拟重启: 新 instance_id
            tx2 = _ManualTransport(collector.port)
            tx2.set_identity(
                "550e8400-e29b-41d4-a716-446655440031", 1
            )
            try:
                ev = _make_event(rule_id="rstrt-2")
                await tx2.submit_envelopes([
                    tx2.build_envelope_with_seq(ev, sequence=s)
                    for s in (1, 2, 3)
                ])
                self.assertTrue(
                    await collector.wait_for_envelope_count(5, timeout=3.0)
                )
                self.assertEqual(
                    len(collector.sequences_by_instance[
                        ("550e8400-e29b-41d4-a716-446655440030", 1)
                    ]),
                    2,
                )
                self.assertEqual(
                    len(collector.sequences_by_instance[
                        ("550e8400-e29b-41d4-a716-446655440031", 1)
                    ]),
                    3,
                )
            finally:
                await tx2.aclose()
        finally:
            await collector.aclose()


# ---------------------------------------------------------------------------
# 场景 6: No-blocking (M6.5.3 决策)
# ---------------------------------------------------------------------------


class NonBlockingTest(unittest.IsolatedAsyncioTestCase):
    """Collector 慢 / 卡死时, emit() 仍 < 10ms."""

    async def test_emit_returns_immediately_with_slow_collector(self) -> None:
        """Collector 故意卡住 (sleep 1s), emit() 仍 < 10ms."""
        async def slow_handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                await reader.readline()
                while True:
                    line = await reader.readline()
                    if not line or line == b"\r\n":
                        break
                # 不读 body, 让 socket 卡住
                await asyncio.sleep(5.0)
            except Exception:
                pass
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

        server = await asyncio.start_server(
            slow_handler, host="127.0.0.1", port=0
        )
        port = server.sockets[0].getsockname()[1]
        try:
            config = _make_config(
                port, batch_send_interval_ns=20_000_000
            )
            reporter = AgentReporter(config)
            await reporter.start()
            try:
                t0 = time.perf_counter()
                reporter.emit(_make_event(rule_id="slow-1"))
                elapsed = time.perf_counter() - t0
                # emit 同步, 必 < 10ms
                self.assertLess(
                    elapsed, 0.01,
                    f"emit() blocked {elapsed*1000:.1f}ms",
                )
            finally:
                await reporter.aclose()
        finally:
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
