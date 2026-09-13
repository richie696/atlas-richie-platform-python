"""C 层私有 Supervisor 子包 (M6.1.0d-1)。

中文
----
**禁止外部 import**: 本包是 M6.1 主包私有实现, 对应 API delta v3 决策 1
"私有 vs 公开 API 二元边界"。本包 ``__all__`` 仅含
:data:`ActivationObserver` (同进程 observer hook 协议 — C 层内部测试
可用, extension **不允许**订阅), 其余符号 (Supervisor / Binding /
Activation fact / Bus) 均**不**进 ``__all__``。

包含:

- :mod:`binding` — ``_RuleSourceBinding`` frozen dataclass (C 层私有)
- :mod:`activation` — ``RuleSourceActivation`` C 层 frozen dataclass (内部 fact)
- :mod:`observer` — ``_RuleSourceActivationBus`` 同进程 pub-sub (C 层私有)
- :mod:`supervisor` — ``RuleSourceSupervisor`` 多源仲裁 (C 层私有)

**CI / static 验证**: ruff ``no-private-import`` + mypy private module
规则在 M6.1.0d-3 阶段补 (PLANNING §M6.1.0d 任务外); M6.1.0d-1 阶段
通过 contract test 验证 import 隔离。

English
--------
**Do not import from outside**: this package is M6.1 main-wheel private
implementation, per API delta v3 decision 1 "private vs public API
binary boundary". ``__all__`` contains only
:data:`ActivationObserver` (same-process observer hook protocol — C-layer
internal tests may use, but extensions **may not** subscribe), with
the other symbols (Supervisor / Binding / Activation fact / Bus) not
in ``__all__``.

Contains:

- :mod:`binding` — ``_RuleSourceBinding`` frozen dataclass (C-layer private)
- :mod:`activation` — ``RuleSourceActivation`` C-layer frozen dataclass (internal fact)
- :mod:`observer` — ``_RuleSourceActivationBus`` same-process pub-sub (C-layer private)
- :mod:`supervisor` — ``RuleSourceSupervisor`` multi-source arbitration (C-layer private)

**CI / static verification**: ruff ``no-private-import`` + mypy private
module rules are added in M6.1.0d-3 (out of M6.1.0d-1 scope); the d-1
phase relies on contract tests to assert import isolation.
"""

from .observer import ActivationObserver

__all__ = ["ActivationObserver"]

