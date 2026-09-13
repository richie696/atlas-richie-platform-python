"""C 层私有: ``_RuleSourceActivationBus`` 同进程 pub-sub (M6.1.0d-1)。

中文
----
**禁止外部 import** (DESIGN §10.3 L1081-1089 / API delta v3 决策 1 /
``rule_source_activation.md`` §4)::

    # DO NOT (extension / user code)
    from atlas_richie.sentinel.source._supervisor import _RuleSourceActivationBus  # noqa

同进程 pub-sub, 单 observer 异常隔离 (P1 #2 / ``rule_source_activation.md`` §4):

- 单个 observer 抛任何异常**不能**影响 (1) 其它 observer 的调用
  (2) ``publish()`` 调用栈本身 (包括 Supervisor 的"Repository 成功
  apply + active Source 实际变更"主链路)
- 失败必须: 被记录 (warn log, **不**含 payload 内容) + 隔离到失败
  observer 自身 + 下一 publish 仍正常分发

**故意不**传播异常到 ``publish()`` 调用方, 因为:

1. ``publish()`` 在 Supervisor 的 hot path (rule 切换主链路), 一旦
   失败就破坏规则应用
2. 多 observer 模式下, 一个内部订阅者不能拖累外部订阅者

**测试可注入**: ``RuleSourceSupervisor(bindings, repository, bus=...)``
允许测试 / future 内部 metrics 注入自定义 bus。M6.1 阶段不冻结 bus
的扩展点 (e.g. 异步 observer / persistent queue), 留给 M6.5+。

English
--------
**Do not import from outside** (DESIGN §10.3 L1081-1089 / API delta v3
decision 1 / ``rule_source_activation.md`` §4)::

    # DO NOT (extension / user code)
    from atlas_richie.sentinel.source._supervisor import _RuleSourceActivationBus  # noqa

Same-process pub-sub with per-observer exception isolation (P1 #2 /
``rule_source_activation.md`` §4):

- A single observer raising any exception **must not** affect
  (1) other observers' calls (2) the ``publish()`` call stack itself
  (including the Supervisor's "Repository 成功 apply + active Source
  实际变更" hot path)
- Failures must: be recorded (warn log, **without** payload content) +
  be isolated to the failing observer + leave subsequent publishes
  unaffected

**Deliberately** does **not** propagate exceptions to ``publish()``
callers, because:

1. ``publish()`` is on the Supervisor's hot path (rule switch main
   chain); failures would break rule application.
2. In multi-observer mode, an internal subscriber must not drag down
   external subscribers.

**Test injection**: ``RuleSourceSupervisor(bindings, repository, bus=...)``
allows tests / future internal metrics to inject a custom bus. The
M6.1 phase does not freeze bus extension points (e.g. async observer /
persistent queue) — left for M6.5+.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from .activation import RuleSourceActivation


_logger = logging.getLogger(__name__)


# Type alias — same-process observer only; M6.1 does not export to extensions.
ActivationObserver = Callable[[RuleSourceActivation], None]
"""中文
----
C 层 observer hook; 同进程 only; M6.1 不导出给 extension
(``rule_source_activation.md`` §4)。

English
--------
C-layer observer hook; same-process only; M6.1 does not export to
extensions (``rule_source_activation.md`` §4).
"""


class _RuleSourceActivationBus:
    """中文
    ----
    C 层私有: 同进程 ``RuleSourceActivation`` pub-sub, observer 异常隔离。

    内部用 list + lock 维护 observers; subscribe / unsubscribe 幂等;
    publish 串行遍历, 单 observer 抛异常被 swallow + log, 其它 observer
    与 publish 调用栈不受影响。

    English
    --------
    C-layer private: same-process ``RuleSourceActivation`` pub-sub with
    per-observer exception isolation.

    Uses list + lock for observers; subscribe / unsubscribe are
    idempotent; publish iterates sequentially; a single observer
    raising is swallowed + logged without affecting other observers or
    the publish call stack.
    """

    __slots__ = ("_observers", "_lock")

    def __init__(self) -> None:
        self._observers: list[ActivationObserver] = []
        self._lock = threading.Lock()

    def subscribe(self, observer: ActivationObserver) -> None:
        """中文
        ----
        注册 observer; 同一 observer 多次注册 = 多次回调 (行为符合
        通用 pub-sub 语义; M6.1 不优化)。

        English
        --------
        Register an observer; registering the same observer multiple
        times results in multiple invocations (standard pub-sub
        semantics; M6.1 does not optimize).
        """
        with self._lock:
            self._observers.append(observer)

    def unsubscribe(self, observer: ActivationObserver) -> None:
        """中文
        ----
        取消注册 observer; 不存在则 no-op。

        English
        --------
        Unregister an observer; no-op if not present.
        """
        with self._lock:
            try:
                self._observers.remove(observer)
            except ValueError:
                pass

    def publish(self, fact: RuleSourceActivation) -> None:
        """中文
        ----
        分发 fact 给所有 observer; **单 observer 抛异常被隔离**, 主
        调用栈不受影响 (P1 #2 / ``rule_source_activation.md`` §4)。

        实现要点:

        1. 在锁内**复制** observers 列表 (避免 subscribe / unsubscribe
           在 publish 过程中被 race 干扰)
        2. 释放锁后逐个调用; 每次调用包在 ``except BaseException`` 中
        3. 异常记录到 ``_logger.warning``, **不**含 payload 内容
           (避免把 activation fact 写入日志, 防止敏感信息泄漏)
        4. 任何 observer 异常**不**重新抛出

        English
        --------
        Dispatch ``fact`` to all observers; **a single observer raising
        is isolated**, the main call stack is unaffected (P1 #2 /
        ``rule_source_activation.md`` §4).

        Implementation notes:

        1. **Copy** the observer list under the lock (avoid race with
           subscribe / unsubscribe mid-publish).
        2. Release the lock, then invoke each observer under
           ``except BaseException``.
        3. Log to ``_logger.warning`` **without** payload content (do
           not write the fact to logs — avoid leaking sensitive info).
        4. Any observer exception is **not** re-raised.
        """
        with self._lock:
            observers = list(self._observers)
        for observer in observers:
            try:
                observer(fact)
            except BaseException as exc:  # noqa: BLE001 — P1 #2 isolation
                _logger.warning(
                    "RuleSourceActivation observer raised; isolated",
                    exc_info=exc,
                )


__all__ = ["_RuleSourceActivationBus", "ActivationObserver"]
