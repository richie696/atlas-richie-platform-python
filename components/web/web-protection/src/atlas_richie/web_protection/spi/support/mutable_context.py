"""默认请求上下文实现（对位 Java 的 MutableWebRequestContext）。

适用场景：
- 单元测试：直接构造，传入字段即可
- 适配层：作为基类持有框架原生请求引用，本类提供全部字段存取
- 非框架场景（mock transport）：直接用本类

不可变部分
    构造时传入的 method / path / headers / query_params / path_variables 一旦
    构造不可变。Java 用 Map.copyOf / List.copyOf 做不可变拷贝，Python 侧改为
    「构造时拷进内部元组，读取时再返回新列表」，避免调用方拿到内部容器的
    引用后绕过拷贝语义。

线程安全
    本类**非线程安全**：每个请求一个实例。跨线程使用必须另行同步（与 Java
    一致）。
"""

from __future__ import annotations

import time
from typing import Any, Iterable, Mapping


def _copy_multi_map(source: Mapping[str, Iterable[str] | str] | None) -> dict[str, tuple[str, ...]]:
    """拷贝多值 map：key 转小写，值拷成不可变元组。

    值可以是多值序列，也可以是单个字符串 —— 单个字符串按**一个值**处理，
    不按字符序列拆开（str 本身是 Iterable[str]，直接 tuple() 会把
    "edge-1" 拆成 ('e','d','g','e','-','1')，是个静默的坑）。
    """
    if source is None:
        return {}
    copied: dict[str, tuple[str, ...]] = {}
    for name, values in source.items():
        if isinstance(values, str):
            copied[name.lower()] = (values,)
        else:
            copied[name.lower()] = tuple(values)
    return copied


class MutableWebRequestContext:
    """可变请求上下文：入站部分构造后不可变，出站部分与 attribute 可写。"""

    def __init__(
        self,
        method: str,
        path: str,
        headers: Mapping[str, Iterable[str] | str] | None = None,
        query_params: Mapping[str, Iterable[str] | str] | None = None,
        path_variables: Mapping[str, str] | None = None,
    ) -> None:
        if method is None:
            raise ValueError("method must not be None")
        if path is None:
            raise ValueError("path must not be None")
        self._method = str(method).upper()
        self._path = str(path)
        self._headers = _copy_multi_map(headers)
        self._query_params = _copy_multi_map(query_params)
        self._path_variables = dict(path_variables or {})
        self._attributes: dict[str, Any] = {}
        self._response_headers: dict[str, str] = {}
        self._response_status = 200
        self._client_key: str | None = None
        self._trace_id: str | None = None
        self._short_circuited = False
        self._short_circuit_body: str | None = None
        self._error: BaseException | None = None
        self._closed = False
        self._start_nanos = time.monotonic_ns()

    # ───────────────────────── 只读 ─────────────────────────

    @property
    def method(self) -> str:
        return self._method

    @property
    def path(self) -> str:
        return self._path

    def header(self, name: str) -> str | None:
        values = self._headers.get(name.lower())
        return values[0] if values else None

    def headers(self, name: str) -> list[str]:
        return list(self._headers.get(name.lower(), ()))

    def header_names(self) -> list[str]:
        return list(self._headers.keys())

    def query_param(self, name: str) -> str | None:
        values = self._query_params.get(name)
        return values[0] if values else None

    def query_params(self) -> dict[str, list[str]]:
        return {name: list(values) for name, values in self._query_params.items()}

    def path_variables(self) -> dict[str, str]:
        return dict(self._path_variables)

    # ───────────────────────── attributes ─────────────────────────

    def attribute(self, name: str) -> Any:
        return self._attributes.get(name)

    def set_attribute(self, name: str, value: Any) -> Any:
        previous = self._attributes.get(name)
        self._attributes[name] = value
        return previous

    def remove_attribute(self, name: str) -> Any:
        return self._attributes.pop(name, None)

    # ───────────────────────── response ─────────────────────────

    @property
    def response_status(self) -> int:
        return self._response_status

    def set_response_status(self, status: int) -> None:
        self._response_status = status

    def response_headers(self) -> dict[str, str]:
        return self._response_headers

    def add_response_header(self, name: str, value: str) -> None:
        self._response_headers[name] = value

    # ───────────────────────── client key / trace id ─────────────────────────

    @property
    def client_key(self) -> str | None:
        return self._client_key

    def set_client_key(self, key: str | None) -> None:
        self._client_key = key

    @property
    def trace_id(self) -> str | None:
        return self._trace_id

    def set_trace_id(self, trace_id: str | None) -> None:
        self._trace_id = trace_id

    # ───────────────────────── short circuit ─────────────────────────

    @property
    def is_short_circuited(self) -> bool:
        return self._short_circuited

    def mark_short_circuit(self, status: int, body: str | None) -> None:
        self._response_status = status
        self._short_circuit_body = body
        self._short_circuited = True

    @property
    def short_circuit_body(self) -> str | None:
        return self._short_circuit_body

    # ───────────────────────── error ─────────────────────────

    @property
    def error(self) -> BaseException | None:
        return self._error

    def set_error(self, error: BaseException | None) -> None:
        self._error = error

    # ───────────────────────── lifecycle ─────────────────────────

    @property
    def start_nanos(self) -> int:
        return self._start_nanos

    def close(self) -> None:
        """幂等：重复调用无副作用。"""
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed

    # ───────────────────────── 便捷构造 ─────────────────────────

    @classmethod
    def builder(cls) -> "MutableWebRequestContextBuilder":
        return MutableWebRequestContextBuilder()


class MutableWebRequestContextBuilder:
    """构造器风格的 builder，便于测试与适配层装配。"""

    def __init__(self) -> None:
        self._method = "GET"
        self._path = "/"
        self._headers: dict[str, list[str]] = {}
        self._query_params: dict[str, list[str]] = {}
        self._path_variables: dict[str, str] = {}

    def method(self, method: str) -> "MutableWebRequestContextBuilder":
        self._method = method
        return self

    def path(self, path: str) -> "MutableWebRequestContextBuilder":
        self._path = path
        return self

    def header(self, name: str, value: str) -> "MutableWebRequestContextBuilder":
        self._headers.setdefault(name.lower(), []).append(value)
        return self

    def query_param(self, name: str, value: str) -> "MutableWebRequestContextBuilder":
        self._query_params.setdefault(name, []).append(value)
        return self

    def path_variable(self, name: str, value: str) -> "MutableWebRequestContextBuilder":
        self._path_variables[name] = value
        return self

    def build(self) -> MutableWebRequestContext:
        return MutableWebRequestContext(
            method=self._method,
            path=self._path,
            headers=self._headers,
            query_params=self._query_params,
            path_variables=self._path_variables,
        )


__all__ = ["MutableWebRequestContext", "MutableWebRequestContextBuilder"]
