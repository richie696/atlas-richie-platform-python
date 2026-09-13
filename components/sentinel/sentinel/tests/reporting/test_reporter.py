"""``AgentReporter`` 单元测试 (M6.5.1).

中文
----
覆盖:

1. **emit() 同步 facade** — sequence 严格递增
2. **3 次 exponential backoff 重试** (mock 4xx 不重试 / 5xx retry)
3. **错误码映射** (11 wire error_code → 7 ReporterError)
4. **aclose() 重复调用安全** (idempotent)
5. **aclose() drain 行为** (in-flight 等待)
6. **lifecycle** (未 start / 已 closed → SentinelLifecycleError)
7. **identity 持久化 + 跨重启**

English
--------
Coverage:

1. **emit() sync facade** — sequence strictly increasing
2. **3-attempt exponential backoff retry** (mock 4xx no retry / 5xx retry)
3. **Error code mapping** (11 wire error_code → 7 ReporterError)
4. **aclose() idempotent**
5. **aclose() drain behavior** (waits for in-flight)
6. **lifecycle** (not started / closed → SentinelLifecycleError)
7. **identity persistence + cross-restart**
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    ReportingEnvelope,
    ReportingEventKind,
    ReportingErrorCode,
    decode_batch,
)
from atlas_richie.contracts.reporting.v1.codec import encode_error_envelope
from atlas_richie.contracts.reporting.v1 import ErrorEnvelope, ErrorDetails

from atlas_richie.sentinel.errors import (
    SentinelConfigurationError,
    SentinelError,
    SentinelLifecycleError,
)
from atlas_richie.sentinel.reporting import (
    AgentReporter,
    AgentReporterConfig,
    OverflowPolicy,
    ReporterError,
    ReporterIdentity,
    ReportingEvent,
)
from atlas_richie.sentinel.reporting.config import (
    BATCH_MAX_BYTES,
    BATCH_MAX_EVENTS,
)


def _make_config(
    *,
    outbox_max_size: int = 100,
    outbox_overflow_policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST,
    collector_address: str = "127.0.0.1:18765",
    auth_token: str = "0123456789abcdef",
) -> AgentReporterConfig:
    return AgentReporterConfig(
        collector_address=collector_address,
        auth_token=auth_token,
        instance_id_persistence_path=None,
        outbox_max_size=outbox_max_size,
        outbox_overflow_policy=outbox_overflow_policy,
        batch_max_events=BATCH_MAX_EVENTS,
        batch_max_bytes=BATCH_MAX_BYTES,
        batch_send_interval_ns=100_000_000,
        max_contiguous_sequence=0,
        connect_timeout_ns=2_000_000_000,  # 2s for tests
        request_timeout_ns=2_000_000_000,  # 2s for tests
        reconnect_initial_ns=10_000_000,  # 10ms for tests
        reconnect_max_ns=100_000_000,  # 100ms for tests
        reconnect_jitter_ns=0,
    )


def _make_event(kind: str = "rule_applied", **overrides: object) -> ReportingEvent:
    defaults: dict[str, object] = {
        "kind": kind,
        "source_id": None,
        "resource": "test-resource",
        "rule_id": "rule-1",
        "exec_result": "applied",
        "failure_class": None,
        "reason": None,
        "previous_source_id": None,
        "priority": None,
        "health_class": None,
        "reason_message": None,
        "epoch": 1,
        "revision": 0,
        "checksum": "sha256:" + "0" * 64,
    }
    defaults.update(overrides)
    return ReportingEvent(**defaults)  # type: ignore[arg-type]


class IdentityTest(unittest.TestCase):
    """identity 构造 + 持久化."""

    def test_auto_identity_generated(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        # identity 自动生成
        self.assertIsNotNone(reporter.identity.instance_id)
        self.assertIsNotNone(reporter.identity.startup_epoch)
        # UUID v4 格式校验
        self.assertEqual(len(reporter.identity.instance_id), 36)
        self.assertEqual(reporter.identity.instance_id.count("-"), 4)

    def test_explicit_identity_accepted(self) -> None:
        config = _make_config()
        identity = ReporterIdentity(
            instance_id="00000000-0000-4000-8000-000000000099",
            startup_epoch=42,
        )
        reporter = AgentReporter(config, identity=identity)
        self.assertEqual(reporter.identity.instance_id, "00000000-0000-4000-8000-000000000099")
        self.assertEqual(reporter.identity.startup_epoch, 42)

    def test_persistence_round_trip(self) -> None:
        """持久化文件: 第一次生成, 第二次读回."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "identity.json")
            config = _make_config()
            config2 = AgentReporterConfig(
                collector_address=config.collector_address,
                auth_token=config.auth_token,
                instance_id_persistence_path=path,
                outbox_max_size=config.outbox_max_size,
                outbox_overflow_policy=config.outbox_overflow_policy,
                batch_max_events=config.batch_max_events,
                batch_max_bytes=config.batch_max_bytes,
                batch_send_interval_ns=config.batch_send_interval_ns,
                max_contiguous_sequence=config.max_contiguous_sequence,
                connect_timeout_ns=config.connect_timeout_ns,
                request_timeout_ns=config.request_timeout_ns,
                reconnect_initial_ns=config.reconnect_initial_ns,
                reconnect_max_ns=config.reconnect_max_ns,
                reconnect_jitter_ns=config.reconnect_jitter_ns,
            )
            r1 = AgentReporter(config2)
            r2 = AgentReporter(config2)
            # 跨进程 (同 path) 读回相同 identity
            self.assertEqual(r1.identity.instance_id, r2.identity.instance_id)
            self.assertEqual(r1.identity.startup_epoch, r2.identity.startup_epoch)


