"""容器无关的请求上下文契约（对位 Java `WebRequestContext`）。

Java 侧是一个只读入站 + 可写出站 + 生命周期的接口，适配层把各容器的原生
请求对象适配成它，拦截器链里的跨容器决策只面向它编程。

Python 侧的命名约定：
- 标量读取 → 属性
- 集合 / 带参读取 → 方法
- 写入 → 显式 setter，不提供可写属性，避免「读到的就是同一个对象」这种
  隐式共享
- 短路不抛异常：调 `mark_short_circuit` 标记，并**不要**调 `chain.proceed`
- 抛出的异常由链外层兜底成 5xx（对位 Java）。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WebRequestContext(Protocol):
    """请求上下文契约。"""

    # ───────────────────────── 只读：HTTP 入站 ─────────────────────────

    @property
    def method(self) -> str:
        """HTTP 方法（大写），如 `GET`。"""
        ...

    @property
    def path(self) -> str:
        """请求路径，不含 query string。"""
        ...

    def header(self, name: str) -> str | None:
        """取指定 header 的第一个值；不存在返回 `None`。"""
        ...

    def headers(self, name: str) -> list[str]:
        """取指定 header 的所有值；不存在返回空列表。"""
        ...

    def header_names(self) -> list[str]:
        """全部 header 名（小写）。"""
        ...

    def query_param(self, name: str) -> str | None:
        """取指定 query 参数的第一个值；不存在返回 `None`。"""
        ...

    def query_params(self) -> dict[str, list[str]]:
        """全部 query 参数。"""
        ...

    def path_variables(self) -> dict[str, str]:
        """路径变量（如 `/users/{id}` 解析出的 `id`）。"""
        ...

    # ───────────────────────── 可写：跨拦截器共享数据 ─────────────────────────

    def attribute(self, name: str) -> Any:
        """取 attribute；不存在返回 `None`。"""
        ...

    def set_attribute(self, name: str, value: Any) -> Any:
        """设置 attribute，返回旧值（无旧值返回 `None`）。"""
        ...

    def remove_attribute(self, name: str) -> Any:
        """删除 attribute，返回旧值。"""
        ...

    # ───────────────────────── 可写：响应出站 ─────────────────────────

    @property
    def response_status(self) -> int:
        """响应状态码；初始值 `200`。"""
        ...

    def set_response_status(self, status: int) -> None:
        """设置响应状态码。"""
        ...

    def response_headers(self) -> dict[str, str]:
        """全部响应头（活视图；用 `add_response_header` 修改）。"""
        ...

    def add_response_header(self, name: str, value: str) -> None:
        """追加响应头（同名覆盖）。"""
        ...

    # ───────────────────────── 可写：客户端 key / traceId ─────────────────────────

    @property
    def client_key(self) -> str | None:
        """客户端 key，由 KeyResolver 解析后写入。"""
        ...

    def set_client_key(self, key: str | None) -> None:
        """设置客户端 key。"""
        ...

    @property
    def trace_id(self) -> str | None:
        """traceId。"""
        ...

    def set_trace_id(self, trace_id: str | None) -> None:
        """设置 traceId。"""
        ...

    # ───────────────────────── 短路（deny 决策） ─────────────────────────

    @property
    def is_short_circuited(self) -> bool:
        """是否已被某个拦截器短路。"""
        ...

    def mark_short_circuit(self, status: int, body: str | None) -> None:
        """标记短路：写入响应状态码与 body 模板。"""
        ...

    @property
    def short_circuit_body(self) -> str | None:
        """短路 body 模板；无短路返回 `None`。"""
        ...

    # ───────────────────────── 错误状态 ─────────────────────────

    @property
    def error(self) -> BaseException | None:
        """当前请求上发生的异常（若有）。"""
        ...

    def set_error(self, error: BaseException | None) -> None:
        """设置异常（覆盖而非叠加）。"""
        ...

    # ───────────────────────── 生命周期 ─────────────────────────

    @property
    def start_nanos(self) -> int:
        """请求起始纳秒（单调时钟）。"""
        ...

    def close(self) -> None:
        """关闭上下文；必须幂等。"""
        ...


__all__ = ["WebRequestContext"]
