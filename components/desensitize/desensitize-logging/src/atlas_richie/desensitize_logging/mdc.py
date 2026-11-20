"""MDC 上下文（对位 Java 的 SLF4J `MDC`）。

Java 的 MDC 是 `ThreadLocal<Map<String, String>>`；Python 标准库没有 MDC，
最接近的是 `contextvars.ContextVar` —— 它同时覆盖**线程**与 **asyncio 任务**
（ThreadLocal 做不到后者：asyncio 任务在同一线程里交错执行）。

两条硬约定：

- **写入永远换新 dict**：ContextVar 的默认值是**共享对象**，原地改会跨请求串味
- **取值永远拷贝**：调用方拿到的是快照，改它不影响上下文

MDC 的值按 Java 约定是字符串；允许 `None` 存在（脱敏后保留为 None，
与 Java `maskMdc` 的行为一致），但写入 None 不推荐 —— formatter 会渲染成 `None`。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_MDC: ContextVar[dict[str, str | None]] = ContextVar("atlas_richie_desensitize_mdc", default={})


class MdcContext:
    """MDC 上下文门面（静态方法）。

    用法：

    ```python
    MdcContext.put("traceId", "abc123")
    with MdcContext.scope(userId="u-1"):
        logger.info("handling request")
    ```

    `scope` 退出时**恢复**原上下文（对位 Java 的 `MDC.putCloseable`）。
    """

    @staticmethod
    def current() -> dict[str, str | None]:
        """当前上下文的快照（拷贝）。"""
        return dict(_MDC.get())

    @staticmethod
    def get(key: str) -> str | None:
        """取一个键；不存在返回 None。"""
        return _MDC.get().get(key)

    @staticmethod
    def put(key: str, value: str | None) -> None:
        """写一个键（换新 dict，不原地改）。"""
        _MDC.set({**_MDC.get(), key: value})

    @staticmethod
    def remove(key: str) -> None:
        """删一个键；不存在时是 no-op。"""
        current = _MDC.get()
        if key in current:
            _MDC.set({k: v for k, v in current.items() if k != key})

    @staticmethod
    def clear() -> None:
        """清空上下文。"""
        _MDC.set({})

    @staticmethod
    @contextmanager
    def scope(**pairs: str | None) -> Iterator["MdcContext"]:
        """临时作用域：进入时叠加若干键，退出时**恢复**原上下文。

        恢复用「写回旧 dict」而不是 `ContextVar.reset(token)` —— token 只能
        在创建它的 context 里 reset，跨 asyncio 任务复用会抛 ValueError。
        """
        previous = _MDC.get()
        _MDC.set({**previous, **pairs})
        try:
            yield MdcContext
        finally:
            _MDC.set(previous)


__all__ = ["MdcContext"]
