"""租户上下文（对位 Java `TenantContext` / `ThreadLocalHolder`）。

Java 用 ThreadLocal；Python 用 contextvars——它天然跨 asyncio 任务传播，
且 `copy_context()` 可显式带到新线程（对位 Java 的 TenantTaskDecorator /
StructuredTaskScope 上下文传播）。

`run_with_tenant` 保存并恢复前值（嵌套调用安全），异常时也恢复——上下文
泄漏会让一个请求的租户串到另一个请求，是隔离事故。
"""

from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from typing import Callable, Protocol, TypeVar, runtime_checkable

from .errors import TenantError, TenantErrorCode
from .model import TenantPrincipal

T = TypeVar("T")

_CURRENT: contextvars.ContextVar[TenantPrincipal | None] = contextvars.ContextVar(
    "tenant-principal", default=None
)


@runtime_checkable
class TenantContextHolder(Protocol):
    def run_with_tenant(self, principal: TenantPrincipal, task: Callable[[], T]) -> T: ...

    def get(self) -> TenantPrincipal | None: ...

    def clear(self) -> None: ...


class ContextVarHolder:
    """contextvars-backed holder (对位 Java `ThreadLocalHolder`)."""

    def run_with_tenant(self, principal: TenantPrincipal, task: Callable[[], T]) -> T:
        token = _CURRENT.set(principal)
        try:
            return task()
        finally:
            _CURRENT.reset(token)

    def get(self) -> TenantPrincipal | None:
        return _CURRENT.get()

    def clear(self) -> None:
        _CURRENT.set(None)


class TenantContext:
    """Static facade over an injectable holder (对位 Java `TenantContext`)."""

    _holder: TenantContextHolder = ContextVarHolder()
    _lock = threading.Lock()

    @classmethod
    def init(cls, holder: TenantContextHolder) -> None:
        with cls._lock:
            cls._holder = holder

    @classmethod
    def get_holder(cls) -> TenantContextHolder:
        return cls._holder

    @classmethod
    def get(cls) -> TenantPrincipal | None:
        return cls._holder.get()

    @classmethod
    def get_tenant_id(cls) -> int | None:
        principal = cls.get()
        return principal.tenant_id if principal is not None else None

    @classmethod
    def get_tenant_name(cls) -> str | None:
        principal = cls.get()
        return principal.tenant_name if principal is not None else None

    @classmethod
    def require(cls) -> TenantPrincipal:
        principal = cls.get()
        if principal is None:
            raise TenantError(
                TenantErrorCode.TENANT_NOT_BOUND,
                "Tenant context not bound, ensure request passed through identity resolution",
            )
        return principal

    @classmethod
    def require_tenant_id(cls) -> int:
        return cls.require().tenant_id

    @classmethod
    def run_with_tenant(cls, principal: TenantPrincipal, task: Callable[[], T]) -> T:
        return cls._holder.run_with_tenant(principal, task)

    @classmethod
    def clear(cls) -> None:
        cls._holder.clear()

    @classmethod
    @contextmanager
    def bind(cls, principal: TenantPrincipal):
        """Bind for the duration of a block — usable around `await`.

        contextvars set/reset in the same task is safe across awaits, so an
        ASGI middleware can `with TenantContext.bind(p): await app(...)`。
        """
        token = _CURRENT.set(principal)
        try:
            yield principal
        finally:
            _CURRENT.reset(token)


def propagate(task: Callable[[], T]) -> Callable[[], T]:
    """Capture the current context so `task` runs with the same tenant elsewhere.

    Use when handing work to a thread pool or a new thread:
        executor.submit(propagate(job))
    对位 Java `TenantTaskDecorator` / `TenantStructuredTaskScope`。
    """
    context = contextvars.copy_context()

    def _wrapped() -> T:
        return context.run(task)

    return _wrapped


__all__ = [
    "TenantContextHolder",
    "ContextVarHolder",
    "TenantContext",
    "propagate",
]