"""Atlas Richie Sentinel — Agent Reporter Ack handler (C 层, Mavis 治理).

中文
----
``AckHandler`` 接收 transport.submit 返回的 ``AckEnvelope``, 处理:

1. 校验 ack.ack_sequences 长度必须 1 (协议 §9.2)
2. 校验 ack.ack_sequences[0].instance_id / startup_epoch 跟 reporter 一致
3. 更新 ``max_contiguous_sequence`` (单调非减)
4. 累计 ``duplicate_count`` (协议 §9.2 字段, 1.0 不暴露 public API)
5. 任何不一致 → 协议错 (raise ``ReporterProtocolError`` 让 supervisor fatal)

**不**导出 ``__all__`` (C 层私有, 跟 Mavis 治理一致).

English
--------
``AckHandler`` receives the ``AckEnvelope`` returned by
``transport.submit`` and handles:

1. Validate ``ack.ack_sequences`` length must be 1 (protocol §9.2)
2. Validate ``ack.ack_sequences[0].instance_id`` / ``startup_epoch``
   match the reporter
3. Update ``max_contiguous_sequence`` (monotonic non-decreasing)
4. Accumulate ``duplicate_count`` (protocol §9.2 field, 1.0 not in
   public API)
5. Any inconsistency → protocol error (raise ``ReporterProtocolError``
   to let supervisor mark fatal)

Not in ``__all__`` (C-layer private, per Mavis governance).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlas_richie.contracts.reporting.v1 import AckEnvelope

from ..errors import ReporterProtocolError


@dataclass(slots=True)
class AckHandler:
    """Agent Reporter 内部 ack handler (C 层私有).

    中文
    ----
    跟 ``AgentReporterSupervisor`` 同 lifecycle, 由 supervisor 持有
    引用; ``handle()`` 是 supervisor 调 transport.submit 成功后
    触发的 callback. 状态包括:

    - ``max_contiguous_sequence`` — 单调非减 int64
    - ``duplicate_count`` — 跨 batch 累计 (不归零, reporter 关闭归零)

    跟 Cluster Server 决策一致: 1.0 不暴露 ``duplicate_count`` 到
    public API (内部 metrics).

    English
    --------
    Same lifecycle as ``AgentReporterSupervisor``; supervisor holds
    the reference; ``handle()`` is the callback triggered after
    supervisor calls ``transport.submit`` successfully. State:

    - ``max_contiguous_sequence`` — monotonic non-decreasing int64
    - ``duplicate_count`` — accumulates across batches (not reset
      until reporter close)

    Per Cluster Server decision: 1.0 does not expose ``duplicate_count``
    in public API (internal metrics only).
    """

    instance_id: str
    startup_epoch: int
    max_contiguous_sequence: int = 0
    duplicate_count: int = 0

    def handle(self, ack: AckEnvelope) -> None:
        """处理 Server ack, 校验 + 更新状态.

        Raises:
            ReporterProtocolError: 协议字段不一致 (length != 1 / identity
                不匹配 / sequence 倒退)
        """
        # 1. 长度校验
        if len(ack.ack_sequences) != 1:
            raise ReporterProtocolError(
                f"ack.ack_sequences must be length 1 (协议 §9.2), "
                f"got {len(ack.ack_sequences)}",
                code="MALFORMED_ENVELOPE",
            )
        seq = ack.ack_sequences[0]
        # 2. identity 校验
        if seq.instance_id != self.instance_id:
            raise ReporterProtocolError(
                f"ack.ack_sequences[0].instance_id ({seq.instance_id}) != "
                f"reporter ({self.instance_id}); identity mismatch",
                code="MALFORMED_ENVELOPE",
            )
        if seq.startup_epoch != self.startup_epoch:
            raise ReporterProtocolError(
                f"ack.ack_sequences[0].startup_epoch ({seq.startup_epoch}) != "
                f"reporter ({self.startup_epoch}); identity mismatch",
                code="MALFORMED_ENVELOPE",
            )
        # 3. sequence 单调非减
        if seq.max_contiguous_sequence < self.max_contiguous_sequence:
            raise ReporterProtocolError(
                f"ack.sequences[0].max_contiguous_sequence "
                f"({seq.max_contiguous_sequence}) < current "
                f"({self.max_contiguous_sequence}); non-monotonic (协议 §9.2)",
                code="SEQUENCE_NOT_MONOTONIC",
            )
        self.max_contiguous_sequence = seq.max_contiguous_sequence
        # 4. duplicate_count 累计
        if ack.duplicate_count < 0:
            raise ReporterProtocolError(
                f"ack.duplicate_count must be ≥ 0, got {ack.duplicate_count}",
                code="MALFORMED_ENVELOPE",
            )
        self.duplicate_count += ack.duplicate_count

    def reset(self) -> None:
        """Reporter 关闭时调, 清状态 (1.0 next reporter 重新构造)."""
        self.max_contiguous_sequence = 0
        self.duplicate_count = 0


__all__: list[str] = []  # C 层私有
