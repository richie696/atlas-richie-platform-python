"""Atlas Richie Sentinel — Agent Reporter 私有 _supervisor (Mavis 治理).

中文
----
私有 ``_supervisor`` sub-package, 仿主包 ``source/_supervisor/`` 的
C/B 二元治理 (richie696 2026-09-13):

- **C 实现层** (本 sub-package): 内部状态机 + ack 处理 + background
  task 编排; **不**导出 ``__all__``, 用户代码不能 ``import`` 内部
  supervisor.
- **B 契约层** (``AgentReporter``): 唯一公开装配入口, 由 AgentReporter
  内部在 ``start()`` 构造 supervisor; 1.0 公开 API 锁住.

**Mavis 决策**: ``_supervisor`` 模块是 C 层 (主包私有); 1.0 任何
``from atlas_richie.sentinel.reporting._supervisor import ...`` 都
应该被视为 breaking (richie696 治理). 公开入口永远是 ``AgentReporter``.

English
--------
Private ``_supervisor`` sub-package, following the main package
``source/_supervisor/`` C/B dual-track governance (richie696 2026-09-13):

- **C implementation layer** (this sub-package): internal state
  machine + ack handling + background task orchestration; **not**
  in ``__all__``; user code cannot import the internal supervisor.
- **B contract layer** (``AgentReporter``): the single public
  assembly entry, constructed by ``AgentReporter`` internally in
  ``start()``; 1.0 public API locked.

Mavis decision: ``_supervisor`` is a C-layer (main-package private)
module; any 1.0 ``from atlas_richie.sentinel.reporting._supervisor
import ...`` is considered breaking (richie696 governance). The
public entry is always ``AgentReporter``.
"""

from __future__ import annotations

# 注意: 不导出任何符号 (``__all__ = []``) — C 层私有, 跟 Mavis 治理一致.
__all__: list[str] = []
