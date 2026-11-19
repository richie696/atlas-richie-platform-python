"""多实例路由客户端（redis-py 客户端代理）。
----
把「一条命令」路由到正确的 Redis 实例，并把 key 改写成目标实例的
真实 key。**16 个 manager 一行都不用改**就能享受前缀路由 —— 这是
Java 端 ``MultiRedisTemplate`` 承诺的「业务无感」。

路由规则（与 Java 端 1:1）：

- key 形如 ``prefix@@real_key`` → 路由到前缀 ``prefix`` 对应的实例，
  真实 key 为 ``real_key``；
- key 不含 ``@@`` → 路由到**主实例**；
- 前缀**未注册** → 直接抛错（Java 端同样是抛
  ``PlatformRuntimeException``，而不是悄悄回落到主实例）。

三条 Java 端没有、Python 端补上的约束：

1. **同一条命令的所有 key 必须落在同一实例**。Java 端按第一个 key 选
   实例后，把其余 key 的前缀也剥掉就发过去 —— 跨实例的 key 会被
   静默塞进错误的实例。Python 端直接报错。
2. **未知命令默认报错**（strict 模式）。Java 端的 API 面封闭，不存在
   「未知命令」；Python 端 redis-py 是动态客户端，未登记的命令一律
   拒绝执行，避免 key 被静默写进主实例。可用
   ``RedisCommandKeySpecTable.register()`` 登记，或关掉 strict。
3. **PUBLISH / 订阅一律走主实例**（Java 端没有覆写 publish，一致）。

English
--------
Routes a command to the right Redis instance and rewrites the keys.

Routing rules are 1:1 with Java's ``MultiRedisTemplate``: a
``prefix@@real_key`` key goes to the instance registered for
``prefix``, a key without ``@@`` goes to the primary, and an
unregistered prefix raises (Java raises too, instead of silently
falling back to the primary).

Three constraints the Python side adds on top of Java:

1. Every key of one command must resolve to the **same** instance
   (Java silently drops the prefixes of the remaining keys and sends
   them to the first key's instance).
2. Unknown commands are rejected by default (strict mode) so a key can
   never land in the wrong instance unnoticed.
3. PUBLISH / subscriptions always use the primary (Java does not
   override publish either).
"""

from __future__ import annotations

import functools
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from atlas_richie.cache_core.routing import (
    CacheRouteError,
    CacheRouteKey,
    CacheRouteRegistry,
)

from ..errors import RouteError
from .command_specs import (
    DEFAULT_COMMAND_KEY_SPEC_TABLE,
    KEYLESS_COMMANDS,
    RedisCommandKeySpec,
    RedisCommandKeySpecTable,
)


