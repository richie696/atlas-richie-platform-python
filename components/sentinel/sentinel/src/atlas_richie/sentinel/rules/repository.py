"""Sentinel RuleRepository(M1.5)。

中文
----
``RuleRepository`` 是 Engine 持有的"当前生效规则 + 上次成功应用版本"
容器,负责 8 步更新流程:

  1. **完整读取** — 拉取全部规则源数据
  2. **解析** — 把 dict / JSON / YAML 转成 ``Mapping[str, Rule]``
  3. **映射** — 校验每个 rule 类型,字段 / 范围 / 依赖
  4. **校验** — 业务级校验(优先级冲突、selector 冲突、TokenService
     可达性等)
  5. **编译索引** — 构造 ``RuleIndex``
  6. **不可变快照** — 构造 ``RuleSnapshot``
  7. **原子交换** — 整个 index 一次性替换,旧规则保持到 swap 完成
  8. **事件** — 触发 ``RuleSnapshotAppliedEvent`` 订阅者

设计要点:

- **last-known-good**:任何步骤失败,**不**清空旧规则;保持上次的
  ``RuleIndex`` 不变,记录错误
- **版本校验** ``(epoch, revision)`` 旧于当前 → 拒绝;
  相同 ``(epoch, revision)`` 但 ``checksum`` 不同 → 拒绝 + 报警
  (出现这两个值是 checksum collision 或 RuleSource bug,不能默默接受)
- **不可变快照**:``apply_snapshot(snap)`` 内部用 ``RuleIndex(snap.rules)``
  构造新 index,验证后整体替换;**不**在原地改 index

English
--------
Sentinel RuleRepository (M1.5).

``RuleRepository`` is the Engine's "currently-active rules + last
successfully applied version" container, implementing the 8-step
update flow:

  1. **Full read** — pull all rule source data.
  2. **Parse** — convert dict / JSON / YAML to ``Mapping[str, Rule]``.
  3. **Map** — validate each rule's type, fields / range / dependencies.
  4. **Validate** — business-level checks (priority conflicts, selector
     conflicts, TokenService reachability, ...).
  5. **Compile index** — build ``RuleIndex``.
  6. **Immutable snapshot** — build ``RuleSnapshot``.
  7. **Atomic swap** — replace the entire index at once; old rules
     stay live until swap completes.
  8. **Event** — fire ``RuleSnapshotAppliedEvent`` to subscribers.

Design points:

- **Last-known-good**: any step failure does **not** clear old
  rules; previous ``RuleIndex`` stays live, error recorded.
- **Version validation** — ``(epoch, revision)`` older than current
  is rejected; same ``(epoch, revision)`` with different ``checksum``
  is rejected + alert (this combination means checksum collision or
  RuleSource bug; cannot silently accept).
- **Immutable snapshot**: ``apply_snapshot(snap)`` builds a new
  ``RuleIndex`` from ``snap.rules`` and atomically replaces; never
  mutates in place."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ..errors import RuleSnapshotError
from .index import RuleIndex
from .snapshot import RuleSnapshot, RuleSnapshotAppliedEvent, RuleVersion


# Type alias for event subscribers
EventSubscriber = Callable[[RuleSnapshotAppliedEvent], None]


@dataclass(slots=True)
class _State:
    """中文
    ----
    Repository 内部状态(只有 Repository 自己访问)。

    English
    --------
    Repository internal state (Repository-only).
    """

    index: RuleIndex
    last_version: RuleVersion | None
    last_error: BaseException | None
    subscribers: list[EventSubscriber]


class RuleRepository:
    """中文
    ----
    Engine 持有的"当前生效规则"容器。

    English
    --------
    Engine's "currently-active rules" container.
    """

    def __init__(self) -> None:
        self._state = _State(
            index=RuleIndex(),
            last_version=None,
            last_error=None,
            subscribers=[],
        )

    @property
    def current_index(self) -> RuleIndex:
        """中文
        ----
        当前生效的 ``RuleIndex``(只读)。

        English
        --------
        Currently active ``RuleIndex`` (read-only).
        """
        return self._state.index

    @property
    def last_version(self) -> RuleVersion | None:
        """中文
        ----
        上次成功应用的版本;未应用过返回 ``None``。

        English
        --------
        Last successfully applied version; ``None`` if none applied yet.
        """
        return self._state.last_version

    @property
    def last_error(self) -> BaseException | None:
        """中文
        ----
        上次 apply 失败的异常;M1.5 暴露给 Engine 状态报告。

        English
        --------
        Last apply-failure exception; M1.5 exposes for Engine status
        reporting.
        """
        return self._state.last_error

    def subscribe(self, fn: EventSubscriber) -> None:
        """中文
        ----
        订阅 ``RuleSnapshotAppliedEvent``;事件触发时同步调 ``fn``,
        异常由 Repository swallow(不污染业务)。

        English
        --------
        Subscribe to ``RuleSnapshotAppliedEvent``; called synchronously
        on apply success, exceptions swallowed.
        """
        self._state.subscribers.append(fn)

    def apply_snapshot(self, snap: RuleSnapshot) -> bool:
        """中文
        ----
        应用快照(8 步更新流程)。

        返回 ``True`` 表示原子 swap 成功;``False`` 表示校验失败,
        旧 index 保持。

        校验规则:

        - 同一 ``(epoch, revision)`` 不同 ``checksum`` → 拒绝
        - 旧 ``(epoch, revision)``(任一字段更小) → 拒绝
        - 相同 ``(epoch, revision, checksum)`` 重复 apply → no-op
          (返回 ``True``,不重复触发事件)
        - ``applied_at_ns`` 字段被设置为本方法的 wall-clock

        English
        --------
        Apply snapshot (8-step flow).

        Returns ``True`` on atomic swap success; ``False`` on
        validation failure (old index kept).

        Validation:

        - Same ``(epoch, revision)`` with different ``checksum`` →
          reject.
        - Older ``(epoch, revision)`` (any field smaller) → reject.
        - Same ``(epoch, revision, checksum)`` repeated → no-op
          (returns ``True``, no duplicate event).
        - ``applied_at_ns`` is set to wall-clock of this call.
        """
        v = snap.version
        # No-op: same triple
        if (
            self._state.last_version is not None
            and self._state.last_version == v
        ):
            return True
        # Reject: same (epoch, revision) different checksum
        if self._state.last_version is not None:
            prev = self._state.last_version
            if prev.epoch == v.epoch and prev.revision == v.revision:
                if prev.checksum != v.checksum:
                    err = RuleSnapshotError(
                        f"RuleSnapshot: same (epoch, revision) but different "
                        f"checksum (prev={prev.checksum[:12]}..., new={v.checksum[:12]}...)",
                        source_id=snap.source_id,
                        version=f"{v.epoch}.{v.revision}",
                        reason="checksum_mismatch_same_epoch_revision",
                    )
                    self._state.last_error = err
                    return False
            # Reject: older
            if v < self._state.last_version:
                err = RuleSnapshotError(
                    f"RuleSnapshot: version {v.epoch}.{v.revision} < "
                    f"current {prev.epoch}.{prev.revision}",
                    source_id=snap.source_id,
                    version=f"{v.epoch}.{v.revision}",
                    reason="older_version_rejected",
                )
                self._state.last_error = err
                return False
        # 8 步: 编译 + 不可变快照(在 snapshot 构造时已经完成;这里
        # 只做 compile 阶段,即 build RuleIndex)
        try:
            new_index = RuleIndex(snap.rules)
        except Exception as e:
            err = RuleSnapshotError(
                f"RuleRepository: compile failed: {e}",
                source_id=snap.source_id,
                version=f"{v.epoch}.{v.revision}",
                reason="compile_failed",
            )
            err.__cause__ = e
            self._state.last_error = err
            return False
        # Set applied_at_ns on a copy of snap
        applied = RuleSnapshot(
            version=v,
            rules=snap.rules,
            applied_at_ns=time.time_ns(),
            source_id=snap.source_id,
        )
        # Atomic swap
        self._state.index = new_index
        self._state.last_version = v
        self._state.last_error = None
        # Fire event (M1.5 同步触发;async subscriber M1.5 末尾)
        event = RuleSnapshotAppliedEvent(
            version=v, rule_count=len(new_index), at_ns=applied.applied_at_ns
        )
        for sub in self._state.subscribers:
            try:
                sub(event)
            except BaseException:
                # Subscriber 必须不抛;但如果抛了,swallow
                pass
        return True


__all__ = ["RuleRepository", "EventSubscriber"]
