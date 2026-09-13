"""C 层私有: ``_RuleSourceBinding`` frozen dataclass (M6.1.0d-1)。

中文
----
**禁止外部 import** (DESIGN §10.3 L1081-1089 / API delta v3 决策 1)::

    # DO NOT (extension / user code)
    from atlas_richie.sentinel.source._supervisor import _RuleSourceBinding  # noqa

``_RuleSourceBinding`` 是 ``RuleSourceAssembly`` (公开 immutable DTO)
经过 Engine 公开装配入口 ``assemble_sources()`` 校验后, 由
``SentinelEngine`` 转换为的 **C 层私有** binding。它包含优先级 (priority)
和短抖动容错窗口 (``failover_after``) 等 Supervisor 仲裁所需的内部状态,
但**不**对外暴露。私有 binding 不能成为公开方法的入参 (DESIGN §10.3
L1085-1086)。

字段说明:

- ``source_id`` — 用户在 ``RuleSourceAssembly`` 中提供的稳定字符串
  (e.g. ``"nacos-prod"``); **不**自动用 endpoint / path / token 构造
  (rule_source_activation.md §7)
- ``source`` — 同进程内的 ``SnapshotRuleSource`` 实现 (新契约)
- ``priority`` — 大值优先; Supervisor 启动时校验全局唯一
  (重复 = 公共装配入口契约违反, 由 contract test 兜底)
- ``failover_after`` — 短抖动容错窗口; active Source stale 后,
  在 ``failover_after`` 到期前 Supervisor 仍保留 last-known-good,
  防止短抖动触发切换

English
--------
**Do not import from outside** (DESIGN §10.3 L1081-1089 / API delta v3
decision 1)::

    # DO NOT (extension / user code)
    from atlas_richie.sentinel.source._supervisor import _RuleSourceBinding  # noqa

``_RuleSourceBinding`` is the **C-layer private** binding produced by
``SentinelEngine.assemble_sources()`` after validating the public
immutable DTO ``RuleSourceAssembly``. It carries the internal state the
Supervisor needs for arbitration — priority and short-jitter tolerance
window — but is **never** exposed. Private bindings may not appear as
public method parameters (DESIGN §10.3 L1085-1086).

Fields:

- ``source_id`` — user-supplied stable string in
  ``RuleSourceAssembly`` (e.g. ``"nacos-prod"``); never auto-derived
  from endpoint / path / token (rule_source_activation.md §7).
- ``source`` — same-process ``SnapshotRuleSource`` implementation.
- ``priority`` — larger wins; Supervisor validates global uniqueness
  at start (duplicates = public contract violation, caught by
  contract tests).
- ``failover_after`` — short-jitter tolerance window; while active
  Source is stale, Supervisor keeps the last-known-good until the
  window elapses, to avoid flap-driven thrashing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..rule_source import SnapshotRuleSource


@dataclass(frozen=True, slots=True)
class _RuleSourceBinding:
    """中文
    ----
    C 层私有: 一个 ``SnapshotRuleSource`` 的多源仲裁绑定。

    公开装配入口 ``SentinelEngine.assemble_sources()`` 把每个
    ``RuleSourceAssembly`` 转换为一个 ``_RuleSourceBinding``; Supervisor
    持有 ``Sequence[_RuleSourceBinding]`` 做出 active 选择。

    **不能**成为公开方法入参; **不能** import 到 extension。

    English
    --------
    C-layer private: one ``SnapshotRuleSource``'s multi-source
    arbitration binding.

    The public assembly entry ``SentinelEngine.assemble_sources()``
    converts each ``RuleSourceAssembly`` into a ``_RuleSourceBinding``;
    the Supervisor holds a ``Sequence[_RuleSourceBinding]`` to make the
    active selection.

    **May not** appear as a public method parameter; **may not** be
    imported into extensions.
    """

    source_id: str
    source: "SnapshotRuleSource"
    priority: int
    failover_after: timedelta


__all__ = ["_RuleSourceBinding"]
