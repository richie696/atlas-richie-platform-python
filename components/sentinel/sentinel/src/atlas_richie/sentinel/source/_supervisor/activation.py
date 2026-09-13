"""C 层私有: ``RuleSourceActivation`` internal fact (M6.1.0d-1)。

中文
----
**禁止外部 import** (DESIGN §10.3 L1073-1079 / API delta v3 决策 4 /
``rule_source_activation.md`` §1.3)::

    # DO NOT (extension / user code)
    from atlas_richie.sentinel.source._supervisor import RuleSourceActivation  # noqa

本类是 M6.1 主包内部 Supervisor 暴露的 **activation fact** 的 C 层
frozen dataclass shape。**不**是跨语言 wire protocol, **不**冻结任何
``event_name`` 字符串常量、跨进程 transport 或时间戳字段。

**3 条件 AND emit** (``rule_source_activation.md`` §2):

1. ``RuleRepository.apply_snapshot(snap)`` 返回 ``True``
2. active Source **实际**变更 (``new_source_id != old_source_id``)
3. 业务语义属于真实切换 (not "all_stale" / not "no-op manual_replace")

**不 emit** 的场景 (同 §2):

- 同一 active Source 的 checksum 刷新 (走 M6.5.7 envelope Reporter
  health event, 不进 activation fact)
- 所有 ready Source 都 stale, 切换被拒绝, 维持 last-known-good
  (同上, health event)
- ``assemble_sources()`` 再次调用, 但所有 binding 解析后 active
  Source 不变 (静默 no-op)
- Repository 拒绝 candidate (apply_snapshot 返回 False) (静默 no-op)

**字段**:

- ``previous_source_id: str | None`` — 切换前 active; ``None`` = 第一次
  activation
- ``source_id: str`` — 切换后新 active
- ``version: RuleVersion`` — 实际 apply 成功的版本 (M0 公共)
- ``reason: Literal["initial", "failover", "manual_replace"]`` —
  3 个固定值, 1.x 阶段**不**扩展

**不**含:

- 时间戳 (M6.5.7 envelope 提供 ``captured_at`` + ``received_at``,
  二者分离)
- 规则正文 (走 ``RuleSnapshot`` 单独通道)
- 凭证 / endpoint / 业务内容

English
--------
**Do not import from outside** (DESIGN §10.3 L1073-1079 / API delta v3
decision 4 / ``rule_source_activation.md`` §1.3)::

    # DO NOT (extension / user code)
    from atlas_richie.sentinel.source._supervisor import RuleSourceActivation  # noqa

This is the C-layer **frozen dataclass** shape of the M6.1 main-wheel
internal activation fact emitted by ``RuleSourceSupervisor``. **Not** a
cross-language wire protocol, **does not** freeze any ``event_name``
string constant, cross-process transport, or timestamp field.

**3-condition AND emit** (``rule_source_activation.md`` §2):

1. ``RuleRepository.apply_snapshot(snap)`` returns ``True``
2. active Source **actually** changed (``new_source_id != old_source_id``)
3. the change is a real switch (not "all_stale" / not "no-op
   manual_replace")

**No-emit** cases (per §2):

- Same active Source's checksum refresh (M6.5.7 envelope Reporter
  health event, not an activation fact)
- All ready Sources stale, switch rejected, last-known-good kept
  (same — health event)
- ``assemble_sources()`` called again, but active Source unchanged
  (silent no-op)
- Repository rejected candidate (silent no-op)

**Fields**:

- ``previous_source_id: str | None`` — pre-switch active; ``None`` =
  first activation
- ``source_id: str`` — post-switch new active
- ``version: RuleVersion`` — actually applied version (M0 public)
- ``reason: Literal["initial", "failover", "manual_replace"]`` —
  3 fixed values, not extended during 1.x

**Does not contain**:

- Timestamps (M6.5.7 envelope provides ``captured_at`` +
  ``received_at``, separated)
- Rule body (goes through ``RuleSnapshot``)
- Credentials / endpoints / business content
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...rules.snapshot import RuleVersion


@dataclass(frozen=True, slots=True)
class RuleSourceActivation:
    """中文
    ----
    Supervisor emit 的内部 activation fact (C 层 frozen dataclass)。

    M6.1 范围: 同进程 C 层 only。
    M6.5.7 envelope 冻结后, 本 fact 会由 M6.5 Reporter 转换为跨语言
    envelope 事件, 经 M6.5.1 父协议 transport 投到 wire。

    English
    --------
    Internal activation fact emitted by Supervisor (C-layer frozen
    dataclass).

    M6.1 scope: same-process C layer only.
    After M6.5.7 envelope is frozen, M6.5 Reporter will convert this
    fact into a cross-language envelope event and project it through
    the M6.5.1 父协议 transport.
    """

    previous_source_id: str | None
    source_id: str
    version: "RuleVersion"
    reason: Literal["initial", "failover", "manual_replace"]


# __all__ is intentionally EMPTY: ``RuleSourceActivation`` is a C-layer
# internal fact, NOT re-exported by ``import *`` (rule_source_activation.md
# §3.1 "extension **不**能 import 这个类"). C-layer tests import it
# directly via ``from .activation import RuleSourceActivation``.
__all__: list[str] = []
