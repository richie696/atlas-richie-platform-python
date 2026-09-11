"""有界队列 / 栈 Redis 管理器共用逻辑。
----
有界队列 / 栈的共享 Lua 脚本与辅助函数。

镜像 ``cn.richie696.component.cache.redis.manage.BoundedListRedisSupport`` +
``BoundedListRedisScripts``。两半部分：

- ``BoundedListRedisScripts`` —— Lua 脚本，在 Redis 服务端原子执行，
  保证元数据 key 与数据列表在并发生产者下保持一致。
- ``BoundedListRedisSupport`` —— Python 端辅助函数：基于 ``SETNX`` 的
  元数据 key 创建、类型兼容性检查、脚本 SHA 缓存。

原子性原因：没有 Lua 脚本的话，生产者可能在元数据 key 设置**之前**就
push 到数据列表；另一个生产者可能读到空的元数据 key 并错误地拒绝 push。
或者：grow 操作可能在裁剪数据列表**之前**就更新元数据 key，导致列表
过长。Lua 脚本将读-改-写包装为单个 Redis 端事务。

English
--------
Shared Lua scripts + helper functions for the bounded queue / stack.

Mirrors `cn.richie696.component.cache.redis.manage.BoundedListRedisSupport`
+ `BoundedListRedisScripts`. Two halves:

- `BoundedListRedisScripts` — Lua scripts executed atomically on the
  Redis server so the meta key and the data list stay consistent
  under concurrent producers.
- `BoundedListRedisSupport` — Python-side helpers for `SETNX`-based
  meta-key creation, type-compatibility checks, and script SHA
  caching.

Atomicity rationale: without the Lua scripts, a producer could push
to the data list BEFORE the meta key is set; another producer could
read an empty meta key and reject the push incorrectly. Or: a grow
operation could update the meta key BEFORE trimming the data list,
leaving the list too long. The Lua scripts wrap the read-modify-
write in a single Redis-side transaction.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

# ── Lua scripts ──────────────────────────────────────────────────────

# Atomically: read maxLen from meta, push, and trim. Returns the new
# length after the operation, or -1 if maxLen is not initialised.
BOUNDED_QUEUE_OFFER_SCRIPT = """
local meta = KEYS[1]
local list_key = KEYS[2]
local raw_max = redis.call('GET', meta)
if not raw_max then return -1 end
local max_len = tonumber(raw_max)
redis.call('RPUSH', list_key, ARGV[1])
redis.call('LTRIM', list_key, -max_len, -1)
return redis.call('LLEN', list_key)
"""

# Atomically: read maxLen, check LLEN, and push. Returns 1 on push,
# 0 if full and rejected.
BOUNDED_STACK_PUSH_SCRIPT = """
local meta = KEYS[1]
local list_key = KEYS[2]
local raw_max = redis.call('GET', meta)
if not raw_max then return -1 end
local max_len = tonumber(raw_max)
if redis.call('LLEN', list_key) >= max_len then return 0 end
redis.call('RPUSH', list_key, ARGV[1])
return 1
"""

# Doubles the meta value, capped at `ceiling`. Returns the new maxLen
# (or the current maxLen if already at the cap), -1 if meta is
# missing, -2 if meta is malformed.
BOUNDED_GROW_MAX_LEN_SCRIPT = """
local meta = KEYS[1]
local ceiling = tonumber(ARGV[1])
local raw = redis.call('GET', meta)
if not raw then return -1 end
local current = tonumber(raw)
if current == nil or current < 1 or current > ceiling then return -2 end
if current >= ceiling then return current end
local new_max = current * 2
if new_max > ceiling then new_max = ceiling end
redis.call('SET', meta, tostring(new_max))
return new_max
"""

# Trim a list to the meta's current maxLen (used after grow on a
# queue).
BOUNDED_TRIM_LIST_TO_META_SCRIPT = """
local list_key = KEYS[1]
local meta = KEYS[2]
local raw = redis.call('GET', meta)
if not raw then return -1 end
local max_len = tonumber(raw)
if max_len == nil then return -2 end
return redis.call('LTRIM', list_key, -max_len, -1)
"""

# Atomic destroy: delete both meta and data keys, return the number
# of keys removed (0 if neither existed, 1 if one existed, 2 if both).
BOUNDED_DESTROY_SCRIPT = """
local meta = KEYS[1]
local list_key = KEYS[2]
local n = 0
if redis.call('DEL', meta) == 1 then n = n + 1 end
if redis.call('DEL', list_key) == 1 then n = n + 1 end
return n
"""


# ── Python-side helper ───────────────────────────────────────────────


class BoundedListRedisSupport:
    """有界队列 / 栈的共享 Python 端辅助函数。
    ----
    提供：

    - ``set_meta_if_absent`` —— 通过 ``SETNX`` 设置元数据 key 与 maxLen。
    - ``assert_list_key_compatible`` —— 拒绝在不同的 Redis 数据类型上
      创建队列/栈。
    - ``evalsha_cached`` —— 加载或复用脚本 SHA，使脚本体只发送一次。

    English
    --------
    Shared Python-side helpers for the bounded queue / stack.

    Provides:
    - `set_meta_if_absent` — SETNX the meta key with the maxLen.
    - `assert_list_key_compatible` — refuse to create a queue/stack
      on top of a different Redis data type.
    - `evalsha_cached` — load-or-reuse the script SHA so we send the
      body once.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._shas: dict[str, str] = {}
        self._lock = threading.Lock()

    def evalsha_cached(
        self,
        script: str,
        num_keys: int,
        *keys_and_args: Any,
    ) -> Any:
        """Run a Lua script by SHA; load the script lazily and reuse.

        Mirrors `scriptLoad` + `evalsha` usage in the rest of the
        backend. On `NOSCRIPT` errors the SHA is dropped and the
        script is reloaded.
        """
        with self._lock:
            sha = self._shas.get(script)
        if sha is None:
            sha = self._client.script_load(script)
            with self._lock:
                self._shas[script] = sha
        try:
            return self._client.evalsha(sha, num_keys, *keys_and_args)
        except Exception:
            # NOSCRIPT (or anything else that invalidates the SHA) —
            # reload and retry once.
            with self._lock:
                self._shas.pop(script, None)
            sha = self._client.script_load(script)
            with self._lock:
                self._shas[script] = sha
            return self._client.evalsha(sha, num_keys, *keys_and_args)

    def set_meta_if_absent(self, meta_key: str, max_len: int) -> bool:
        """Initialise the meta key with `max_len` only if it does not
        already exist. Returns `True` on creation, `False` on no-op.
        """
        encoded = str(int(max_len)).encode("utf-8")
        return bool(self._client.set(meta_key, encoded, nx=True))

    def assert_list_key_compatible(
        self, list_key: str, kind: str
    ) -> None:
        """Refuse to create a queue/stack on top of a non-List key."""
        t = self._client.type(list_key)
        if t is None:
            return
        if isinstance(t, bytes):
            t = t.decode("utf-8", errors="replace")
        if t.lower() == "none":
            return
        if t.lower() != "list":
            from ..errors import StateError as CacheStateError

            raise CacheStateError(
                f"Key '{list_key}' already exists as Redis {t}, "
                f"cannot create {kind}"
            )

    def read_meta_max_len(self, meta_key: str) -> Optional[int]:
        raw = self._client.get(meta_key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None


__all__ = [
    "BOUNDED_DESTROY_SCRIPT",
    "BOUNDED_GROW_MAX_LEN_SCRIPT",
    "BOUNDED_QUEUE_OFFER_SCRIPT",
    "BOUNDED_STACK_PUSH_SCRIPT",
    "BOUNDED_TRIM_LIST_TO_META_SCRIPT",
    "BoundedListRedisSupport",
]
