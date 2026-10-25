"""Atlas Richie Sentinel — Agent Reporting integration (M6.5.3 + M6.5.4).

中文
----
``integration`` sub-package 内部桥接 (Mavis 治理: 私有), 把主包
RuleSourceSupervisor 状态变化 + Slot chain 执行结果 翻译成
``ReportingEvent`` 并 emit 到 AgentReporter.

3 个模块:

- :mod:`rule_source_activation` — M6.1 ``RuleSourceActivation`` fact
  → ``RULE_SOURCE_ACTIVATED`` ReportingEvent
- :mod:`source_health` — Source health 变化 (从 supervisor polling)
  → ``RULE_SOURCE_STALE`` / ``RULE_SOURCE_DEGRADED`` ReportingEvent
- :mod:`slot_chain` — Slot chain 执行结果 (M2 outcomes)
  → ``RULE_APPLIED`` / ``RULE_BLOCKED`` / ``RULE_FAILED`` ReportingEvent

**M6.5.4 实施原则**: integration 监听 Supervisor / Engine, 调
``AgentReporter.emit()`` 投递; Slot / Engine 自身不依赖 Reporter
(避免 Slot 协议污染). 1.0 integration 通过回调 (subscriber) 接入,
不修改主包 Slot / Engine 接口.

**不**暴露在 ``__all__`` (C 层私有, 跟 Mavis 治理一致).

English
--------
``integration`` sub-package internal bridge (Mavis governance: private),
translates main package ``RuleSourceSupervisor`` state changes +
Slot chain execution results into ``ReportingEvent`` and emits to
``AgentReporter``.

3 modules:

- :mod:`rule_source_activation` — M6.1 ``RuleSourceActivation`` fact
  → ``RULE_SOURCE_ACTIVATED`` ReportingEvent
- :mod:`source_health` — Source health change (from supervisor polling)
  → ``RULE_SOURCE_STALE`` / ``RULE_SOURCE_DEGRADED`` ReportingEvent
- :mod:`slot_chain` — Slot chain execution result (M2 outcomes)
  → ``RULE_APPLIED`` / ``RULE_BLOCKED`` / ``RULE_FAILED`` ReportingEvent

M6.5.4 implementation principle: integration listens to Supervisor /
Engine, calls ``AgentReporter.emit()`` to submit; Slot / Engine
themselves do not depend on Reporter (avoiding Slot protocol
pollution). 1.0 integration subscribes via callbacks; no main-package
Slot / Engine API changes.

Not in ``__all__`` (C-layer private, per Mavis governance).
"""

from __future__ import annotations

__all__: list[str] = []
