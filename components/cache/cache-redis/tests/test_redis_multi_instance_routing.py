"""多 Redis 实例前缀路由测试。
----
覆盖五块：

1. **core 路由契约**（``CacheRouteKey`` / ``CacheRouteRegistry`` /
   ``CacheRouteError``）—— key 解析、路由表、装饰语义。
2. **命令 key 规格表**（``RedisCommandKeySpecTable``）—— 各命令的 key
   位置；外加一条**静态扫描**守卫：仓内 manager 用到的每一条 redis-py
   命令都必须在表里登记，否则路由会漏掉它。
3. **路由客户端**（``RedisRoutingClient``）—— 路由、改写、跨实例拒绝、
   未知命令拒绝、脚本预加载。
4. **路由 pipeline**（``RedisRoutingPipeline``）—— 按实例分组、结果
   还原、WATCH 锁定。
5. **集成**（``MultiRedisDistributedCache`` / registrar / 派生 key）——
   manager 零改动即享受路由，派生 key 与原 key 同实例。

English
--------
Unit tests for the multi-instance prefix routing: the core routing
contract, the command key table (including a static scan that every
redis-py command used by the managers is registered), the routing
client, the routing pipeline, and the end-to-end wiring.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from atlas_richie.cache_core.operations.bounded_list_capacity_limits import (
    BoundedListCapacityLimits,
)
from atlas_richie.cache_core.routing import (
    CacheRouteError,
    CacheRouteKey,
    CacheRouteRegistry,
)
from atlas_richie.cache_redis import (
    MultiRedisDistributedCache,
    RedisCacheProperties,
    RedisCommandKeySpec,
    RedisCommandKeySpecTable,
    RedisDistributedCache,
    RedisInstanceSettings,
    RedisProviderRegistrar,
    RouteError,
)
from atlas_richie.cache_core.config.bloom_filter_config import (
    BloomFilterConfig,
)
from atlas_richie.cache_redis.managers.redis_bloom_filter import (
    RedisSharedBloomFilter,
)
from atlas_richie.cache_redis.managers.redis_collection_manager import (
    RedisCollectionManager,
)
from atlas_richie.cache_redis.managers.redis_string_manager import (
    _make_stampede_lock_key,
)
from atlas_richie.cache_redis.redis_cache_infrastructure import (
    RedisCacheInfrastructure,
)
from atlas_richie.cache_redis.routing import (
    DEFAULT_COMMAND_KEY_SPEC_TABLE,
    KEYLESS_COMMANDS,
)

pytestmark = pytest.mark.unit


# ── Test doubles ─────────────────────────────────────────────────


class RecordingClient:
    """A redis-py client double that records every call."""

    def __init__(self, name: str = "primary") -> None:
        self.name = name
        self.calls: List[Tuple[str, Tuple[Any, ...], Dict[str, Any]]] = []

    def record(
        self, command: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]
    ) -> None:
        self.calls.append((command, args, kwargs))

    def commands(self) -> List[str]:
        return [call[0] for call in self.calls]

    def last(self) -> Tuple[str, Tuple[Any, ...], Dict[str, Any]]:
        return self.calls[-1]

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _record(*args: Any, **kwargs: Any) -> Any:
            self.record(name, args, kwargs)
            return "OK"

        return _record

    def pipeline(
        self, transaction: bool = True, shard_size: Optional[int] = None
    ) -> "RecordingPipeline":
        return RecordingPipeline(self, transaction=transaction)

    def pubsub(self, *args: Any, **kwargs: Any) -> Tuple[str, str]:
        self.record("pubsub", args, kwargs)
        return ("pubsub", self.name)

    def close(self) -> None:
        self.record("close", (), {})


#: Canned results for the pipeline double, keyed by command name.
_PIPELINE_RESULTS: Dict[str, Any] = {
    "hgetall": {"bit_size": "128", "hash_count": "7"},
    "hsetnx": 1,
    "type": "none",
}


def _default_result(command: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Any:
    return f"{command}:{args[0] if args else ''}"


class RecordingPipeline:
    """A pipeline double that records the queued commands."""

    def __init__(
        self, client: RecordingClient, transaction: bool = True
    ) -> None:
        self._client = client
        self._commands: List[Tuple[str, Tuple[Any, ...], Dict[str, Any]]] = []
        self.transaction = transaction

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _record(*args: Any, **kwargs: Any) -> "RecordingPipeline":
            self._commands.append((name, args, kwargs))
            return self

        return _record

    def execute(self) -> List[Any]:
        results = []
        for name, args, kwargs in self._commands:
            self._client.record(name, args, kwargs)
            if name in _PIPELINE_RESULTS:
                results.append(_PIPELINE_RESULTS[name])
            else:
                results.append(_default_result(name, args, kwargs))
        self._commands.clear()
        return results

    def watch(self, *names: Any) -> None:
        self._client.record("watch", names, {})

    def multi(self) -> None:
        self._client.record("multi", (), {})

    def reset(self) -> None:
        self._commands.clear()


@pytest.fixture
def instances() -> Tuple[
    MultiRedisDistributedCache, RecordingClient, RecordingClient
]:
    """A primary instance plus one routed instance named `order`."""
    primary_client = RecordingClient("primary")
    slave_client = RecordingClient("slave")
    primary = RedisDistributedCache(primary_client, namespace="ns-main")
    slave = RedisDistributedCache(slave_client, namespace="ns-slave")
    registry = CacheRouteRegistry({"order": "order", "user": "order"})
    multi = MultiRedisDistributedCache(
        primary, {"order": slave}, registry=registry
    )
    return multi, primary_client, slave_client


@pytest.fixture
def two_instances() -> Tuple[
    MultiRedisDistributedCache,
    RecordingClient,
    RecordingClient,
    RecordingClient,
]:
    """Two routed instances so cross-instance operations can be tested."""
    primary_client = RecordingClient("primary")
    order_client = RecordingClient("order")
    user_client = RecordingClient("user")
    primary = RedisDistributedCache(primary_client, namespace="ns-main")
    order = RedisDistributedCache(order_client, namespace="ns-order")
    user = RedisDistributedCache(user_client, namespace="ns-user")
    registry = CacheRouteRegistry({"order": "order", "user": "user"})
    multi = MultiRedisDistributedCache(
        primary, {"order": order, "user": user}, registry=registry
    )
    return multi, primary_client, order_client, user_client


# ══════════════════════════════════════════════════════════════════
# 1. Core routing contract
# ══════════════════════════════════════════════════════════════════


class TestCacheRouteKey:
    def test_key_without_separator_is_not_routed(self) -> None:
        route = CacheRouteKey.parse("user:1")
        assert route.prefix is None
        assert route.real_key == "user:1"
        assert route.routed is False

    def test_key_with_separator_is_routed(self) -> None:
        route = CacheRouteKey.parse("order@@user:1")
        assert route.prefix == "order"
        assert route.real_key == "user:1"
        assert route.routed is True

    def test_only_the_first_separator_splits(self) -> None:
        route = CacheRouteKey.parse("a@@b@@c")
        assert route.prefix == "a"
        assert route.real_key == "b@@c"

    def test_empty_prefix_is_rejected(self) -> None:
        with pytest.raises(CacheRouteError):
            CacheRouteKey.parse("@@leading")

    def test_non_string_key_is_rejected(self) -> None:
        with pytest.raises(CacheRouteError):
            CacheRouteKey.parse(42)  # type: ignore[arg-type]

    def test_decorate_keeps_the_prefix(self) -> None:
        route = CacheRouteKey.parse("order@@user:1")
        assert route.decorate(lambda r: f"lock:{r}") == "order@@lock:user:1"

    def test_decorate_without_prefix_has_no_prefix(self) -> None:
        route = CacheRouteKey.parse("user:1")
        assert route.decorate(lambda r: f"lock:{r}") == "lock:user:1"

    def test_decorate_applies_to_the_real_key_only(self) -> None:
        route = CacheRouteKey.parse("order@@user:1")
        assert route.decorate(lambda r: r + ":meta") == "order@@user:1:meta"

    def test_matches_cache_key_utils(self) -> None:
        from atlas_richie.cache_core.commons import CacheKeyUtils

        for raw in ("user:1", "order@@user:1", "a@@b@@c"):
            assert CacheRouteKey.parse(raw).real_key == (
                CacheKeyUtils.get_real_key(raw)
            )


class TestCacheRouteRegistry:
    def test_register_and_resolve(self) -> None:
        registry = CacheRouteRegistry()
        registry.register("order", "order-redis")
        assert registry.resolve("order") == "order-redis"

    def test_resolve_unknown_prefix_raises(self) -> None:
        registry = CacheRouteRegistry()
        with pytest.raises(CacheRouteError):
            registry.resolve("nope")

    def test_initial_mapping(self) -> None:
        registry = CacheRouteRegistry({"a": "x", "b": "y"})
        assert registry.resolve("a") == "x"
        assert registry.resolve("b") == "y"

    def test_unregister(self) -> None:
        registry = CacheRouteRegistry({"a": "x"})
        registry.unregister("a")
        assert "a" not in registry

    def test_unregister_missing_is_a_noop(self) -> None:
        registry = CacheRouteRegistry()
        registry.unregister("ghost")

    def test_empty_prefix_is_rejected(self) -> None:
        registry = CacheRouteRegistry()
        with pytest.raises(CacheRouteError):
            registry.register("", "x")

    def test_empty_instance_is_rejected(self) -> None:
        registry = CacheRouteRegistry()
        with pytest.raises(CacheRouteError):
            registry.register("a", "")

    def test_prefixes_and_instances(self) -> None:
        registry = CacheRouteRegistry({"b": "z", "a": "z"})
        assert registry.prefixes() == ("a", "b")
        assert registry.instances() == ("z",)

    def test_len_iter_and_contains(self) -> None:
        registry = CacheRouteRegistry({"a": "x"})
        assert len(registry) == 1
        assert list(registry) == ["a"]
        assert "a" in registry
        assert "b" not in registry

    def test_as_mapping_is_a_copy(self) -> None:
        registry = CacheRouteRegistry({"a": "x"})
        mapping = registry.as_mapping()
        mapping["a"] = "mutated"
        assert registry.resolve("a") == "x"

    def test_instance_for_key(self) -> None:
        registry = CacheRouteRegistry({"order": "order-redis"})
        assert registry.instance_for_key("order@@x") == "order-redis"

    def test_instance_for_unrouted_key_is_none(self) -> None:
        registry = CacheRouteRegistry({"order": "order-redis"})
        assert registry.instance_for_key("plain") is None

    def test_route_error_is_a_runtime_error(self) -> None:
        assert issubclass(CacheRouteError, RuntimeError)


# ══════════════════════════════════════════════════════════════════
# 2. Command key spec table
# ══════════════════════════════════════════════════════════════════


class TestCommandKeySpecTable:
    def test_table_has_the_expected_size(self) -> None:
        assert len(DEFAULT_COMMAND_KEY_SPEC_TABLE) >= 120

    @pytest.mark.parametrize(
        "command,mode",
        [
            ("get", "single"),
            ("set", "single"),
            ("delete", "varargs"),
            ("exists", "varargs"),
            ("mget", "list"),
            ("mset", "mapping"),
            ("zunionstore", "store"),
            ("eval", "numkeys"),
            ("evalsha", "numkeys"),
            ("sintercard", "numkeys_list"),
            ("scan_iter", "keyword"),
            ("publish", "primary_only"),
        ],
    )
    def test_key_modes(self, command: str, mode: str) -> None:
        spec = DEFAULT_COMMAND_KEY_SPEC_TABLE.spec_for(command)
        assert spec is not None
        assert spec.key_mode == mode

    def test_rename_owns_two_keys(self) -> None:
        spec = DEFAULT_COMMAND_KEY_SPEC_TABLE.spec_for("rename")
        assert spec is not None
        assert spec.extra_key_args == (1,)

    def test_sort_owns_the_store_destination(self) -> None:
        spec = DEFAULT_COMMAND_KEY_SPEC_TABLE.spec_for("sort")
        assert spec is not None
        assert spec.extra_key_kwargs == ("store",)

    def test_eval_counts_the_keys_from_index_two(self) -> None:
        spec = DEFAULT_COMMAND_KEY_SPEC_TABLE.spec_for("eval")
        assert spec is not None
        assert spec.key_arg == 1

    def test_keyless_commands_cover_ping_and_info(self) -> None:
        assert "ping" in KEYLESS_COMMANDS
        assert "info" in KEYLESS_COMMANDS

    def test_register_a_custom_command(self) -> None:
        table = DEFAULT_COMMAND_KEY_SPEC_TABLE.copy()
        table.register(
            RedisCommandKeySpec(command="mycmd", key_mode="single")
        )
        assert table.spec_for("mycmd").key_mode == "single"
        # the shared table is untouched
        assert DEFAULT_COMMAND_KEY_SPEC_TABLE.spec_for("mycmd") is None

    def test_copy_is_independent(self) -> None:
        table = DEFAULT_COMMAND_KEY_SPEC_TABLE.copy()
        table.register(RedisCommandKeySpec(command="other"))
        assert "other" not in DEFAULT_COMMAND_KEY_SPEC_TABLE

    def test_unknown_command_has_no_spec(self) -> None:
        assert DEFAULT_COMMAND_KEY_SPEC_TABLE.spec_for("nope") is None

    def test_every_redis_command_used_by_the_managers_is_registered(
        self,
    ) -> None:
        """Static guard: a command the managers use but the table does not
        know would silently fall through to the primary instance."""
        import redis as redis_lib

        redis_methods = {
            name for name in dir(redis_lib.Redis) if not name.startswith("_")
        }
        # Client-level helpers that never reach the server as a command.
        client_level = {
            "close",
            "digest",
            "from_url",
            "pipeline",
            "pubsub",
        }
        package_dir = Path(
            os.path.dirname(
                os.path.abspath(
                    __import__(
                        "atlas_richie.cache_redis", fromlist=["__file__"]
                    ).__file__
                )
            )
        )
        used: Dict[str, str] = {}
        for source in package_dir.rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in redis_methods
                ):
                    used.setdefault(node.func.attr, source.name)
        missing = {
            command: source
            for command, source in used.items()
            if command not in DEFAULT_COMMAND_KEY_SPEC_TABLE
            and command not in KEYLESS_COMMANDS
            and command not in client_level
        }
        assert not missing, (
            "redis commands used by the backend but missing from the "
            f"routing command table: {missing}"
        )


# ══════════════════════════════════════════════════════════════════
# 3. Routing client
# ══════════════════════════════════════════════════════════════════


class TestRoutingClient:
    def test_key_without_prefix_stays_on_the_primary(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().get("plain")
        assert primary_client.last()[1][0] == "ns-main:plain"
        assert slave_client.calls == []

    def test_key_with_prefix_is_routed(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().get("order@@user:1")
        assert slave_client.last()[1][0] == "ns-slave:user:1"
        assert primary_client.calls == []

    def test_route_prefix_is_stripped(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().get("order@@user:1")
        assert "order" not in slave_client.last()[1][0]

    def test_a_second_prefix_can_share_an_instance(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().get("user@@user:1")
        assert slave_client.last()[1][0] == "ns-slave:user:1"

    def test_unregistered_prefix_is_rejected(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        with pytest.raises(RouteError):
            multi.raw_client().get("ghost@@user:1")
        assert slave_client.calls == []

    def test_keys_of_one_command_must_share_the_instance(
        self, two_instances: Any
    ) -> None:
        multi, primary_client, order_client, user_client = two_instances
        with pytest.raises(RouteError):
            multi.raw_client().mget(["order@@a", "user@@b"])

    def test_a_routed_key_cannot_join_the_primary(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        with pytest.raises(RouteError):
            multi.raw_client().mget(["plain", "order@@a"])

    def test_an_unprefixed_key_joins_the_routed_instance(
        self, instances: Any
    ) -> None:
        """Java parity: the first key picks the template and the other
        keys follow it (their own prefix is stripped)."""
        multi, primary_client, slave_client = instances
        multi.raw_client().mget(["order@@a", "plain"])
        assert slave_client.last()[1][0] == ["ns-slave:a", "ns-slave:plain"]

    def test_mget_rewrites_every_key(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().mget(["order@@a", "order@@b"])
        assert slave_client.last()[1][0] == ["ns-slave:a", "ns-slave:b"]

    def test_mset_rewrites_every_mapping_key(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().mset({"order@@a": "1", "order@@b": "2"})
        assert slave_client.last()[1][0] == {
            "ns-slave:a": "1",
            "ns-slave:b": "2",
        }

    def test_delete_rewrites_every_key(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().delete("order@@a", "order@@b")
        assert slave_client.last()[1] == ("ns-slave:a", "ns-slave:b")

    def test_exists_rewrites_every_key(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().exists("order@@a", "order@@b")
        assert slave_client.last()[1] == ("ns-slave:a", "ns-slave:b")

    def test_eval_rewrites_the_keys_only(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().eval("return 1", 2, "order@@a", "order@@b", "arg")
        assert slave_client.last()[1] == (
            "return 1",
            2,
            "ns-slave:a",
            "ns-slave:b",
            "arg",
        )

    def test_evalsha_rewrites_the_keys_only(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().evalsha("sha", 1, "order@@a", "arg")
        assert slave_client.last()[1] == ("sha", 1, "ns-slave:a", "arg")

    def test_rename_rewrites_both_keys(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().rename("order@@a", "order@@b")
        assert slave_client.last()[1] == ("ns-slave:a", "ns-slave:b")

    def test_rename_destination_without_prefix_stays(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().rename("order@@a", "plain-b")
        assert slave_client.last()[1] == ("ns-slave:a", "ns-slave:plain-b")

    def test_rename_to_another_instance_is_rejected(
        self, two_instances: Any
    ) -> None:
        multi, primary_client, order_client, user_client = two_instances
        with pytest.raises(RouteError):
            multi.raw_client().rename("order@@a", "user@@b")

    def test_copy_rewrites_both_keys(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().copy("order@@a", "order@@b")
        assert slave_client.last()[1] == ("ns-slave:a", "ns-slave:b")

    def test_publish_stays_on_the_primary(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().publish("order@@channel", "payload")
        assert primary_client.last()[1] == ("order@@channel", "payload")
        assert slave_client.calls == []

    def test_the_channel_keeps_the_namespace(
        self, instances: Any
    ) -> None:
        """Pub/sub channels are not routed, so they must stay namespaced."""
        multi, primary_client, slave_client = instances
        multi.raw_client().publish(
            multi.make_key("order@@channel"), "payload"
        )
        assert primary_client.last()[1][0] == "ns-main:order@@channel"

    def test_pubsub_stays_on_the_primary(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        assert multi.raw_client().pubsub() == ("pubsub", "primary")
        assert slave_client.calls == []

    def test_scan_iter_routes_the_pattern(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        list(multi.raw_client().scan_iter(match="order@@user:*"))
        assert slave_client.calls[0][2]["match"] == "ns-slave:user:*"

    def test_unknown_command_is_rejected_in_strict_mode(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        with pytest.raises(RouteError):
            multi.raw_client().some_unknown_command("k")

    def test_unknown_command_falls_back_when_not_strict(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        loose = MultiRedisDistributedCache(
            multi.primary, multi.slaves, registry=multi.registry, strict=False
        )
        loose.raw_client().some_unknown_command("k")
        assert primary_client.last()[0] == "some_unknown_command"

    def test_script_load_targets_every_instance(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().script_load("return 1")
        assert "script_load" in primary_client.commands()
        assert "script_load" in slave_client.commands()

    def test_close_closes_every_instance(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        multi.raw_client().close()
        assert "close" in primary_client.commands()
        assert "close" in slave_client.commands()

    def test_instance_name(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        client = multi.raw_client()
        assert client.instance_name(multi.primary) == "primary"
        assert client.instance_name(multi.slaves["order"]) == "order"

    def test_registry_prefix_pointing_at_a_missing_instance(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        broken = CacheRouteRegistry({"ghost": "not-wired"})
        other = MultiRedisDistributedCache(
            multi.primary, multi.slaves, registry=broken
        )
        with pytest.raises(RouteError):
            other.raw_client().get("ghost@@x")


# ══════════════════════════════════════════════════════════════════
# 4. Routing pipeline
# ══════════════════════════════════════════════════════════════════


class TestRoutingPipeline:
    def test_commands_are_grouped_by_instance(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        pipe = multi.raw_client().pipeline(transaction=False)
        pipe.set("order@@a", "1")
        pipe.set("plain", "2")
        pipe.execute()
        assert slave_client.commands() == ["set"]
        assert primary_client.commands() == ["set"]

    def test_results_keep_the_original_order(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        pipe = multi.raw_client().pipeline(transaction=False)
        pipe.set("order@@a", "1")
        pipe.set("plain", "2")
        pipe.get("order@@a")
        results = pipe.execute()
        assert results == ["set:ns-slave:a", "set:ns-main:plain", "get:ns-slave:a"]

    def test_empty_pipeline_returns_no_results(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        assert multi.raw_client().pipeline().execute() == []

    def test_watch_pins_the_instance(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        pipe = multi.raw_client().pipeline()
        pipe.watch("order@@a")
        assert pipe.pinned_instance is multi.slaves["order"]
        pipe.get("order@@a")
        pipe.execute()
        assert "watch" in slave_client.commands()
        assert "watch" not in primary_client.commands()

    def test_watch_after_multi_is_rejected(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        pipe = multi.raw_client().pipeline()
        pipe.multi()
        with pytest.raises(RouteError):
            pipe.watch("order@@a")

    def test_a_multi_block_cannot_span_instances(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        pipe = multi.raw_client().pipeline()
        pipe.multi()
        pipe.set("order@@a", "1")
        pipe.set("plain", "2")
        with pytest.raises(RouteError):
            pipe.execute()

    def test_pipeline_is_a_context_manager(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        with multi.raw_client().pipeline(transaction=False) as pipe:
            pipe.set("order@@a", "1")
            pipe.execute()
        assert slave_client.commands() == ["set"]

    def test_unknown_command_in_a_pipeline_is_rejected(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        pipe = multi.raw_client().pipeline(transaction=False)
        pipe.some_unknown_command("k")
        with pytest.raises(RouteError):
            pipe.execute()


# ══════════════════════════════════════════════════════════════════
# 5. MultiRedisDistributedCache
# ══════════════════════════════════════════════════════════════════


class TestMultiRedisDistributedCache:
    def test_make_key_keeps_the_primary_namespace(
        self, instances: Any
    ) -> None:
        """Both modes namespace the key the same way — the router strips
        the namespace before it parses the route prefix."""
        multi, primary_client, slave_client = instances
        assert multi.make_key("order@@user:1") == "ns-main:order@@user:1"
        assert multi.make_key("user:1") == "ns-main:user:1"

    def test_make_key_validates(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        with pytest.raises(Exception):
            multi.make_key("")

    def test_decorate_key_keeps_the_route_prefix(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        assert (
            multi.decorate_key("order@@user:1", lambda r: f"lock:{r}")
            == "ns-main:order@@lock:user:1"
        )

    def test_decorate_key_without_prefix(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        assert (
            multi.decorate_key("user:1", lambda r: f"lock:{r}")
            == "ns-main:lock:user:1"
        )

    def test_namespace_is_the_primary_one(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        assert multi.namespace == "ns-main"

    def test_keys_routes_and_strips_the_target_namespace(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances

        def _scan(**kwargs: Any) -> Any:
            slave_client.record("scan_iter", (), kwargs)
            return iter(["ns-slave:user:1", "ns-slave:user:2"])

        class _Client:
            def scan_iter(self, **kwargs: Any) -> Any:
                return _scan(**kwargs)

        multi.slaves["order"]._client = _Client()
        assert multi.keys("order@@user:*") == ["user:1", "user:2"]

    def test_default_registry_maps_the_instance_name(
        self, instances: Any
    ) -> None:
        primary = RedisDistributedCache(
            RecordingClient("primary"), namespace="ns-main"
        )
        slave = RedisDistributedCache(
            RecordingClient("slave"), namespace="ns-slave"
        )
        multi = MultiRedisDistributedCache(primary, {"order": slave})
        assert multi.registry.resolve("order") == "order"

    def test_repr_mentions_the_instances(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        assert "order" in repr(multi)


# ══════════════════════════════════════════════════════════════════
# 6. Properties + registrar
# ══════════════════════════════════════════════════════════════════


class TestPropertiesAndRegistrar:
    def test_slaves_are_parsed(self) -> None:
        props = RedisCacheProperties(
            url="redis://127.0.0.1:6379/0",
            slaves={
                "order": {"url": "redis://127.0.0.1:6380/0"},
            },
        )
        assert isinstance(props.slaves["order"], RedisInstanceSettings)
        assert props.slaves["order"].url == "redis://127.0.0.1:6380/0"

    def test_slaves_from_an_env_var(self, monkeypatch: Any) -> None:
        monkeypatch.setenv(
            "ATLAS_RICHIE_CACHE_REDIS_URL", "redis://127.0.0.1:6379/0"
        )
        monkeypatch.setenv(
            "ATLAS_RICHIE_CACHE_REDIS_SLAVES",
            '{"order": {"url": "redis://127.0.0.1:6380/0"}}',
        )
        props = RedisCacheProperties()
        assert props.slaves["order"].url == "redis://127.0.0.1:6380/0"

    def test_slave_url_is_validated(self) -> None:
        with pytest.raises(Exception):
            RedisInstanceSettings(url="http://nope")

    def test_from_properties_builds_one_client_per_instance(
        self, monkeypatch: Any
    ) -> None:
        import redis as redis_lib

        pools: List[Any] = []

        def _from_url(url: str, **kwargs: Any) -> Any:
            pool = type("Pool", (), {"url": url, "kwargs": kwargs})()
            pools.append(pool)
            return pool

        monkeypatch.setattr(
            redis_lib.connection.BlockingConnectionPool,
            "from_url",
            staticmethod(_from_url),
        )
        monkeypatch.setattr(
            redis_lib, "Redis", lambda connection_pool=None: connection_pool
        )

        props = RedisCacheProperties(
            url="redis://127.0.0.1:6379/0",
            slaves={
                "order": {"url": "redis://127.0.0.1:6380/0"},
                "user": {"url": "redis://127.0.0.1:6381/0"},
            },
        )
        registrar = RedisProviderRegistrar.from_properties(props)
        assert len(pools) == 3
        assert set(registrar.backend.slaves) == {"order", "user"}

    def test_single_instance_registrar_is_unchanged(self) -> None:
        registrar = RedisProviderRegistrar(
            RecordingClient("primary"), namespace="ns-main"
        )
        assert not isinstance(registrar.backend, MultiRedisDistributedCache)

    def test_registrar_routes_the_managers(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        registrar = RedisProviderRegistrar(
            primary_client,
            namespace="ns-main",
            slaves={"order": multi.slaves["order"]},
            route_registry=multi.registry,
        )
        registrar.value_ops().set("order@@user:1", "v")
        assert slave_client.last()[1][0] == "ns-slave:user:1"
        assert primary_client.calls == []

    def test_registrar_keeps_unrouted_keys_on_the_primary(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        registrar = RedisProviderRegistrar(
            primary_client,
            namespace="ns-main",
            slaves={"order": multi.slaves["order"]},
            route_registry=multi.registry,
        )
        registrar.value_ops().set("plain", "v")
        assert primary_client.last()[1][0] == "ns-main:plain"
        assert slave_client.calls == []


# ══════════════════════════════════════════════════════════════════
# 7. Derived keys stay on the routed instance
# ══════════════════════════════════════════════════════════════════


class TestDerivedKeys:
    def test_stampede_lock_key_keeps_the_route(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        assert (
            _make_stampede_lock_key(multi, "order@@user:1")
            == "ns-main:order@@__stampede_lock__:user:1"
        )

    def test_negative_set_marker_keeps_the_route(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        infra = RedisCacheInfrastructure(multi, None)
        manager = RedisCollectionManager(multi, infra)
        assert (
            manager._negative_set_marker_key("order@@user:1")
            == "ns-main:order@@__negative_set__:user:1"
        )

    def test_bounded_list_meta_key_keeps_the_route(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        assert multi.decorate_key(
            "order@@q", BoundedListCapacityLimits.meta_key
        ) == "ns-main:order@@q:meta"

    def test_bloom_filter_keys_keep_the_route(self, instances: Any) -> None:
        multi, primary_client, slave_client = instances
        config = BloomFilterConfig(
            key="order@@bf",
            expected_insertions=100,
            false_probability=0.01,
        )
        bloom = RedisSharedBloomFilter(multi, config)
        assert bloom._bit_key == "ns-main:order@@bloom:bf"
        assert bloom._meta_key == "ns-main:order@@bloom:bf:meta"
        # the meta read happens on the routed instance
        assert slave_client.calls
        assert all(
            str(call[1][0]).startswith("ns-slave:")
            for call in slave_client.calls
        )

    def test_bloom_filter_meta_read_lands_on_the_slave(
        self, instances: Any
    ) -> None:
        multi, primary_client, slave_client = instances
        config = BloomFilterConfig(
            key="order@@bf",
            expected_insertions=100,
            false_probability=0.01,
        )
        RedisSharedBloomFilter(multi, config)
        hgetall_calls = [
            call for call in slave_client.calls if call[0] == "hgetall"
        ]
        assert hgetall_calls
        assert hgetall_calls[0][1][0] == "ns-slave:bloom:bf:meta"
        assert primary_client.calls == []
