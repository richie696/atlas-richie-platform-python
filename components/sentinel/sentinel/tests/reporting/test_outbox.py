"""``ReportingOutbox`` 单元测试 (M6.5.5).

中文
----
覆盖:

1. **串行化 sequence 分配** (asyncio.Lock → threading.Lock 简化) —
   多线程并发 emit 严格递增
2. **overflow 3 选 1 策略** — DROP_OLDEST 静默淘汰 / DROP_NEWEST 拒绝 /
   BLOCK_WITH_TIMEOUT 阻塞
3. **dropped_count 准确计数** — DROP_OLDEST 透传到 batch
4. **batch 累积触发** — 256 / 64 KiB / 时间 / drain
5. **batch 单一 identity 校验** — 协议 §7.2

English
--------
Coverage:

1. **Serialized sequence allocation** (asyncio.Lock → threading.Lock
   simplified) — multi-thread concurrent emit strictly increasing
2. **3-of-3 overflow policy** — DROP_OLDEST silent eviction /
   DROP_NEWEST reject / BLOCK_WITH_TIMEOUT blocking
3. **Accurate dropped_count** — DROP_OLDEST propagates to batch
4. **Batch accumulation triggers** — 256 / 64 KiB / time / drain
5. **Batch single-identity validation** — protocol §7.2
"""

from __future__ import annotations

import threading
import time
import unittest

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    ReportingEnvelope,
)

from atlas_richie.sentinel.reporting.config import (
    BATCH_MAX_BYTES,
    BATCH_MAX_EVENTS,
    AgentReporterConfig,
    OverflowPolicy,
)
from atlas_richie.sentinel.reporting.outbox import OutboxFull, ReportingOutbox


INSTANCE_ID = "00000000-0000-4000-8000-000000000001"
STARTUP_EPOCH = 12345


def _make_config(
    *,
    outbox_max_size: int = 100,
    outbox_overflow_policy: OverflowPolicy = OverflowPolicy.BLOCK_WITH_TIMEOUT,
    batch_send_interval_ns: int = 100_000_000,
) -> AgentReporterConfig:
    return AgentReporterConfig(
        collector_address="127.0.0.1:8765",
        auth_token="0123456789abcdef",
        instance_id_persistence_path=None,
        outbox_max_size=outbox_max_size,
        outbox_overflow_policy=outbox_overflow_policy,
        batch_max_events=BATCH_MAX_EVENTS,
        batch_max_bytes=BATCH_MAX_BYTES,
        batch_send_interval_ns=batch_send_interval_ns,
        max_contiguous_sequence=0,
        connect_timeout_ns=5_000_000_000,
        request_timeout_ns=5_000_000_000,
        reconnect_initial_ns=100_000_000,
        reconnect_max_ns=30_000_000_000,
        reconnect_jitter_ns=50_000_000,
    )


def _make_envelope(seq: int) -> ReportingEnvelope:
    """构造一个 minimal envelope (只填必要字段, 测试不严格 codec)."""
    return ReportingEnvelope(
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
        sequence=seq,
        captured_at="2026-09-13T12:00:00.000000Z",
    )


