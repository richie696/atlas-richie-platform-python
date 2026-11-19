"""Redis 命令的 key 位置规格表。
----
多实例路由必须知道「一条命令的哪些参数是 key」，才能：

1. 用**第一个** key 决定这条命令落在哪个实例；
2. 转发前把 key 改写成「目标实例的真实 key」（剥掉路由前缀 + 套目标
   实例自己的 namespace）。

Java 端不需要这张表 —— ``MultiRedisTemplate`` 是继承
``RedisTemplate`` 的，Spring Data Redis 的 API 面是封闭的，Java 只能
**逐个方法覆写**（``delete`` / ``hasKey`` / ``expire`` /
``keys`` / ``rename`` / ``boundXOps`` …）。Python 侧 managers
直接调用 redis-py 的动态客户端，没有封闭的 API 面，所以改用
**显式命令表**：命令 → key 位置。

命令表的 key 位置模式（``key_mode``）：

| 模式 | 含义 | 典型命令 |
|------|------|----------|
| ``none`` | 没有 key | PING / INFO |
| ``primary_only`` | 有 key 形态的参数，但一律走主实例 | PUBLISH（频道） |
| ``single`` | 第 ``key_arg`` 个位置是单个 key | GET / SET / HGET |
| ``varargs`` | 从第 ``key_arg`` 个位置起全是 key | DEL / EXISTS / SDIFF |
| ``list`` | 第 ``key_arg`` 个位置装 key（字符串或列表） | MGET / ZINTER |
| ``mapping`` | 第 ``key_arg`` 个位置是 dict，其 key 是 Redis key | MSET / XREAD |
| ``store`` | 第 0 位是目标 key，第 1 位是来源 key 列表 | ZUNIONSTORE |
| ``numkeys`` | 第 ``key_arg`` 个位置是 key 个数，后面紧跟 key | EVAL / EVALSHA |
| ``numkeys_list`` | 第 ``key_arg`` 个位置是 key 个数，下一个位置是 key 列表 | SINTERCARD |
| ``keyword`` | ``kwargs[key_kwarg]`` 是 key | SCAN_ITER(match=) |

**形态说明**：``list`` / ``varargs`` 模式下的容器既可以是一个 key
字符串，也可以是一个 key 列表 —— 两种写法都能识别与改写，保持原来的
容器形状不变。

English
--------
Key-position specs for Redis commands.

Routing needs to know *which arguments of a command are keys* so that
(a) the first key can pick the target instance and (b) the keys can be
rewritten (route prefix stripped, target namespace applied) before the
command is forwarded.

Java does not need such a table: ``MultiRedisTemplate`` extends
``RedisTemplate``, whose API surface is closed, so Java overrides the
methods one by one. The Python managers call the dynamic redis-py
client, so the equivalent is an explicit command table.

Key modes: ``none``, ``primary_only``, ``single``, ``varargs``,
``list``, ``mapping``, ``store``, ``numkeys``,
``numkeys_list``, ``keyword``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

#: 不含任何 key 的命令 —— 一律走主实例，参数原样透传。
KEYLESS_COMMANDS = frozenset(
    {
        "acl",
        "acl_getuser",
        "acl_list",
        "acl_setuser",
        "acl_whoami",
        "bgrewriteaof",
        "bgsave",
        "client_getname",
        "client_id",
        "client_info",
        "client_kill",
        "client_list",
        "client_setname",
        "client_unpause",
        "cluster_info",
        "cluster_myinfo",
        "cluster_nodes",
        "cluster_replicate",
        "cluster_reset",
        "cluster_shards",
        "cluster_slots",
        "command",
        "command_count",
        "command_docs",
        "command_getkeys",
        "command_info",
        "config_get",
        "config_resetstat",
        "config_set",
        "dbsize",
        "debug",
        "echo",
        "failover",
        "flushall",
        "flushdb",
        "function_dump",
        "function_flush",
        "function_list",
        "function_stats",
        "hello",
        "info",
        "lastsave",
        "lolwut",
        "memory_doctor",
        "memory_stats",
        "monitor",
        "ping",
        "psync",
        "quit",
        "randomkey",
        "replicaof",
        "replconf",
        "reset",
        "role",
        "save",
        "select",
        "shutdown",
        "slaveof",
        "slowlog_get",
        "slowlog_len",
        "slowlog_reset",
        "swapdb",
        "sync",
        "time",
        "wait",
    }
)


@dataclass(frozen=True)
class RedisCommandKeySpec:
    """Where the keys of one Redis command live.

    Attributes:
        command: The redis-py method name (lower case, e.g. ``"get"``).
        key_mode: One of the modes documented in the module docstring.
        key_arg: Index of the positional argument that holds the key(s).
        extra_key_args: Extra positional arguments that also hold keys
            and must therefore live in the **same** instance (e.g. the
            destination of ``RENAME`` / ``COPY`` / ``LMOVE``).
        extra_key_kwargs: Same, for keyword arguments (e.g. the
            ``store=`` destination of ``SORT``).
        key_kwarg: Name of the keyword argument holding a single key
            (used by ``keyword`` mode).
    """

    command: str
    key_mode: str = "none"
    key_arg: int = 0
    extra_key_args: Tuple[int, ...] = ()
    extra_key_kwargs: Tuple[str, ...] = ()
    key_kwarg: Optional[str] = None


def _s(command: str, key_arg: int = 0) -> RedisCommandKeySpec:
    """Single-key command."""
    return RedisCommandKeySpec(
        command=command, key_mode="single", key_arg=key_arg
    )


def _v(command: str, key_arg: int = 0) -> RedisCommandKeySpec:
    """Varargs command (every argument from ``key_arg`` on is a key)."""
    return RedisCommandKeySpec(
        command=command, key_mode="varargs", key_arg=key_arg
    )


def _n(command: str) -> RedisCommandKeySpec:
    """Keyless command (always runs on the primary)."""
    return RedisCommandKeySpec(command=command, key_mode="none")


def _l(command: str, key_arg: int = 0) -> RedisCommandKeySpec:
    """Command whose ``key_arg`` position holds one or more keys."""
    return RedisCommandKeySpec(
        command=command, key_mode="list", key_arg=key_arg
    )


def _pair(command: str) -> RedisCommandKeySpec:
    """Two-key command (source + destination, same instance)."""
    return RedisCommandKeySpec(
        command=command, key_mode="single", extra_key_args=(1,)
    )


def _store(command: str) -> RedisCommandKeySpec:
    """Store command: ``dest`` + a list of source keys."""
    return RedisCommandKeySpec(command=command, key_mode="store")


#: The built-in command table.
DEFAULT_COMMAND_KEY_SPECS: Tuple[RedisCommandKeySpec, ...] = (
    # ── string ────────────────────────────────────────────────────
    _s("get"),
    _s("set"),
    _s("setnx"),
    _s("setex"),
    _s("psetex"),
    _s("getset"),
    _s("getdel"),
    _s("getex"),
    _s("getrange"),
    _s("setrange"),
    _s("append"),
    _s("strlen"),
    _s("incr"),
    _s("incrby"),
    _s("incrbyfloat"),
    _s("decr"),
    _s("decrby"),
    _pair("lcs"),
    _l("mget"),
    RedisCommandKeySpec(command="mset", key_mode="mapping"),
    RedisCommandKeySpec(command="msetnx", key_mode="mapping"),
    # ── keyspace ──────────────────────────────────────────────────
    _v("delete"),
    _v("del"),
    _v("unlink"),
    _v("exists"),
    _v("touch"),
    _v("watch"),
    _s("expire"),
    _s("pexpire"),
    _s("expireat"),
    _s("pexpireat"),
    _s("ttl"),
    _s("pttl"),
    _s("persist"),
    _s("type"),
    _s("dump"),
    _s("restore"),
    _pair("copy"),
    _s("move"),
    _pair("rename"),
    _pair("renamenx"),
    RedisCommandKeySpec(
        command="sort", key_mode="single", extra_key_kwargs=("store",)
    ),
    _s("object", 1),
    _s("memory_usage"),
    _s("setbit"),
    _s("getbit"),
    _s("bitcount"),
    _s("bitpos"),
    _s("bitfield"),
    _v("bitop", 1),
    _s("keys"),
    RedisCommandKeySpec(
        command="scan", key_mode="keyword", key_kwarg="match"
    ),
    RedisCommandKeySpec(
        command="scan_iter", key_mode="keyword", key_kwarg="match"
    ),
    # ── hash ──────────────────────────────────────────────────────
    _s("hget"),
    _s("hset"),
    _s("hsetnx"),
    _s("hmset"),
    _s("hdel"),
    _s("hlen"),
    _s("hexists"),
    _s("hkeys"),
    _s("hvals"),
    _s("hgetall"),
    _s("hstrlen"),
    _s("hincrby"),
    _s("hincrbyfloat"),
    _s("hrandfield"),
    _s("hscan"),
    _s("hmget"),
    _s("hpexpire"),
    _s("hpexpireat"),
    _s("hexpire"),
    _s("hexpireat"),
    _s("hpersist"),
    # ── list ──────────────────────────────────────────────────────
    _s("lpush"),
    _s("rpush"),
    _s("lpop"),
    _s("rpop"),
    _s("llen"),
    _s("lrange"),
    _s("ltrim"),
    _s("lset"),
    _s("lindex"),
    _s("linsert"),
    _s("lrem"),
    _s("lpos"),
    _l("blpop"),
    _l("brpop"),
    _pair("brpoplpush"),
    _pair("lmove"),
    _pair("rpoplpush"),
    # ── set ───────────────────────────────────────────────────────
    _s("sadd"),
    _s("srem"),
    _s("smembers"),
    _s("scard"),
    _s("sismember"),
    _s("smismember"),
    _s("spop"),
    _s("srandmember"),
    _s("sscan"),
    _v("sinter"),
    _v("sunion"),
    _v("sdiff"),
    _store("sinterstore"),
    _store("sunionstore"),
    _store("sdiffstore"),
    _pair("smove"),
    RedisCommandKeySpec(
        command="sintercard", key_mode="numkeys_list", key_arg=0
    ),
    RedisCommandKeySpec(
        command="sdiffcard", key_mode="numkeys_list", key_arg=0
    ),
    # ── zset ──────────────────────────────────────────────────────
    _s("zadd"),
    _s("zcard"),
    _s("zcount"),
    _s("zincrby"),
    _s("zrange"),
    _s("zrevrange"),
    _s("zrangebyscore"),
    _s("zrevrangebyscore"),
    _s("zrangebylex"),
    _s("zrevrangebylex"),
    _s("zrank"),
    _s("zrevrank"),
    _s("zrem"),
    _s("zremrangebyrank"),
    _s("zremrangebyscore"),
    _s("zremrangebylex"),
    _s("zscore"),
    _s("zmscore"),
    _s("zpopmin"),
    _s("zpopmax"),
    _s("zrandmember"),
    _s("zscan"),
    _l("zunion"),
    _l("zinter"),
    _l("zdiff"),
    _store("zunionstore"),
    _store("zinterstore"),
    _store("zdiffstore"),
    _pair("zrangestore"),
    RedisCommandKeySpec(
        command="zintercard", key_mode="numkeys_list", key_arg=0
    ),
    # ── geo ───────────────────────────────────────────────────────
    _s("geoadd"),
    _s("geopos"),
    _pair("geodist"),
    _s("geohash"),
    _s("geosearch"),
    _s("georadius"),
    _s("georadiusbymember"),
    _s("georadius_ro"),
    _s("georadiusbymember_ro"),
    # ── hyperloglog ───────────────────────────────────────────────
    _s("pfadd"),
    _v("pfcount"),
    _v("pfmerge"),
    _s("pfdebug"),
    # ── stream ────────────────────────────────────────────────────
    _s("xadd"),
    _s("xlen"),
    _s("xrange"),
    _s("xrevrange"),
    _s("xdel"),
    _s("xtrim"),
    _s("xgroup"),
    RedisCommandKeySpec(command="xread", key_mode="mapping"),
    RedisCommandKeySpec(
        command="xreadgroup", key_mode="mapping", key_arg=2
    ),
    _s("xack"),
    _s("xautoclaim"),
    _s("xclaim"),
    _s("xpending"),
    _s("xrange_ro"),
    # ── scripting ─────────────────────────────────────────────────
    RedisCommandKeySpec(command="eval", key_mode="numkeys", key_arg=1),
    RedisCommandKeySpec(command="evalsha", key_mode="numkeys", key_arg=1),
    _n("script_load"),
    _n("script_exists"),
    _n("script_flush"),
    _n("unwatch"),
    # ── pub/sub (channels always stay on the primary) ─────────────
    RedisCommandKeySpec(command="publish", key_mode="primary_only"),
    RedisCommandKeySpec(command="spublish", key_mode="primary_only"),
    RedisCommandKeySpec(command="subscribe", key_mode="primary_only"),
    RedisCommandKeySpec(command="psubscribe", key_mode="primary_only"),
    RedisCommandKeySpec(command="unsubscribe", key_mode="primary_only"),
    RedisCommandKeySpec(command="punsubscribe", key_mode="primary_only"),
    RedisCommandKeySpec(command="pubsub", key_mode="primary_only"),
)


class RedisCommandKeySpecTable:
    """A lookup table of ``RedisCommandKeySpec``.

    The table is the single source of truth for "which arguments of a
    command are keys". It is mutable so that application code can
    register commands the built-in table does not know (e.g. a
    module command or a newer Redis release).
    """

    def __init__(self, specs: Iterable[RedisCommandKeySpec] = ()) -> None:
        self._specs: Dict[str, RedisCommandKeySpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: RedisCommandKeySpec) -> None:
        """Add (or replace) a spec."""
        if not spec.command:
            raise ValueError("command must be a non-empty string")
        self._specs[spec.command.lower()] = spec

    def spec_for(self, command: str) -> Optional[RedisCommandKeySpec]:
        """Return the spec for ``command``, or ``None`` when unknown."""
        if not isinstance(command, str):
            return None
        return self._specs.get(command.lower())

    def commands(self) -> Tuple[str, ...]:
        """All registered command names (sorted)."""
        return tuple(sorted(self._specs))

    def __contains__(self, command: object) -> bool:
        if not isinstance(command, str):
            return False
        return command.lower() in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    def copy(self) -> "RedisCommandKeySpecTable":
        """A shallow copy (the specs themselves are immutable)."""
        return RedisCommandKeySpecTable(self._specs.values())

    def __repr__(self) -> str:
        return f"RedisCommandKeySpecTable({len(self._specs)} commands)"


#: The shared built-in table.
DEFAULT_COMMAND_KEY_SPEC_TABLE = RedisCommandKeySpecTable(
    DEFAULT_COMMAND_KEY_SPECS
)


__all__ = [
    "DEFAULT_COMMAND_KEY_SPECS",
    "DEFAULT_COMMAND_KEY_SPEC_TABLE",
    "KEYLESS_COMMANDS",
    "RedisCommandKeySpec",
    "RedisCommandKeySpecTable",
]
