"""Sentinel 异常根类(M1.1 集中定义)。

中文
----
``SentinelError`` 是所有 Sentinel 异常的根,直接继承 stdlib ``Exception``
以保证主包零 3rd-party 依赖(不依赖 ``atlas_richie.contracts.PlatformError``)。

M0.5-A 的层级: ``SentinelError(Exception)`` 是根,``ResilienceError`` 继承
它,5 个原语异常继承 ``ResilienceError``。M1.1 把根类从这里迁到独立
``base.py`` 模块,``__init__.py`` 仅做 re-export,避免出现"两处定义
``SentinelError``"的情况。

English
--------
Root class for all Sentinel exceptions.

``SentinelError`` is the root of the Sentinel exception tree, inheriting
stdlib ``Exception`` directly so the main wheel has zero third-party
runtime dependencies (notably ``atlas_richie.contracts.PlatformError``).

Per the M0.5-A hierarchy: ``SentinelError(Exception)`` is the root,
``ResilienceError`` inherits it, and five primitive exceptions inherit
``ResilienceError``. M1.1 moves the root class into this dedicated
``base.py`` module; ``__init__.py`` only re-exports, preventing the
"two definitions of SentinelError" footgun."""

from __future__ import annotations


class SentinelError(Exception):
    """中文
    ----
    所有 Sentinel 异常的根。直接继承 stdlib ``Exception`` 以保证主包
    零 3rd-party 依赖。

    子树分支(M0.5-A + M1.1):

    - ``ResilienceError`` — 原语直接 throw(M0 阶段 5 个具体异常)
    - ``SentinelBlockedError`` — Engine / Slot 拒绝契约(M1.1 引入)
    - ``SentinelConfigurationError`` — 配置错误(M1.1 引入)
    - ``SentinelLifecycleError`` — 生命周期非法迁移(M1.1 引入)

    用户代码通常用 ``except SentinelError`` 兜底,或更精确地用
    ``SentinelBlockedError`` / ``ResilienceError`` 分支。

    English
    --------
    Root of the Sentinel exception tree. Inherits stdlib ``Exception``
    directly so the main wheel has zero third-party runtime
    dependencies.

    Subtree branches (M0.5-A + M1.1):

    - ``ResilienceError`` — primitive-thrown (M0: 5 concrete exceptions).
    - ``SentinelBlockedError`` — Engine / Slot rejection contract (M1.1).
    - ``SentinelConfigurationError`` — config errors (M1.1).
    - ``SentinelLifecycleError`` — illegal state transitions (M1.1).

    User code typically catches ``SentinelError`` as a catch-all, or
    branches on ``SentinelBlockedError`` / ``ResilienceError`` for
    precise handling.
    """


__all__ = ["SentinelError"]
