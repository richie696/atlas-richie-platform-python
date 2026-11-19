"""多实例前缀路由的失败类型。
----
路由契约层的唯一异常类型。保持与 ``cache_core.registry.cache_registry``
里的 ``StateError`` 同一约定（继承 ``RuntimeError``，不引入任何第三方
依赖），避免 core 层反向依赖 ``atlas-richie-contracts``。

English
--------
The only exception type of the routing contract layer. Follows the same
convention as ``StateError`` in ``cache_core.registry.cache_registry``
(inherits ``RuntimeError``, no third-party dependency), so the core
layer never has to depend on ``atlas-richie-contracts``.
"""

from __future__ import annotations


class CacheRouteError(RuntimeError):
    """Raised when a cache key cannot be routed to a Redis instance.

    Typical causes:

    - the key carries a ``prefix@@real_key`` route prefix that is not
      registered in the route registry;
    - one command touches keys that resolve to **different** instances
      (a cross-instance operation is not expressible in Redis);
    - the route prefix is empty or otherwise malformed.
    """


__all__ = ["CacheRouteError"]