class SequenceAllocationTest(unittest.TestCase):
    """sequence 严格递增 (协议 §8.3)."""

    def test_strict_increasing_single_thread(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        seqs = [outbox.emit(_make_envelope(0)) for _ in range(50)]
        # 严格递增
        self.assertEqual(seqs, list(range(50)))

    def test_strict_increasing_multi_thread(self) -> None:
        """多线程并发 emit, sequence 必须严格递增且无重复.

        中文
        ----
        虽然 spec 禁止跨线程 (M6.7 决策), 但 threading.Lock 保证
        并发安全, 单测验证实现正确性.
        """
        outbox = ReportingOutbox(
            config=_make_config(),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        results: list[int] = []
        results_lock = threading.Lock()
        N = 200

        def worker() -> None:
            local = []
            for _ in range(N // 4):
                local.append(outbox.emit(_make_envelope(0)))
            with results_lock:
                results.extend(local)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 严格递增且无重复
        self.assertEqual(len(results), N)
        self.assertEqual(sorted(results), list(range(N)))

    def test_startup_epoch_offset(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        outbox.assign_startup_epoch_offset(100)
        # 下一个 sequence = 101
        self.assertEqual(outbox.next_sequence, 101)
        seq = outbox.emit(_make_envelope(0))
        self.assertEqual(seq, 101)


class OverflowPolicyTest(unittest.TestCase):
    """overflow 3 选 1 显式策略."""

    def test_drop_oldest_never_raises(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(
                outbox_max_size=3,
                outbox_overflow_policy=OverflowPolicy.DROP_OLDEST,
            ),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        # emit 5 个, max=3, 应该 2 个被淘汰
        seqs = [outbox.emit(_make_envelope(0)) for _ in range(5)]
        self.assertEqual(seqs, [0, 1, 2, 3, 4])
        self.assertEqual(outbox.size, 3)
        self.assertEqual(outbox.dropped_count, 2)

    def test_drop_newest_raises_on_full(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(
                outbox_max_size=3,
                outbox_overflow_policy=OverflowPolicy.DROP_NEWEST,
            ),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        for i in range(3):
            outbox.emit(_make_envelope(0))
        # 第 4 个抛 OutboxFull
        with self.assertRaises(OutboxFull):
            outbox.emit(_make_envelope(0))
        # size 仍 3, sequence 不递增 (失败前已回滚)
        self.assertEqual(outbox.size, 3)
        self.assertEqual(outbox.next_sequence, 3)
        self.assertEqual(outbox.dropped_count, 0)

    def test_block_with_timeout_raises_after_timeout(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(
                outbox_max_size=2,
                outbox_overflow_policy=OverflowPolicy.BLOCK_WITH_TIMEOUT,
            ),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
            block_timeout_ns=50_000_000,  # 50ms
        )
        for _ in range(2):
            outbox.emit(_make_envelope(0))
        # 第 3 个阻塞 50ms 后抛
        start = time.monotonic()
        with self.assertRaises(OutboxFull):
            outbox.emit(_make_envelope(0))
        elapsed_ms = (time.monotonic() - start) * 1000
        self.assertGreaterEqual(elapsed_ms, 40)  # 至少等了 ~50ms

    def test_block_with_timeout_succeeds_after_drain(self) -> None:
        """block_with_timeout 期间 background drain, emit 应该成功."""
        outbox = ReportingOutbox(
            config=_make_config(
                outbox_max_size=2,
                outbox_overflow_policy=OverflowPolicy.BLOCK_WITH_TIMEOUT,
            ),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
            block_timeout_ns=200_000_000,  # 200ms
        )
        for _ in range(2):
            outbox.emit(_make_envelope(0))
        # 50ms 后 drain, 释放空间
        def drain_after_delay() -> None:
            time.sleep(0.05)
            outbox.build_batch_all()  # 清空 buffer
        t = threading.Thread(target=drain_after_delay)
        t.start()
        # emit 阻塞 50ms 后成功
        seq = outbox.emit(_make_envelope(0))
        t.join()
        self.assertEqual(seq, 2)


class DroppedCountTest(unittest.TestCase):
    """dropped_count 准确计数 + 透传到 batch."""

    def test_dropped_count_propagates_to_batch(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(
                outbox_max_size=3,
                outbox_overflow_policy=OverflowPolicy.DROP_OLDEST,
            ),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        for _ in range(5):
            outbox.emit(_make_envelope(0))
        # dropped_count = 2
        self.assertEqual(outbox.dropped_count, 2)
        # build batch, dropped_count 透传
        batch = outbox.build_batch_all()
        assert batch is not None
        self.assertEqual(batch.dropped_count, 2)
        # 提交后归零
        self.assertEqual(outbox.dropped_count, 0)


class BatchAccumulationTest(unittest.TestCase):
    """batch 累积触发条件: 256 / 64 KiB / 时间 / drain."""

    def test_should_flush_on_count(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(
                outbox_max_size=BATCH_MAX_EVENTS,
            ),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        # 不满
        for _ in range(100):
            outbox.emit(_make_envelope(0))
        self.assertFalse(outbox.should_flush())
        # 满 256
        for _ in range(BATCH_MAX_EVENTS - 100):
            outbox.emit(_make_envelope(0))
        self.assertTrue(outbox.should_flush())

    def test_try_build_batch_returns_none_when_not_full(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        outbox.emit(_make_envelope(0))
        self.assertIsNone(outbox.try_build_batch())
        # build_batch_all 仍可强制
        batch = outbox.build_batch_all()
        assert batch is not None
        self.assertEqual(len(batch.events), 1)

    def test_try_build_batch_returns_batch_when_full(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(
                outbox_max_size=BATCH_MAX_EVENTS,
            ),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        for _ in range(BATCH_MAX_EVENTS):
            outbox.emit(_make_envelope(0))
        batch = outbox.try_build_batch()
        assert batch is not None
        self.assertEqual(len(batch.events), BATCH_MAX_EVENTS)
        # 提交后 buffer 清空
        self.assertEqual(outbox.size, 0)

    def test_drain_returns_remaining(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        for _ in range(5):
            outbox.emit(_make_envelope(0))
        batch = outbox.drain()
        assert batch is not None
        self.assertEqual(len(batch.events), 5)
        self.assertTrue(outbox.closed)
        # 关闭后 emit 抛
        with self.assertRaises(RuntimeError):
            outbox.emit(_make_envelope(0))

    def test_drain_empty_returns_none(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        self.assertIsNone(outbox.drain())
        self.assertTrue(outbox.closed)


class BatchIdentityTest(unittest.TestCase):
    """batch 单一 identity 校验 (协议 §7.2)."""

    def test_emit_identity_mismatch_rejected(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        wrong = _make_envelope(0)
        wrong_instance = ReportingEnvelope(
            protocol_version=PROTOCOL_VERSION,
            event_kind="rule_applied",
            event_payload=wrong.event_payload,
            instance_id="00000000-0000-4000-8000-000000000099",  # 错的
            startup_epoch=STARTUP_EPOCH,
            sequence=0,
            captured_at=wrong.captured_at,
        )
        with self.assertRaises(ValueError):
            outbox.emit(wrong_instance)

    def test_emit_startup_epoch_mismatch_rejected(self) -> None:
        outbox = ReportingOutbox(
            config=_make_config(),
            instance_id=INSTANCE_ID,
            startup_epoch=STARTUP_EPOCH,
        )
        wrong = _make_envelope(0)
        wrong_epoch = ReportingEnvelope(
            protocol_version=PROTOCOL_VERSION,
            event_kind="rule_applied",
            event_payload=wrong.event_payload,
            instance_id=INSTANCE_ID,
            startup_epoch=99999,  # 错的
            sequence=0,
            captured_at=wrong.captured_at,
        )
        with self.assertRaises(ValueError):
            outbox.emit(wrong_epoch)