def _key_container(value: Any) -> List[str]:
    """Flatten a "key container" argument into a list of key strings.

    A container is either a single key string or a sequence of them.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


class RedisRoutingClient:
    """A redis-py client proxy that routes commands by key prefix.

    Args:
        primary: The primary instance wrapper. Keys without a route
            prefix land here.
        instances: The slave instances, keyed by instance name.
        registry: The prefix -> instance-name table.
        specs: The command key table. Defaults to the built-in one.
        strict: When ``True`` (the default) a command that is not in
            the table and not in the keyless allow-list is rejected
            instead of being silently sent to the primary.
    """

    def __init__(
        self,
        primary: Any,
        instances: Mapping[str, Any],
        registry: CacheRouteRegistry,
        *,
        specs: Optional[RedisCommandKeySpecTable] = None,
        strict: bool = True,
    ) -> None:
        self._primary = primary
        self._instances: Dict[str, Any] = dict(instances)
        self._registry = registry
        self._specs = specs or DEFAULT_COMMAND_KEY_SPEC_TABLE
        self._strict = strict

    # ── Introspection ──────────────────────────────────────────────

    @property
    def primary(self) -> Any:
        """The primary instance wrapper."""
        return self._primary

    @property
    def instances(self) -> Mapping[str, Any]:
        """The slave instances, keyed by instance name."""
        return dict(self._instances)

    @property
    def registry(self) -> CacheRouteRegistry:
        """The prefix -> instance-name table."""
        return self._registry

    @property
    def specs(self) -> RedisCommandKeySpecTable:
        """The command key table."""
        return self._specs

    @property
    def strict(self) -> bool:
        """Whether unknown commands are rejected."""
        return self._strict

    @property
    def connection_pool(self) -> Any:
        """The primary's connection pool (observability)."""
        return getattr(self._primary, "_connection_pool", None)

    def instance_for_prefix(self, prefix: str) -> Any:
        """Return the instance wrapper registered for ``prefix``.

        Raises:
            RouteError: the prefix is not registered, or it points at an
                instance that is not wired up.
        """
        try:
            name = self._registry.resolve(prefix)
        except CacheRouteError as exc:
            raise RouteError(str(exc)) from exc
        try:
            return self._instances[name]
        except KeyError as exc:
            raise RouteError(
                f"route prefix '{prefix}' maps to instance '{name}', "
                f"which is not registered in the routing client"
            ) from exc

    def spec_for(self, command: str) -> Optional[RedisCommandKeySpec]:
        """The key spec of ``command``, or ``None`` when unknown."""
        return self._specs.spec_for(command)

    # ── Planning ───────────────────────────────────────────────────

    def plan(
        self,
        spec: RedisCommandKeySpec,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        *,
        pinned: Optional[Tuple[Any, Any]] = None,
    ) -> Tuple[Any, Tuple[Any, ...], Dict[str, Any]]:
        """Resolve the target instance and rewrite the keys.

        Args:
            spec: The command's key spec.
            args: Positional arguments of the command.
            kwargs: Keyword arguments of the command.
            pinned: Optional ``(name, instance)`` the command is pinned
                to (used by WATCH, where every command must run on the
                watched connection).

        Returns:
            ``(target, args, kwargs)`` — the instance to run on and
            the rewritten arguments.
        """
        args = tuple(args)
        kwargs = dict(kwargs)
        if spec.key_mode in ("none", "primary_only"):
            if pinned is not None:
                return pinned[1], args, kwargs
            return self._primary, args, kwargs

        raw_keys = self._collect_keys(spec, args, kwargs)
        target = self._resolve_target(raw_keys, pinned)
        new_args, new_kwargs = self._rewrite(spec, args, kwargs, target)
        return target, new_args, new_kwargs

    def _strip_namespace(self, key: str) -> str:
        """Remove the primary instance's namespace prefix from a key.

        The managers build their keys with ``make_key()``, which always
        prefixes the **primary** namespace. The router has to see the
        route prefix (``prefix@@real_key``) rather than the namespaced
        form, so the primary namespace is stripped before the key is
        parsed. The target instance's own namespace is applied when the
        command is rewritten.
        """
        prefix = f"{self._primary.namespace}:"
        if prefix and key.startswith(prefix):
            return key[len(prefix):]
        return key

    def _route_of(self, key: str) -> CacheRouteKey:
        """Parse a key into its route, ignoring the primary namespace."""
        return CacheRouteKey.parse(self._strip_namespace(key))

    def _collect_keys(
        self,
        spec: RedisCommandKeySpec,
        args: Tuple[Any, ...],
        kwargs: Mapping[str, Any],
    ) -> List[str]:
        """Collect every key involved in one command invocation."""
        mode = spec.key_mode
        keys: List[str] = []
        if mode == "single":
            if len(args) > spec.key_arg:
                keys.extend(_key_container(args[spec.key_arg]))
        elif mode == "varargs":
            for value in args[spec.key_arg:]:
                keys.extend(_key_container(value))
        elif mode == "list":
            if len(args) > spec.key_arg:
                keys.extend(_key_container(args[spec.key_arg]))
        elif mode == "mapping":
            if len(args) > spec.key_arg and isinstance(args[spec.key_arg], dict):
                keys.extend(
                    [k for k in args[spec.key_arg].keys() if isinstance(k, str)]
                )
        elif mode == "store":
            if len(args) > 0:
                keys.extend(_key_container(args[0]))
            if len(args) > 1:
                keys.extend(_key_container(args[1]))
        elif mode == "numkeys":
            if len(args) > spec.key_arg:
                try:
                    count = int(args[spec.key_arg])
                except (TypeError, ValueError):
                    count = 0
                for value in args[spec.key_arg + 1: spec.key_arg + 1 + count]:
                    keys.extend(_key_container(value))
        elif mode == "numkeys_list":
            if len(args) > spec.key_arg + 1:
                keys.extend(_key_container(args[spec.key_arg + 1]))
        elif mode == "keyword":
            if spec.key_kwarg and spec.key_kwarg in kwargs:
                keys.extend(_key_container(kwargs[spec.key_kwarg]))
        for position in spec.extra_key_args:
            if len(args) > position:
                keys.extend(_key_container(args[position]))
        for name in spec.extra_key_kwargs:
            if name in kwargs:
                keys.extend(_key_container(kwargs[name]))
        return keys

    def _resolve_target(
        self,
        raw_keys: Sequence[str],
        pinned: Optional[Tuple[Any, Any]],
    ) -> Any:
        """Pick the instance for one command from its keys."""
        if not raw_keys:
            if pinned is not None:
                return pinned[1]
            return self._primary

        first = self._route_of(raw_keys[0])
        if first.routed:
            target = self.instance_for_prefix(first.prefix or "")
        else:
            target = self._primary

        for key in raw_keys[1:]:
            route = self._route_of(key)
            if not route.routed:
                # A key without a prefix belongs to the instance the
                # command was routed to (Java keeps it in the same
                # template).
                continue
            other = self.instance_for_prefix(route.prefix or "")
            if other is not target:
                raise RouteError(
                    f"the keys of one command must live in the same "
                    f"redis instance, but '{raw_keys[0]}' routes to "
                    f"'{self._instance_name(target)}' and '{key}' routes "
                    f"to '{self._instance_name(other)}'"
                )
        if pinned is not None and target is not pinned[1]:
            raise RouteError(
                f"the command is pinned to the watched instance "
                f"'{self._instance_name(pinned[1])}' but its keys route "
                f"to '{self._instance_name(target)}'"
            )
        return target

    def instance_name(self, target: Any) -> str:
        """The registered name of an instance wrapper."""
        return self._instance_name(target)

    def _instance_name(self, target: Any) -> str:
        if target is self._primary:
            return "primary"
        for name, instance in self._instances.items():
            if instance is target:
                return name
        return "<unknown>"

    def _rewrite(
        self,
        spec: RedisCommandKeySpec,
        args: Tuple[Any, ...],
        kwargs: Mapping[str, Any],
        target: Any,
    ) -> Tuple[Tuple[Any, ...], Dict[str, Any]]:
        """Rewrite every key argument into the target's real key."""
        new_args = list(args)
        new_kwargs = dict(kwargs)

        def rewrite_key(key: str) -> str:
            route = self._route_of(key)
            return target.make_key(route.real_key)

        def rewrite_container(value: Any) -> Any:
            if isinstance(value, str):
                return rewrite_key(value)
            if isinstance(value, (list, tuple)):
                return type(value)(
                    rewrite_key(item) for item in value if isinstance(item, str)
                )
            return value

        mode = spec.key_mode
        if mode == "single":
            if len(new_args) > spec.key_arg:
                new_args[spec.key_arg] = rewrite_container(
                    new_args[spec.key_arg]
                )
        elif mode == "varargs":
            for index in range(spec.key_arg, len(new_args)):
                new_args[index] = rewrite_container(new_args[index])
        elif mode == "list":
            if len(new_args) > spec.key_arg:
                new_args[spec.key_arg] = rewrite_container(
                    new_args[spec.key_arg]
                )
        elif mode == "mapping":
            if len(new_args) > spec.key_arg and isinstance(
                new_args[spec.key_arg], dict
            ):
                rewritten: Dict[Any, Any] = {}
                for key, value in new_args[spec.key_arg].items():
                    if isinstance(key, str):
                        rewritten[rewrite_key(key)] = value
                    else:
                        rewritten[key] = value
                new_args[spec.key_arg] = rewritten
        elif mode == "store":
            if len(new_args) > 0:
                new_args[0] = rewrite_container(new_args[0])
            if len(new_args) > 1:
                new_args[1] = rewrite_container(new_args[1])
        elif mode == "numkeys":
            if len(new_args) > spec.key_arg:
                try:
                    count = int(new_args[spec.key_arg])
                except (TypeError, ValueError):
                    count = 0
                upper = min(spec.key_arg + 1 + count, len(new_args))
                for index in range(spec.key_arg + 1, upper):
                    new_args[index] = rewrite_container(new_args[index])
        elif mode == "numkeys_list":
            if len(new_args) > spec.key_arg + 1:
                new_args[spec.key_arg + 1] = rewrite_container(
                    new_args[spec.key_arg + 1]
                )
        elif mode == "keyword":
            if spec.key_kwarg and spec.key_kwarg in new_kwargs:
                new_kwargs[spec.key_kwarg] = rewrite_container(
                    new_kwargs[spec.key_kwarg]
                )
        for position in spec.extra_key_args:
            if len(new_args) > position:
                new_args[position] = rewrite_container(new_args[position])
        for name in spec.extra_key_kwargs:
            if name in new_kwargs:
                new_kwargs[name] = rewrite_container(new_kwargs[name])
        return tuple(new_args), new_kwargs

    # ── Public helpers ─────────────────────────────────────────────

    def plan_keys(
        self, keys: Sequence[str]
    ) -> Tuple[Any, List[str]]:
        """Resolve the target of a key list and rewrite the keys."""
        raw = list(keys)
        target = self._resolve_target(raw, None)
        rewritten = []
        for key in raw:
            route = self._route_of(key)
            rewritten.append(target.make_key(route.real_key))
        return target, rewritten

    def plan_pattern(self, pattern: str) -> Tuple[Any, str]:
        """Resolve the target of a key pattern and rewrite it."""
        route = self._route_of(pattern)
        if route.routed:
            target = self.instance_for_prefix(route.prefix or "")
        else:
            target = self._primary
        return target, target.make_key(route.real_key)

    # ── Dispatch ───────────────────────────────────────────────────

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        spec = self._specs.spec_for(name)
        if spec is not None:
            return functools.partial(self._dispatch, name, spec)
        if name in KEYLESS_COMMANDS:
            return getattr(self._primary.raw_client(), name)
        if self._strict:
            raise RouteError(
                f"redis command '{name}' is not registered in the "
                f"routing command table; register a "
                f"RedisCommandKeySpec for it (or disable strict "
                f"routing) — sending it to the primary instance would "
                f"silently place keys in the wrong instance"
            )
        return getattr(self._primary.raw_client(), name)

    def _dispatch(
        self,
        command: str,
        spec: RedisCommandKeySpec,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        target, new_args, new_kwargs = self.plan(spec, args, kwargs)
        return getattr(target.raw_client(), command)(*new_args, **new_kwargs)

    # ── Client-level helpers ───────────────────────────────────────

    def pipeline(
        self, transaction: bool = True, shard_size: Optional[int] = None
    ) -> Any:
        """A routing pipeline (see ``RedisRoutingPipeline``)."""
        from .route_pipeline import RedisRoutingPipeline

        return RedisRoutingPipeline(
            self, transaction=transaction, shard_size=shard_size
        )

    def pubsub(self, *args: Any, **kwargs: Any) -> Any:
        """Pub/sub always lives on the primary instance."""
        return self._primary.raw_client().pubsub(*args, **kwargs)

    def scan_iter(
        self,
        match: Optional[str] = None,
        count: Optional[int] = None,
        _type: Optional[str] = None,
        **kwargs: Any,
    ) -> Iterator[Any]:
        """SCAN over the instance the pattern routes to."""
        if match is None:
            yield from self._primary.raw_client().scan_iter(
                count=count, _type=_type, **kwargs
            )
            return
        target, pattern = self.plan_pattern(match)
        yield from target.raw_client().scan_iter(
            match=pattern, count=count, _type=_type, **kwargs
        )

    def script_load(self, script: Any, *args: Any, **kwargs: Any) -> Any:
        """Load a Lua script on **every** instance.

        ``EVALSHA`` is routed by key, so a script that was only
        loaded on the primary would fail with ``NOSCRIPT`` on a routed
        instance. Loading everywhere keeps the SHA cache valid on all
        instances. The returned SHA is the primary's (identical on every
        instance — it is the SHA1 of the script body).
        """
        sha = None
        for target in self._all_targets():
            result = target.raw_client().script_load(script, *args, **kwargs)
            if sha is None:
                sha = result
        return sha

    def _all_targets(self) -> List[Any]:
        targets = [self._primary]
        for instance in self._instances.values():
            if instance is not self._primary:
                targets.append(instance)
        return targets

    def close(self) -> None:
        """Close every instance's client."""
        for target in self._all_targets():
            target.close()

    def __repr__(self) -> str:
        return (
            f"RedisRoutingClient(instances={list(self._instances)}, "
            f"prefixes={list(self._registry.prefixes())})"
        )


__all__ = ["RedisRoutingClient"]
