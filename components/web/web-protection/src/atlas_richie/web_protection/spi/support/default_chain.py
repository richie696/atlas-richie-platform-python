"""默认拦截器链实现：按注册顺序驱动（对位 Java DefaultWebInterceptorChain）。

并发模型
    本类**非线程安全**：每个请求一个实例，跨线程使用必须另行同步（与 Java
    一致）。

链末行为
    proceed 在游标越界时为 no-op（不抛异常），这样拦截器末尾调用一次
    proceed 无需先判边界（与 Java 一致）。

短路行为
    proceed 在 ctx 已短路时为 no-op —— 让拦截器在短路的 ctx 上调用 proceed
    不会破坏链（与 Java 一致）。
"""

from __future__ import annotations

from typing import Sequence

from ..context import WebRequestContext
from ..interceptor import WebInterceptor


class DefaultWebInterceptorChain:
    """按注册顺序驱动拦截器执行。"""

    def __init__(self, interceptors: Sequence[WebInterceptor]) -> None:
        if interceptors is None:
            raise ValueError("interceptors must not be None")
        self._interceptors = tuple(interceptors)
        self._index = 0

    def proceed(self, ctx: WebRequestContext) -> None:
        if ctx.is_short_circuited:
            return
        if self._index >= len(self._interceptors):
            return
        interceptor = self._interceptors[self._index]
        self._index += 1
        interceptor.intercept(ctx, self)

    @property
    def interceptors(self) -> tuple[WebInterceptor, ...]:
        return self._interceptors

    @property
    def current_index(self) -> int:
        """当前游标（诊断与测试断言用）。"""
        return self._index


__all__ = ["DefaultWebInterceptorChain"]
