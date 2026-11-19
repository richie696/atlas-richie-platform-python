"""前缀路由 key 的解析与装饰。
----
多实例路由的 key 约定（对位 Java 端
``cn.richie696.component.cache.redis.bean.MultiRedisTemplate``)：

    {prefix}@@{real_key}      ->  路由到名为 ``prefix`` 的实例，真实 key 为 ``real_key``
    {real_key}                ->  路由到主实例，真实 key 原样

前缀只取 **第一个** ``@@`` 之前的部分；``@@`` 之后的内容全部算作
真实 key。这与 ``cache_core.commons.CacheKeyUtils.get_real_key`` 的
语义完全一致（同为「首个 ``@@`` 之后的后缀」），因此本模块可以直接复用
它，也可以被单独使用。

English
--------
Key parsing / decoration for prefix routing.

The key convention (mirroring Java's ``MultiRedisTemplate``) is:

    {prefix}@@{real_key}   -> route to the instance named ``prefix``, real key ``real_key``
    {real_key}             -> route to the primary instance, real key unchanged

The prefix is everything **before the first** ``@@``; everything after
it is the real key. This is exactly the semantics of
``cache_core.commons.CacheKeyUtils.get_real_key`` ("the suffix after
the first ``@@``"), so the two stay consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .route_error import CacheRouteError

#: 分隔符：前缀与真实 key 之间使用 ``@@``。
ROUTE_SEPARATOR = "@@"


@dataclass(frozen=True)
class CacheRouteKey:
    """A parsed routing key.

    Attributes:
        prefix: The instance prefix, or ``None`` when the key is not
            routed (it belongs to the primary instance).
        real_key: The key as it must be stored in the target instance
            (namespace prefix excluded).
    """

    prefix: Optional[str]
    real_key: str

    @property
    def routed(self) -> bool:
        """``True`` when this key carries an explicit route prefix."""
        return self.prefix is not None

    @classmethod
    def parse(cls, key: str) -> "CacheRouteKey":
        """Parse a raw key into `(prefix, real_key)`.

        Raises:
            CacheRouteError: the key is not a string, or the route
                prefix is empty (e.g. ``"@@key"``).
        """
        if not isinstance(key, str):
            raise CacheRouteError(
                f"cache key must be a string, got {type(key).__name__}"
            )
        if ROUTE_SEPARATOR not in key:
            return cls(None, key)
        prefix, _, real_key = key.partition(ROUTE_SEPARATOR)
        if not prefix:
            raise CacheRouteError(
                f"cache key {key!r} has an empty route prefix; "
                f"the prefix before {ROUTE_SEPARATOR!r} must not be empty"
            )
        return cls(prefix, real_key)

    def decorate(self, transform: Callable[[str], str]) -> str:
        """Apply ``transform`` to the **real** key, keeping the prefix.

        Derived keys (a lock key, a meta key, a marker key ...) must
        live in the same instance as the key they were derived from.
        Decorating the *decorated* key would bury the route prefix
        behind the decorator and the router would no longer recognise
        it, so the transform is applied to the real key only and the
        prefix is re-attached.

        English
        --------
        Apply ``transform`` to the real key and re-attach the route
        prefix.
        """
        real_key = transform(self.real_key)
        if self.prefix is None:
            return real_key
        return f"{self.prefix}{ROUTE_SEPARATOR}{real_key}"


__all__ = ["ROUTE_SEPARATOR", "CacheRouteKey"]
