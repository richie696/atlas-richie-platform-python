"""前缀路由注册表（prefix -> instance name）。
----
对位 Java 端 ``MultiRedisTemplate.slaveTemplateMap`` 的**契约部分**：
一张「前缀 -> 实例名」的映射表。

Java 端的映射是「前缀 -> RedisTemplate 实例」，且只在配置期装配
（``RedisBaseAutoConfiguration.createRedisTemplate`` 递归建好模板后
一次性 ``setSlaveTemplateMap``，运行时增删必须重启）。Python 端把
「表」和「连接」拆开：

- 本类（core，零第三方依赖）只管 **前缀 -> 实例名** 的映射；
- ``cache_redis`` 侧的路由客户端把 **实例名 -> 实际连接** 绑定上。

因此本表可以在运行时增删（线程安全），而 Java 端不行 —— 这是一处
刻意的差异。

English
--------
The contract half of Java's ``MultiRedisTemplate.slaveTemplateMap``:
a ``prefix -> instance name`` mapping.

Java binds the map directly to RedisTemplate instances and populates it
once at configuration time (runtime changes need a restart). The Python
side splits the table from the connections: this class (core, zero
third-party dependency) only owns the prefix -> instance-name mapping,
while the ``cache_redis`` routing client binds instance names to real
connections. The table is therefore mutable at runtime (thread-safe) -
a deliberate difference.
"""

from __future__ import annotations

import threading
from typing import Iterator, Mapping, Optional

from .route_error import CacheRouteError


class CacheRouteRegistry:
    """Thread-safe ``prefix -> instance name`` registry.

    Args:
        routes: Optional initial mapping. Keys are route prefixes,
            values are instance names.
    """

    def __init__(self, routes: Optional[Mapping[str, str]] = None) -> None:
        self._routes: dict[str, str] = {}
        self._lock = threading.RLock()
        if routes:
            for prefix, instance in routes.items():
                self.register(prefix, instance)

    # ── Mutation ───────────────────────────────────────────────────

    def register(self, prefix: str, instance: str) -> None:
        """Bind ``prefix`` to ``instance``.

        Raises:
            CacheRouteError: the prefix or the instance name is empty.
        """
        if not prefix or not isinstance(prefix, str):
            raise CacheRouteError("route prefix must be a non-empty string")
        if not instance or not isinstance(instance, str):
            raise CacheRouteError("instance name must be a non-empty string")
        with self._lock:
            self._routes[prefix] = instance

    def unregister(self, prefix: str) -> None:
        """Remove ``prefix`` from the table (no-op when absent)."""
        with self._lock:
            self._routes.pop(prefix, None)

    # ── Lookup ─────────────────────────────────────────────────────

    def resolve(self, prefix: str) -> str:
        """Return the instance name bound to ``prefix``.

        Raises:
            CacheRouteError: the prefix is not registered. Mirrors
                Java, where an unknown prefix raises
                ``PlatformRuntimeException("The key '%s' is not found in
                slave redis template")`` instead of silently falling
                back to the primary instance.
        """
        with self._lock:
            instance = self._routes.get(prefix)
        if instance is None:
            raise CacheRouteError(
                f"The key prefix '{prefix}' is not found in the "
                f"redis instance registry"
            )
        return instance

    def instance_for_key(self, key: str) -> Optional[str]:
        """Return the instance name for ``key`, or ``None`` for primary.

        The prefix is the part before the first ``@@``. A key without
        ``@@`` belongs to the primary instance.
        """
        from .route_key import CacheRouteKey

        route = CacheRouteKey.parse(key)
        if not route.routed:
            return None
        return self.resolve(route.prefix or "")

    # ── Introspection ──────────────────────────────────────────────

    def prefixes(self) -> tuple[str, ...]:
        """All registered route prefixes (sorted)."""
        with self._lock:
            return tuple(sorted(self._routes))

    def instances(self) -> tuple[str, ...]:
        """All referenced instance names (sorted, de-duplicated)."""
        with self._lock:
            return tuple(sorted(set(self._routes.values())))

    def as_mapping(self) -> dict[str, str]:
        """A copy of the current mapping."""
        with self._lock:
            return dict(self._routes)

    def __contains__(self, prefix: object) -> bool:
        if not isinstance(prefix, str):
            return False
        with self._lock:
            return prefix in self._routes

    def __len__(self) -> int:
        with self._lock:
            return len(self._routes)

    def __iter__(self) -> Iterator[str]:
        return iter(self.prefixes())

    def __repr__(self) -> str:
        return f"CacheRouteRegistry({self.as_mapping()!r})"


__all__ = ["CacheRouteRegistry"]
