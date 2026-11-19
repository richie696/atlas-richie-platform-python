"""容器无关的拦截器与拦截器链（对位 Java `WebInterceptor` / `WebInterceptorChain`）。

Java 侧是「拦截器在请求生命周期某个时点执行，通过拦截器链驱动后续拦截器」。

短路语义（对位 Java 的 WebInterceptor 注释）：
- 拦截器**不应**抛异常短路 —— 应调 `mark_short_circuit` 标记，并且**不要**调
  `chain.proceed`
- 抛出的异常由链外层包装成 5xx 响应。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .context import WebRequestContext


@runtime_checkable
class WebInterceptor(Protocol):
    """拦截器接口。"""

    def intercept(self, ctx: WebRequestContext, chain: "WebInterceptorChain") -> None:
        """拦截器入口。

        - 放行 → 调 `chain.proceed(ctx)`
        - 拒绝 → 调 `mark_short_circuit(...)` 并且**不**调 `chain.proceed(ctx)`
        """
        ...


@runtime_checkable
class WebInterceptorChain(Protocol):
    """拦截器链。"""

    def proceed(self, ctx: WebRequestContext) -> None:
        """驱动下一个拦截器执行；已到链末为 no-op。"""
        ...

    @property
    def interceptors(self) -> tuple[WebInterceptor, ...]:
        """当前链持有的全部拦截器（按注册顺序，只读）。"""
        ...


__all__ = ["WebInterceptor", "WebInterceptorChain"]