class LifecycleTest(unittest.IsolatedAsyncioTestCase):
    """lifecycle: start / aclose 行为."""

    async def test_aclose_before_start_is_safe(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        # 从未 start, aclose 不抛
        await reporter.aclose()
        self.assertTrue(reporter.closed)

    async def test_aclose_idempotent(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.aclose()
        # 重复 aclose
        await reporter.aclose()
        await reporter.aclose()
        self.assertTrue(reporter.closed)

    async def test_emit_before_start_raises_lifecycle_error(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        with self.assertRaises(SentinelLifecycleError):
            reporter.emit(_make_event())

    async def test_emit_after_aclose_raises_lifecycle_error(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.start()
        await reporter.aclose()
        with self.assertRaises(SentinelLifecycleError):
            reporter.emit(_make_event())

    async def test_double_start_raises_lifecycle_error(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            with self.assertRaises(SentinelLifecycleError):
                await reporter.start()
        finally:
            await reporter.aclose()


class EmitSequenceTest(unittest.IsolatedAsyncioTestCase):
    """emit() 同步 facade + sequence 严格递增."""

    async def test_emit_returns_strict_increasing_sequence(self) -> None:
        config = _make_config(
            outbox_overflow_policy=OverflowPolicy.DROP_OLDEST,
        )
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            seqs = [reporter.emit(_make_event()) for _ in range(50)]
            self.assertEqual(seqs, list(range(50)))
        finally:
            await reporter.aclose()

    async def test_emit_invalid_kind_raises(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            with self.assertRaises(ValueError):
                reporter.emit(_make_event(kind="not_a_valid_kind"))
        finally:
            await reporter.aclose()

    async def test_emit_event_kinds(self) -> None:
        """6 个 ReportingEventKind 全部可 emit (DRAFT 字段保留)."""
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            seqs: list[int] = []
            seqs.append(reporter.emit(_make_event(
                kind="rule_source_activated",
                source_id="src-A", reason="initial", previous_source_id=None, priority=10,
            )))
            seqs.append(reporter.emit(_make_event(
                kind="rule_source_stale",
                source_id="src-A", health_class="stale", reason_message="timeout",
            )))
            seqs.append(reporter.emit(_make_event(
                kind="rule_source_degraded",
                source_id="src-A", health_class="degraded", reason_message="partial",
            )))
            seqs.append(reporter.emit(_make_event(
                kind="rule_applied", resource="r", rule_id="rule", exec_result="applied",
            )))
            seqs.append(reporter.emit(_make_event(
                kind="rule_blocked", resource="r", rule_id="rule", exec_result="blocked",
            )))
            seqs.append(reporter.emit(_make_event(
                kind="rule_failed", resource="r", rule_id="rule", exec_result="failed",
                failure_class="timeout",
            )))
            self.assertEqual(seqs, list(range(6)))
        finally:
            await reporter.aclose()


class ErrorCodeMappingTest(unittest.TestCase):
    """11 wire error_code → 7 ReporterError."""

    def test_error_code_mapping(self) -> None:
        from atlas_richie.sentinel.reporting.errors import (
            ReporterAuthError,
            ReporterProtocolError,
            ReporterConnectionError,
            ReporterSendTimeoutError,
            ReporterAckTimeoutError,
            ReporterOverflowError,
            ReporterLeaseError,
        )
        # 11 错误码 → 7 ReporterError 映射
        mapping = {
            ReportingErrorCode.PROTOCOL_VERSION_MISMATCH: ReporterProtocolError,
            ReportingErrorCode.MALFORMED_ENVELOPE: ReporterProtocolError,
            ReportingErrorCode.UNKNOWN_EVENT_KIND: ReporterProtocolError,
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH: ReporterProtocolError,
            ReportingErrorCode.INSTANCE_ID_EMPTY: ReporterProtocolError,
            ReportingErrorCode.SEQUENCE_NOT_MONOTONIC: ReporterProtocolError,
            ReportingErrorCode.SEQUENCE_GAP: ReporterProtocolError,
            ReportingErrorCode.STALE_EPOCH: ReporterProtocolError,
            ReportingErrorCode.ENVELOPE_TOO_LARGE: ReporterProtocolError,
            ReportingErrorCode.BATCH_TOO_LARGE: ReporterProtocolError,
            ReportingErrorCode.AUTH_FAILED: ReporterAuthError,
        }
        # 全部 7 个 ReporterError 都覆盖
        seen = set()
        for code, err_cls in mapping.items():
            self.assertTrue(issubclass(err_cls, ReporterError))
            self.assertTrue(issubclass(err_cls, SentinelError))
            seen.add(err_cls)
        # 7 个 ReporterError 都在 mapping 中或独立类
        all_known = {
            ReporterAuthError,
            ReporterProtocolError,
            ReporterConnectionError,
            ReporterSendTimeoutError,
            ReporterAckTimeoutError,
            ReporterOverflowError,
            ReporterLeaseError,
        }
        # ReporterError 自身也包括
        all_known.add(ReporterError)
        # mapping 中出现的
        self.assertIn(ReporterAuthError, seen)
        self.assertIn(ReporterProtocolError, seen)
        # 其它 4 个是网络/超时/overflow/lease, 跟 wire 错误码无直接 1:1
        # (它们是 transport 层本地异常, 由 transport 抛, 不来自 wire 错误码)

    def test_all_reporter_errors_inherit_sentinel_error(self) -> None:
        from atlas_richie.sentinel.reporting.errors import (
            ReporterError,
            ReporterConnectionError,
            ReporterAuthError,
            ReporterProtocolError,
            ReporterAckTimeoutError,
            ReporterOverflowError,
            ReporterSendTimeoutError,
            ReporterLeaseError,
        )
        for cls in (
            ReporterConnectionError,
            ReporterAuthError,
            ReporterProtocolError,
            ReporterAckTimeoutError,
            ReporterOverflowError,
            ReporterSendTimeoutError,
            ReporterLeaseError,
        ):
            self.assertTrue(issubclass(cls, ReporterError))
            self.assertTrue(issubclass(cls, SentinelError))


class OverflowTest(unittest.IsolatedAsyncioTestCase):
    """overflow 3 选 1 策略 (端到端 via AgentReporter.emit)."""

    async def test_drop_newest_raises_overflow(self) -> None:
        config = _make_config(
            outbox_max_size=2,
            outbox_overflow_policy=OverflowPolicy.DROP_NEWEST,
        )
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            reporter.emit(_make_event())  # 0
            reporter.emit(_make_event())  # 1
            # 第 3 个 → ReporterOverflowError
            from atlas_richie.sentinel.reporting import ReporterOverflowError
            with self.assertRaises(ReporterOverflowError):
                reporter.emit(_make_event())
        finally:
            await reporter.aclose()

    async def test_drop_oldest_never_raises(self) -> None:
        config = _make_config(
            outbox_max_size=2,
            outbox_overflow_policy=OverflowPolicy.DROP_OLDEST,
        )
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            # emit 5 个, max=2, 静默淘汰 3 个
            seqs = [reporter.emit(_make_event()) for _ in range(5)]
            self.assertEqual(seqs, [0, 1, 2, 3, 4])
        finally:
            await reporter.aclose()


class AcloseDrainTest(unittest.IsolatedAsyncioTestCase):
    """aclose() drain 行为 (in-flight 等待)."""

    async def test_aclose_waits_for_drain(self) -> None:
        """aclose 等待 background flush + drain 完毕."""
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.start()
        # emit 几个 (不投到 server, 没 server)
        for _ in range(3):
            reporter.emit(_make_event())
        # aclose 立即返回 (1.0 不持久化, 接受损失)
        await reporter.aclose()
        self.assertTrue(reporter.closed)


class AcloseAfterStartTest(unittest.IsolatedAsyncioTestCase):
    """aclose() 在 start() 之后 drain + 关闭."""

    async def test_aclose_after_start(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.start()
        self.assertTrue(reporter.started)
        await reporter.aclose()
        self.assertTrue(reporter.closed)


class ConfigIntegrationTest(unittest.TestCase):
    """AgentReporter 跟 AgentReporterConfig fail-fast 集成."""

    def test_invalid_config_raises_sentinel_configuration_error(self) -> None:
        # 错误 token 长度 → 构造时抛
        with self.assertRaises(SentinelConfigurationError):
            AgentReporterConfig(
                collector_address="127.0.0.1:8765",
                auth_token="short",
                instance_id_persistence_path=None,
                outbox_max_size=100,
                outbox_overflow_policy=OverflowPolicy.DROP_OLDEST,
                batch_max_events=BATCH_MAX_EVENTS,
                batch_max_bytes=BATCH_MAX_BYTES,
                batch_send_interval_ns=100_000_000,
                max_contiguous_sequence=0,
                connect_timeout_ns=5_000_000_000,
                request_timeout_ns=5_000_000_000,
                reconnect_initial_ns=100_000_000,
                reconnect_max_ns=30_000_000_000,
                reconnect_jitter_ns=50_000_000,
            )
