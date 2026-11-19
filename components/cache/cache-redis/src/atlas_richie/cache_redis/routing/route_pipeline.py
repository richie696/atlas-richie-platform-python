"""多实例路由 Pipeline。
----
redis-py 的 ``Pipeline`` 绑定在**一个连接**上，而多实例路由下一条
pipeline 里的命令可能落在不同实例上。本模块按目标实例把命令分组，
分组执行后再按原始顺序把结果拼回去。

两种模式：

1. **普通 pipeline**（没有 WATCH）：命令按目标实例分组，每组用目标
   实例自己的 ``pipeline()` 执行，结果按原始下标还原。
2. **WATCH pipeline**：一旦调用 ``watch()``，整个 pipeline 就**锁定**
   在被 WATCH 的那个实例上，并 1:1 委托给该实例的真实 pipeline ——
   WATCH 与后续的 MULTI/EXEC 必须落在同一条连接上，只有委托才能保证
   这个语义（``RedisStructManager`` 的乐观锁就是这条路径）。

English
--------
redis-py pipelines are bound to a single connection, but with prefix
routing the commands of one pipeline may target different instances.
This module groups the commands by target instance, runs each group on
that instance, and splices the results back into the original order.

Without WATCH the commands are grouped. With WATCH the whole pipeline
is pinned to the watched instance and delegated 1:1 to that instance's
real pipeline, because WATCH and the following MULTI/EXEC must share
one connection.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..errors import RouteError


class RedisRoutingPipeline:
    """A pipeline that routes each command to its instance.

    Args:
        client: The ``RedisRoutingClient`` that owns this pipeline.
        transaction: Whether the commands run inside MULTI/EXEC (the
            redis-py default).
        shard_size: Forwarded to redis-py (cluster pipelines only).
    """

    def __init__(
        self,
        client: Any,
        *,
        transaction: bool = True,
        shard_size: Optional[int] = None,
    ) -> None:
        self._client = client
        self._transaction = transaction
        self._shard_size = shard_size
        self._stack: List[Tuple[str, Tuple[Any, ...], Dict[str, Any]]] = []
        self._explicit_transaction = False
        self._real_pipe: Any = None
        self._pinned: Optional[Tuple[Any, Any]] = None

    # ── Introspection ──────────────────────────────────────────────

    @property
    def pinned_instance(self) -> Optional[Any]:
        """The instance this pipeline is pinned to (after WATCH)."""
        return self._pinned[1] if self._pinned is not None else None

    @property
    def command_count(self) -> int:
        """How many commands are buffered."""
        return len(self._stack)

    # ── Command recording ──────────────────────────────────────────

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _record(*args: Any, **kwargs: Any) -> Any:
            if self._real_pipe is not None:
                spec = self._client.spec_for(name)
                if spec is None:
                    return getattr(self._real_pipe, name)(*args, **kwargs)
                target, new_args, new_kwargs = self._client.plan(
                    spec, args, kwargs, pinned=self._pinned
                )
                return getattr(self._real_pipe, name)(
                    *new_args, **new_kwargs
                )
            self._stack.append((name, tuple(args), dict(kwargs)))
            return self

        return _record

    # ── Transaction control ─────────────────────────────────────────

    def watch(self, *names: str) -> None:
        """WATCH the given keys and pin the pipeline to their instance.

        After this call every command of the pipeline runs on the
        watched instance (and therefore on the watched connection),
        which is what redis-py requires for the WATCH/MULTI/EXEC
        optimistic-lock pattern.
        """
        if self._explicit_transaction:
            raise RouteError("cannot issue a watch after a multi")
        if self._pinned is not None:
            raise RouteError("already watching")
        target, rewritten = self._client.plan_keys(list(names))
        self._pinned = (self._client.instance_name(target), target)
        self._real_pipe = target.raw_client().pipeline(
            transaction=self._transaction, shard_size=self._shard_size
        )
        self._real_pipe.watch(*rewritten)
        return None

    def unwatch(self) -> Any:
        """Unwatch and release the pin."""
        if self._real_pipe is not None:
            result = self._real_pipe.unwatch()
            self._real_pipe = None
            self._pinned = None
            return result
        self._pinned = None
        return None

    def multi(self) -> "RedisRoutingPipeline":
        """Start a MULTI block."""
        if self._explicit_transaction:
            raise RouteError("cannot issue nested multi() calls")
        self._explicit_transaction = True
        if self._real_pipe is not None:
            self._real_pipe.multi()
        return self

    def reset(self) -> None:
        """Discard every buffered command and release the pin."""
        self._stack.clear()
        self._explicit_transaction = False
        if self._real_pipe is not None:
            self._real_pipe.reset()
            self._real_pipe = None
        self._pinned = None
        return None

    # ── Execution ──────────────────────────────────────────────────

    def execute(self) -> List[Any]:
        """Run the buffered commands and return the results in order."""
        if self._real_pipe is not None:
            results = self._real_pipe.execute()
            self._real_pipe = None
            self._pinned = None
            self._stack.clear()
            self._explicit_transaction = False
            return results
        if not self._stack:
            return []

        plans: List[Tuple[Any, str, Tuple[Any, ...], Dict[str, Any]]] = []
        groups: Dict[int, List[int]] = {}
        order: List[Any] = []
        for index, (name, args, kwargs) in enumerate(self._stack):
            spec = self._client.spec_for(name)
            if spec is None:
                if self._client.strict:
                    raise RouteError(
                        f"redis command '{name}' is not registered in "
                        f"the routing command table"
                    )
                target = self._client.primary
                new_args: Tuple[Any, ...] = tuple(args)
                new_kwargs: Dict[str, Any] = dict(kwargs)
            else:
                target, new_args, new_kwargs = self._client.plan(
                    spec, args, kwargs
                )
            plans.append((target, name, new_args, new_kwargs))
            if target not in order:
                order.append(target)
            groups.setdefault(id(target), []).append(index)

        if self._explicit_transaction and len(groups) > 1:
            raise RouteError(
                "a MULTI block cannot span several redis instances; "
                "the buffered commands target "
                f"{len(groups)} different instances"
            )

        results: List[Any] = [None] * len(self._stack)
        for target in order:
            indices = groups[id(target)]
            pipe = target.raw_client().pipeline(
                transaction=self._transaction, shard_size=self._shard_size
            )
            for index in indices:
                _, name, new_args, new_kwargs = plans[index]
                getattr(pipe, name)(*new_args, **new_kwargs)
            group_results = pipe.execute()
            for index, value in zip(indices, group_results):
                results[index] = value

        self._stack.clear()
        self._explicit_transaction = False
        return results

    # ── Context manager ────────────────────────────────────────────

    def __enter__(self) -> "RedisRoutingPipeline":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.reset()
        return None

    def __repr__(self) -> str:
        return (
            f"RedisRoutingPipeline(commands={len(self._stack)}, "
            f"transaction={self._transaction}, "
            f"pinned={self.pinned_instance is not None})"
        )


__all__ = ["RedisRoutingPipeline"]
