"""Sentinel RuleSnapshot / RuleVersion(M1.5)。

中文
----
``RuleSnapshot`` 是 RuleSource 推送给 Engine 的不可变规则快照;同一
``RuleVersion`` (epoch + revision + checksum) 只可能产生一种有效
RuleSnapshot。Engine 校验通过后**原子**替换本地规则;校验失败保留
last-known-good,不破坏在线服务。

设计要点:

- **三段版本号 ``epoch + revision + checksum``**:
  - ``epoch`` — 单调递增的逻辑时代(可以理解为"部署批次")
  - ``revision`` — epoch 内的修订号(顺序数字,**不**从字符串大小推断)
  - ``checksum`` — 规则正文 SHA-256;同一 (epoch, revision) 不同
    checksum 必拒绝 + 报警
- **不可变快照** (``frozen=True, slots=True``):构造后不能改;校验
  / 编译都在构造时一次性完成
- **``RuleSnapshotAppliedEvent``** 事件在 atomic swap 成功后发;
  Engine 内部事件订阅者(M1.5 占位,EventBus M1.5 末尾)消费

English
--------
Sentinel RuleSnapshot / RuleVersion (M1.5).

``RuleSnapshot`` is the immutable rule snapshot RuleSource pushes to
the Engine. A given ``RuleVersion`` (epoch + revision + checksum)
maps to exactly one valid ``RuleSnapshot``. After validation, the
Engine **atomically** replaces local rules; on validation failure
the last-known-good is kept (no in-flight service disruption).

Design points:

- **Three-part version ``epoch + revision + checksum``**:
  - ``epoch`` — monotonically increasing logical era (deployment batch).
  - ``revision`` — per-epoch integer revision (**not** derived from
    string comparison).
  - ``checksum`` — SHA-256 of rule body; same (epoch, revision) with
    different checksum is rejected + alert.
- **Immutable** (``frozen=True, slots=True``) — once built cannot
  change; validation / compile happen at construction.
- **``RuleSnapshotAppliedEvent``** fires after atomic swap; Engine's
  internal event subscribers (M1.5 placeholder) consume it."""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RuleVersion:
    """中文
    ----
    规则快照版本号 — 不可变三元组。

    - ``epoch`` — 单调递增 epoch(从 1 开始,0 保留为"未初始化")
    - ``revision`` — epoch 内的整数修订号
    - ``checksum`` — 规则正文 SHA-256 hex(64 字符)

    ``__post_init__`` 强制:

    - ``epoch >= 0``(0 = sentinel "未初始化")
    - ``revision >= 0``(0 = 当前 epoch 的初版)
    - ``checksum`` 长度 64(完整 SHA-256 hex)

    排序 / 比较: 字典序 ``(epoch, revision, checksum)``;**不**走
    字符串大小(那会因不同长度给出无意义结果)。

    English
    --------
    Rule snapshot version — immutable triple.

    - ``epoch`` — monotonically increasing epoch (0 reserved for
      "uninitialized").
    - ``revision`` — integer revision within epoch.
    - ``checksum`` — SHA-256 hex of rule body (64 chars).

    ``__post_init__`` enforces:

    - ``epoch >= 0``
    - ``revision >= 0``
    - ``checksum`` length 64 (full SHA-256 hex)

    Sort / compare: lexicographic ``(epoch, revision, checksum)``;
    **not** via string comparison (that would give meaningless results
    across different lengths)."""

    epoch: int
    revision: int
    checksum: str

    def __post_init__(self) -> None:
        if self.epoch < 0:
            raise ValueError(f"RuleVersion.epoch must be >= 0 (got {self.epoch})")
        if self.revision < 0:
            raise ValueError(
                f"RuleVersion.revision must be >= 0 (got {self.revision})"
            )
        if len(self.checksum) != 64:
            raise ValueError(
                f"RuleVersion.checksum must be 64-char SHA-256 hex "
                f"(got len={len(self.checksum)})"
            )

    @staticmethod
    def compute_checksum(rules_payload: Mapping[str, Any]) -> str:
        """中文
        ----
        计算规则正文的 SHA-256 hex(对 dict 排序后 JSON 序列化,
        保证 deterministic)。

        English
        --------
        Compute SHA-256 hex of rule body (sort-keyed JSON serialization
        for determinism).
        """
        blob = json.dumps(rules_payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def __lt__(self, other: "RuleVersion") -> bool:
        """中文
        ----
        字典序比较;epoch/revision 是 int,checksum 是同长度 hex
        字符串(64),可以走字典序。

        English
        --------
        Lexicographic compare; epoch/revision are int, checksum is
        fixed-length hex (64), so lexicographic works.
        """
        if not isinstance(other, RuleVersion):
            return NotImplemented
        return (self.epoch, self.revision, self.checksum) < (
            other.epoch, other.revision, other.checksum,
        )


@dataclass(frozen=True, slots=True)
class RuleSnapshot:
    """中文
    ----
    不可变规则快照。

    - ``version`` — ``RuleVersion`` 三元组(epoch + revision + checksum)
    - ``rules`` — 规则字典,key = rule_id,value = 规则 dataclass 实例
      (FlowRule / DegradeRule / ParamFlowRule / AuthorityRule /
      SystemRule — M2 实现)
    - ``applied_at_ns`` — Engine 原子替换的时刻(纳秒);``0`` 表示
      尚未 apply(构造中)
    - ``source_id`` — 来源 id(file / nacos / redis / ...;M3+ 引入)

    English
    --------
    Immutable rule snapshot.

    - ``version`` — ``RuleVersion`` triple.
    - ``rules`` — rule dict, key = rule_id, value = rule dataclass
      instance (FlowRule / DegradeRule / ParamFlowRule / AuthorityRule
      / SystemRule — M2 implements).
    - ``applied_at_ns`` — Engine atomic-swap time (ns); ``0`` means
      not yet applied.
    - ``source_id`` — origin id (file / nacos / redis / ...; M3+
      introduces)."""

    version: RuleVersion
    rules: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    applied_at_ns: int = 0
    source_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.rules, MappingProxyType):
            object.__setattr__(self, "rules", MappingProxyType(dict(self.rules)))
        if self.applied_at_ns < 0:
            raise ValueError(
                f"RuleSnapshot.applied_at_ns must be >= 0 (got {self.applied_at_ns})"
            )


class RuleSnapshotAppliedEvent:
    """中文
    ----
    规则快照成功 apply 后触发的事件(M1.5 占位 — EventBus 在 M1.5 末尾
    实现,目前用 dataclass + engine 内部 _emit_event 占位)。

    English
    --------
    Event fired after a rule snapshot is successfully applied
    (M1.5 placeholder — EventBus comes at M1.5 end; for now a
    dataclass + engine-internal ``_emit_event`` placeholder).
    """

    __slots__ = ("version", "rule_count", "at_ns")

    def __init__(self, version: RuleVersion, rule_count: int, at_ns: int) -> None:
        self.version = version
        self.rule_count = rule_count
        self.at_ns = at_ns


# Re-export for convenience
__all__ = [
    "RuleVersion",
    "RuleSnapshot",
    "RuleSnapshotAppliedEvent",
]
