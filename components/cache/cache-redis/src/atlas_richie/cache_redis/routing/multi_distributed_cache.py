"""多实例分布式缓存（主实例 + 前缀路由的从实例）。
----
对位 Java 端 ``MultiRedisTemplate``：把多个 Redis 实例包成一个
「看起来只有一个」的缓存入口，按 key 前缀把命令路由到对应实例。

与单实例 ``RedisDistributedCache`` 的一点差别：

- ``decorate_key()`` 是**路由感知**的：派生 key（锁 key、meta key、
  标记 key）会继承原 key 的路由前缀，因此一定和原 key 落在同一个
  实例。

``make_key()`` 的语义两模式一致（都加主实例的 namespace）；路由层
在解析路由前缀时**剥掉**这层 namespace，转发时再套上目标实例自己的
namespace —— 因此同一条业务 key 在不同实例上有各自独立的 namespace，
而 pub/sub 频道名这类不走路由的名字仍然带 namespace。

English
--------
The multi-instance counterpart of ``RedisDistributedCache``, mirroring
Java's ``MultiRedisTemplate``.

One difference from the single-instance wrapper:

- ``decorate_key()`` is route-aware: a derived key (lock key, meta
  key, marker key) inherits the route prefix of the original key and
  therefore always lands in the same instance.

``make_key()`` keeps the same semantics in both modes (the primary
namespace is added); the router strips that namespace before parsing
the route prefix and applies the target instance's own namespace when
forwarding.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional

from atlas_richie.cache_core.routing import CacheRouteKey, CacheRouteRegistry

from ..errors import CacheError
from ..redis_distributed_cache import RedisDistributedCache
from .command_specs import RedisCommandKeySpecTable
from .route_client import RedisRoutingClient


class MultiRedisDistributedCache(RedisDistributedCache):
    """A cache transport that routes commands by key prefix.

    Args:
        primary: The primary instance wrapper.
        slaves: The additional instances, keyed by instance name.
        registry: The prefix -> instance-name table. Defaults to the
            identity mapping (the instance name is the prefix).
        strict: Whether unknown commands are rejected (see
            ``RedisRoutingClient``).
        specs: The command key table.
    """

    def __init__(
        self,
        primary: RedisDistributedCache,
        slaves: Mapping[str, RedisDistributedCache],
        *,
        registry: Optional[CacheRouteRegistry] = None,
        strict: bool = True,
        specs: Optional[RedisCommandKeySpecTable] = None,
    ) -> None:
        super().__init__(
            primary.raw_client(),
            namespace=primary.namespace,
            connection_string=primary.connection_string,
            connection_pool=getattr(primary, "_connection_pool", None),
        )
        self._primary = primary
        self._slaves: Dict[str, RedisDistributedCache] = dict(slaves)
        self._registry = (
            registry
            if registry is not None
            else CacheRouteRegistry(
                {name: name for name in self._slaves}
            )
        )
        self._routing_client = RedisRoutingClient(
            primary, self._slaves, self._registry, specs=specs, strict=strict
        )
        # The inherited convenience methods (get / set / ...) call
        # self._client.<cmd>(self.make_key(key)) - pointing
        # self._client at the routing client is what makes them route.
        self._client = self._routing_client

    # ── Introspection ──────────────────────────────────────────────

    @property
    def primary(self) -> RedisDistributedCache:
        """The primary instance wrapper."""
        return self._primary

    @property
    def slaves(self) -> Dict[str, RedisDistributedCache]:
        """The routed instances, keyed by instance name."""
        return dict(self._slaves)

    @property
    def registry(self) -> CacheRouteRegistry:
        """The prefix -> instance-name table."""
        return self._registry

    @property
    def routing_client(self) -> RedisRoutingClient:
        """The routing client proxy."""
        return self._routing_client

    # ── Key helpers ────────────────────────────────────────────────

    def decorate_key(self, key: str, transform: Callable[[str], str]) -> str:
        """Derive a key from ``key``, keeping its route prefix.

        The transform is applied to the **real** key; the route prefix
        is re-attached and the result is namespaced like any other key.
        """
        self._validate(key)
        route = CacheRouteKey.parse(key)
        return self.make_key(route.decorate(transform))

    def raw_client(self) -> Any:
        """The routing client (not the raw redis-py client)."""
        return self._routing_client

    def keys(self, pattern: str = "*") -> list[str]:
        """Return the keys matching ``pattern`` on its target instance.

        The pattern is routed by its prefix; the returned keys have
        the **target instance's** namespace stripped.
        """
        target, rewritten = self._routing_client.plan_pattern(pattern)
        prefix = f"{target.namespace}:"
        out: list[str] = []
        try:
            for raw in target.raw_client().scan_iter(
                match=rewritten, count=200
            ):
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                if raw.startswith(prefix):
                    out.append(raw[len(prefix):])
        except Exception as exc:
            raise CacheError(
                f"Redis SCAN failed for {pattern!r}: {exc}"
            ) from exc
        return out

    def __repr__(self) -> str:
        return (
            f"MultiRedisDistributedCache(namespace={self.namespace!r}, "
            f"instances={list(self._slaves)})"
        )


__all__ = ["MultiRedisDistributedCache"]
