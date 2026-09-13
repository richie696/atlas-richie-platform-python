"""Atlas Richie Sentinel — Agent Reporting V1 outbox (M6.5.5).

中文
----
Reporter 内部有界 outbox (内存, 1.0 不持久化 outbox, 跟 Cluster
Server 决策一致):

- **串行化 sequence 分配** (协议 §8.3 强制 "严格递增且连续"): 用
  ``threading.Lock`` 保护 emit() 跟 flush 之间的 race.
- **3 选 1 overflow 策略** (``OverflowPolicy``): DROP_OLDEST /
  DROP_NEWEST / BLOCK_WITH_TIMEOUT
- **dropped_count 准确计数**: 内部 ``_dropped_count`` int64, batch
  提交时透传到 ``ReportingBatch.dropped_count`` (协议 §7.2)
- **batch 累积触发**: batch 满 (256 events) / 字节满 (64 KiB) /
  时间到 (100ms) / aclose (drain) — flush 调 Reporter 私有 callback
  把 batch 投递到 transport.

**不**暴露在 ``__all__`` (Mavis 治理: outbox 私有, 不进 public API).

实现要点 (M6.7 决策):

- 1.0 ``emit()`` 是**同步** facade (不 await 外部), 所以 outbox
  操作必须 sync. 用 ``threading.Lock`` 而不是 ``asyncio.Lock`` 同步
  emit() 跟 background flush task 之间的访问.
- **Sequence 分配**: outbox 内部 counter, emit() 持锁 ++; 返回的
  sequence 跟 envelope.template 一起存到 ``_buffer`` (deque of
  ``_BufferedItem(envelope, sequence, size_bytes)``); build_batch
  时用 ``dataclasses.replace`` 把 sequence 写回 envelope (frozen
  dataclass 不可直接赋值).
- ``BLOCK_WITH_TIMEOUT`` 用 ``Condition.wait(timeout=...)`` 阻塞
  等待空位, 不会 spin-loop 浪费 CPU.

English
--------
Internal bounded outbox (in-memory, 1.0 does not persist outbox,
matching Cluster Server decision):

- **Serialized sequence allocation** (protocol §8.3 mandates
  "strictly increasing and contiguous"): uses ``threading.Lock`` to
  guard ``emit()`` against the flush.
- **3-of-3 overflow policy** (``OverflowPolicy``): DROP_OLDEST /
  DROP_NEWEST / BLOCK_WITH_TIMEOUT
- **Accurate ``dropped_count``**: internal ``_dropped_count`` int64,
  propagated to ``ReportingBatch.dropped_count`` on batch submit
  (protocol §7.2)
- **Batch accumulation triggers**: batch full (256 events) / bytes
  full (64 KiB) / time elapsed (100ms) / aclose (drain) — flush
  invokes Reporter's private callback to deliver the batch via transport.

Not in ``__all__`` (Mavis governance: outbox is private, not public).

Implementation points (per M6.7 decision):

- 1.0 ``emit()`` is **synchronous** (no external await), so outbox
  operations must be sync. Uses ``threading.Lock`` (not
  ``asyncio.Lock``) to synchronize ``emit()`` against the background
  flush task.
- **Sequence allocation**: outbox internal counter, ``emit()``
  increments under lock; the returned sequence is stored alongside
  the envelope template in ``_buffer`` (deque of
  ``_BufferedItem(envelope, sequence, size_bytes)``); ``build_batch``
  uses ``dataclasses.replace`` to write sequence back into the
  envelope (frozen dataclass).
- ``BLOCK_WITH_TIMEOUT`` uses ``Condition.wait(timeout=...)`` to
  block waiting for space; no spin-loop wasting CPU.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    ReportingBatch,
    ReportingEnvelope,
    encode_batch,
    encode_envelope,
)

from .config import (
    BATCH_MAX_BYTES,
    BATCH_MAX_EVENTS,
    AgentReporterConfig,
    OverflowPolicy,
)


# ---------------------------------------------------------------------------
# 内部 record
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class _BufferedItem:
    """Outbox buffer 单条: envelope template (sequence=0) + 分配的 sequence.

    中文
    ----
    ``envelope`` 是 template (sequence=0 占位), ``sequence`` 是 outbox
    分配的真正 sequence (frozen dataclass 不可改, build_batch 时
    ``dataclasses.replace`` 替换). ``size_bytes`` 是 envelope 编码后
    字节数 (协议 §7.1 batch 大小约束).

    English
    --------
    ``envelope`` is a template (sequence=0 placeholder); ``sequence``
    is the real sequence allocated by outbox (frozen dataclass, so
    ``build_batch`` uses ``dataclasses.replace``). ``size_bytes`` is
    encoded envelope size (protocol §7.1 batch size constraint).
    """

    envelope: ReportingEnvelope
    sequence: int
    size_bytes: int


# ---------------------------------------------------------------------------
# 内部异常 (Reporter 捕获后转 ReporterOverflowError)
# ---------------------------------------------------------------------------


class OutboxFull(Exception):
    """Outbox 内部溢出信号 (私有, **不**导出 public API).

    中文
    ----
    与 :class:`ReporterOverflowError` (用户可见) 区分: 本类是 outbox
    内部使用, 由 ``emit()`` 转换并重抛 ``ReporterOverflowError``.

    English
    --------
    Distinct from :class:`ReporterOverflowError`` (user-visible):
    this class is used internally by the outbox; ``emit()`` converts
    it to ``ReporterOverflowError`` and re-raises.
    """


# ---------------------------------------------------------------------------
# Outbox 主体
# ---------------------------------------------------------------------------


class ReportingOutbox:
    """Agent Reporter 内部有界 outbox (Mavis 治理: 私有, 不导出).

    中文
    ----
    实现要点:

    1. **emit() 串行化**: ``threading.Lock`` 保护 ``_next_sequence``
       严格递增 + 跟 protocol §8.3 "严格递增且连续" 一致.
    2. **overflow 3 选 1 策略** (DRAFT frozen 后不变, 跟 Mavis 治理
       一致): DROP_OLDEST 静默淘汰, DROP_NEWEST 抛 OutboxFull,
       BLOCK_WITH_TIMEOUT 阻塞直到有空间或 ``batch_send_interval_ns``
       超时.
    3. **batch 累积**: 字节按 envelope 实际 encoded size 累加
       (协议 §7.1 64 KiB), 满 256 触发; 满字节触发; 时间触发由
       background task 周期性调 ``try_build_batch()`` 决定.
    4. **dropped_count**: DROP_OLDEST 淘汰时 +1 (永久存活, 跨 batch
       透传, 直到 reporter 关闭).
    5. **batch 单一 identity 校验**: flush 前校验所有 envelope 的
       ``instance_id`` / ``startup_epoch`` 跟 batch 一致 (协议 §7.2).
    6. **byte estimate**: 每次 emit 调用 ``encode_envelope``, O(1)
       摊销可接受 (单个 envelope < 16 KiB, Python JSON encode ~µs 级).
    7. **sequence 替换**: build_batch 时 ``dataclasses.replace`` 把
       模板 envelope.sequence=0 替换成 outbox 分配的真正 sequence.

    English
    --------
    Implementation points:

    1. **emit() serialization**: ``threading.Lock`` guards
       ``_next_sequence`` strictly increasing; matches protocol §8.3
       "strictly increasing and contiguous".
    2. **3-of-3 overflow policy** (DRAFT after freeze, per Mavis
       governance): DROP_OLDEST silently evicts, DROP_NEWEST raises
       OutboxFull, BLOCK_WITH_TIMEOUT blocks until space or
       ``batch_send_interval_ns`` elapses.
    3. **Batch accumulation**: bytes accumulate by per-envelope
       encoded size (protocol §7.1 64 KiB); triggers on 256, on
       bytes, on time (background task periodically calls
       ``try_build_batch()``).
    4. **dropped_count**: +1 on DROP_OLDEST eviction (persistent,
       propagated across batches until reporter close).
    5. **Batch single-identity validation**: before flush, all
       envelopes' ``instance_id`` / ``startup_epoch`` must match the
       batch (protocol §7.2).
    6. **Byte estimate**: each emit calls ``encode_envelope``;
       O(1) amortized acceptable (per envelope < 16 KiB, Python JSON
       encode is µs-level).
    7. **Sequence replacement**: at ``build_batch``, use
       ``dataclasses.replace`` to swap template envelope.sequence=0
       for the real outbox-allocated sequence.
    """

    def __init__(
        self,
        *,
        config: AgentReporterConfig,
        instance_id: str,
        startup_epoch: int,
        block_timeout_ns: int | None = None,
    ) -> None:
        if config.outbox_max_size < 1:
            raise ValueError(
                f"outbox_max_size must be ≥ 1, got {config.outbox_max_size}"
            )
        if config.batch_max_events != BATCH_MAX_EVENTS:
            raise ValueError(
                f"batch_max_events must be {BATCH_MAX_EVENTS}, "
                f"got {config.batch_max_events}"
            )
        if config.batch_max_bytes != BATCH_MAX_BYTES:
            raise ValueError(
                f"batch_max_bytes must be {BATCH_MAX_BYTES}, "
                f"got {config.batch_max_bytes}"
            )
        self._max_size: int = config.outbox_max_size
        self._policy: OverflowPolicy = config.outbox_overflow_policy
        self._batch_max_events: int = config.batch_max_events
        self._batch_max_bytes: int = config.batch_max_bytes
        self._instance_id: str = instance_id
        self._startup_epoch: int = startup_epoch
        # BLOCK_WITH_TIMEOUT 默认 100ms (跟 batch_send_interval_ns 对齐)
        self._block_timeout_ns: int = (
            block_timeout_ns
            if block_timeout_ns is not None
            else config.batch_send_interval_ns
        )
        # 内部状态
        self._buffer: deque[_BufferedItem] = deque()
        self._buffered_bytes: int = 0
        self._next_sequence: int = 0
        self._dropped_count: int = 0
        self._lock: threading.Lock = threading.Lock()
        self._cond: threading.Condition = threading.Condition(self._lock)
        self._closed: bool = False

    # ------------------------------------------------------------------
    # 内部 API
    # ------------------------------------------------------------------

    @property
    def dropped_count(self) -> int:
        """当前累积 dropped_count (协议 §7.2 batch 透传)."""
        with self._lock:
            return self._dropped_count

    @property
    def size(self) -> int:
        """当前 buffer 内 envelope 数."""
        with self._lock:
            return len(self._buffer)

    @property
    def buffered_bytes(self) -> int:
        """当前 buffer 字节数 (协议 §7.1 64 KiB 约束)."""
        with self._lock:
            return self._buffered_bytes

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def next_sequence(self) -> int:
        """下一个 emit() 将分配的 sequence (含 startup_epoch 偏移)."""
        with self._lock:
            return self._next_sequence

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def policy(self) -> OverflowPolicy:
        return self._policy

    def assign_startup_epoch_offset(self, max_contiguous_sequence: int) -> None:
        """Reporter start() 时调, 把 Server 上次 ack 的
        ``max_contiguous_sequence`` + 1 作为 next_sequence 起点.

        中文
        ----
        协议 §8.3 强制 sequence 严格递增且连续; 重启后 next 从
        max_contiguous + 1 开始, 避免跟历史 sequence 重复.

        English
        --------
        Protocol §8.3 mandates strictly increasing and contiguous
        sequence; after restart, next starts from
        ``max_contiguous + 1`` to avoid colliding with history.
        """
        if max_contiguous_sequence < 0:
            raise ValueError(
                f"max_contiguous_sequence must be ≥ 0, got {max_contiguous_sequence}"
            )
        with self._lock:
            self._next_sequence = max_contiguous_sequence + 1

    def emit(self, envelope: ReportingEnvelope) -> int:
        """同步 facade, 把 envelope 入队 + 分配 sequence.

        中文
        ----
        返回分配的 sequence (int64). 本方法**不**触发 flush — flush
        走独立的 background task.

        Raises:
            OutboxFull: DROP_NEWEST 策略满 / BLOCK_WITH_TIMEOUT 策略
                超时 (Reporter 捕获后转 ``ReporterOverflowError`` 重抛)
            ValueError: 单一 identity 校验失败 (envelope instance_id
                / startup_epoch 跟 outbox 不一致)
            RuntimeError: outbox 已 closed
        """
        # 1. 单一 identity 校验 (协议 §7.2 强制): emit() 入队的 envelope
        # 必须跟 outbox 同 instance_id / startup_epoch
        if envelope.instance_id != self._instance_id:
            raise ValueError(
                f"envelope.instance_id ({envelope.instance_id}) != outbox "
                f"({self._instance_id}); identity mismatch (协议 §7.2)"
            )
        if envelope.startup_epoch != self._startup_epoch:
            raise ValueError(
                f"envelope.startup_epoch ({envelope.startup_epoch}) != outbox "
                f"({self._startup_epoch}); identity mismatch (协议 §7.2)"
            )
        size_bytes = len(encode_envelope(envelope))
        block_timeout_s = self._block_timeout_ns / 1_000_000_000
        with self._cond:
            if self._closed:
                raise RuntimeError("outbox is closed")
            # 2. overflow 处理 (3 选 1)
            if self._policy is OverflowPolicy.BLOCK_WITH_TIMEOUT:
                deadline = time.monotonic() + block_timeout_s
                while len(self._buffer) >= self._max_size:
                    if self._closed:
                        raise RuntimeError("outbox is closed")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise OutboxFull(
                            f"outbox full (max={self._max_size}), "
                            f"policy=BLOCK_WITH_TIMEOUT elapsed "
                            f"({block_timeout_s * 1000:.1f}ms)"
                        )
                    self._cond.wait(timeout=remaining)
                seq = self._next_sequence
                self._next_sequence += 1
                self._buffer.append(
                    _BufferedItem(envelope=envelope, sequence=seq, size_bytes=size_bytes)
                )
                self._buffered_bytes += size_bytes
            elif self._policy is OverflowPolicy.DROP_OLDEST:
                # 静默淘汰最老的, 永远不抛
                while len(self._buffer) >= self._max_size:
                    evicted = self._buffer.popleft()
                    self._buffered_bytes -= evicted.size_bytes
                    self._dropped_count += 1
                seq = self._next_sequence
                self._next_sequence += 1
                self._buffer.append(
                    _BufferedItem(envelope=envelope, sequence=seq, size_bytes=size_bytes)
                )
                self._buffered_bytes += size_bytes
            else:  # DROP_NEWEST
                if len(self._buffer) >= self._max_size:
                    raise OutboxFull(
                        f"outbox full (max={self._max_size}), "
                        f"policy=DROP_NEWEST"
                    )
                seq = self._next_sequence
                self._next_sequence += 1
                self._buffer.append(
                    _BufferedItem(envelope=envelope, sequence=seq, size_bytes=size_bytes)
                )
                self._buffered_bytes += size_bytes
            # 唤醒可能在等空间的调用方 (DROP_NEWEST / BLOCK_WITH_TIMEOUT
            # 走 try_flush 后有空间, 通知 cond)
            self._cond.notify_all()
            return seq

    def should_flush(self) -> bool:
        """检查是否满足 flush 触发条件 (256 / 64 KiB).

        中文
        ----
        不动 buffer, 只读. 时间触发 (100ms) 由 background task 周期性
        调 ``try_build_batch()`` 处理.

        English
        --------
        Read-only, no buffer mutation. Time trigger (100ms) is
        handled by the background task periodically calling
        ``try_build_batch()``.
        """
        with self._lock:
            if not self._buffer:
                return False
            return (
                len(self._buffer) >= self._batch_max_events
                or self._buffered_bytes >= self._batch_max_bytes
            )

    def try_build_batch(self) -> ReportingBatch | None:
        """满足触发条件时构造并返回 batch, 清空 buffer; 否则返回 None.

        中文
        ----
        同步版本 (不 await 外部), 由 background task 在 event loop
        里调. 满足条件 = (256 events) OR (64 KiB). 时间触发由
        background task 周期性直接调 ``build_batch_all()`` 实现.

        English
        --------
        Sync version (no external await), called by background task
        in the event loop. Triggers: (256 events) OR (64 KiB). Time
        trigger is implemented by background task periodically
        calling ``build_batch_all()`` directly.
        """
        with self._cond:
            if not self._buffer:
                return None
            if not (
                len(self._buffer) >= self._batch_max_events
                or self._buffered_bytes >= self._batch_max_bytes
            ):
                return None
            return self._build_batch_locked()

    def build_batch_all(self) -> ReportingBatch | None:
        """无条件构造 batch (即使不满触发条件). 留给时间触发 + drain.

        中文
        ----
        background task 周期到 (100ms) 调; ``drain()`` 内部也调.
        即使只 1 个 envelope 也构造 (协议 §7.1 强制
        ``events.length ∈ [1, 256]``).

        English
        --------
        Called by background task on period (100ms); also by
        ``drain()``. Constructs even for 1 envelope (protocol §7.1
        mandates ``events.length ∈ [1, 256]``).
        """
        with self._cond:
            if not self._buffer:
                return None
            return self._build_batch_locked()

    def drain(self) -> ReportingBatch | None:
        """aclose() 调用, 强制 flush 最后一批. 置 ``_closed=True``.

        中文
        ----
        永远返回 batch (即使 1 envelope 也 flush), 除非 buffer 真的空.
        设 closed 后, 后续 emit 抛 RuntimeError.

        English
        --------
        Always returns a batch (even for 1 envelope), unless buffer
        is truly empty. After closed, subsequent ``emit`` raises
        ``RuntimeError``.
        """
        with self._cond:
            self._closed = True
            if not self._buffer:
                self._cond.notify_all()
                return None
            batch = self._build_batch_locked()
            self._cond.notify_all()
            return batch

    def notify_drain(self) -> None:
        """drain 完成时通知, 让 BLOCK_WITH_TIMEOUT 等待方能感知 closed."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def _build_batch_locked(self) -> ReportingBatch:
        """在 lock 内构造 ReportingBatch + 清空 buffer. 调方负责持锁."""
        # 1. 强制单一 identity 校验 (协议 §7.2)
        for item in self._buffer:
            ev = item.envelope
            if ev.instance_id != self._instance_id:
                raise ValueError(
                    f"batch single-identity violated: instance_id "
                    f"{ev.instance_id} != {self._instance_id} (协议 §7.2)"
                )
            if ev.startup_epoch != self._startup_epoch:
                raise ValueError(
                    f"batch single-identity violated: startup_epoch "
                    f"{ev.startup_epoch} != {self._startup_epoch} (协议 §7.2)"
                )
        # 2. 用 dataclasses.replace 把 sequence 写回 envelope
        envelopes: list[ReportingEnvelope] = [
            replace(item.envelope, sequence=item.sequence)
            for item in self._buffer
        ]
        batch = ReportingBatch(
            protocol_version=PROTOCOL_VERSION,
            instance_id=self._instance_id,
            startup_epoch=self._startup_epoch,
            batch_id=str(uuid.uuid4()),
            sent_at=_now_iso_utc_micro(),
            events=envelopes,
            dropped_count=self._dropped_count,
        )
        # 3. 提交完清空 buffer + dropped_count 归零 (协议 §7.2 累积)
        self._buffer.clear()
        self._buffered_bytes = 0
        self._dropped_count = 0
        # 4. batch 太大校验: 协议 §7.1 强制 ≤ 64 KiB
        encoded = encode_batch(batch)
        if len(encoded) > self._batch_max_bytes:
            # 不可恢复 (单个 envelope 已超 16 KiB 才会出现, 上一级已校验)
            raise RuntimeError(
                f"built batch exceeds {self._batch_max_bytes} bytes "
                f"(actual: {len(encoded)})"
            )
        return batch


def _now_iso_utc_micro() -> str:
    """ISO 8601 UTC microsecond, 跟 codec 严格 regex 一致."""
    return (
        datetime.now(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.%f")
    ) + "Z"


__all__: list[str] = []  # 全部私有, Reporter 内部使用
