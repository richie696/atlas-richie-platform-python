"""常用 Redis 封装场景的 `RedisCommandMeta` 预设表。
----
对位 Java `cn.richie696.component.cache.redis.perf.RedisOperationCatalog`
——26 条预设，1:1 对位。

这张表是"操作复杂度"这件事的**唯一真源**：manager 不再手写
`"O1"` / `"O_N"` 这类字符串，而是引用表里的预设。好处有两个：

1. 同一个操作在所有 manager 里是同一档，不会各写各的；
2. 每条预设自带 **BIGKEY 探测建议**——分级只说"这条命令是 O(n)"，
   探测建议才说"读之前先探一下 HLEN / ZCARD"。

**Python 侧接线状态**：表是完整的，但并非每条预设都有对应的 Python
manager 方法——例如 `STRING_SINGLE` / `LOCK_TRY` / `STREAM_*` 在 Java
侧对应的是 RedisStringManager 的单 key 写与锁管理器、streammq 组件，
Python 侧目前没有一一对应的公开方法。保留它们是为了让这张表始终是
"Redis 操作的完整分级参考"，而不是"当前已接线方法的快照"。

English
--------
Catalogue of `RedisCommandMeta` presets for common Redis call shapes.
26 entries, ported 1:1 from the Java catalog.
"""

from __future__ import annotations

from .command_meta import RedisCommandMeta


class RedisOperationCatalog:
    """Redis 操作的复杂度分级预设表。

    English
    --------
    Complexity-tier presets for Redis operations.
    """

    # ── String ─────────────────────────────────────────────────────

    #: GET/SET 单 key 单 value
    STRING_SINGLE = RedisCommandMeta.o1("GET/SET 单 key，O(1)")

    #: MGET 多 key，O(k)
    STRING_MULTI_GET = RedisCommandMeta.linear(
        "MGET 等，k 为 key 数量",
    )

    # ── Hash ───────────────────────────────────────────────────────

    #: HGET 单 field
    HASH_FIELD = RedisCommandMeta.o1("HGET 单 field，O(1)")

    #: HGETALL / 全量 entries
    HASH_FULL = RedisCommandMeta.linear(
        "HGETALL/entries，O(n) n 为 field 数",
        hlen=True,
    )

    #: HKEYS
    HASH_KEYS = RedisCommandMeta.linear(
        "HKEYS，O(n) n 为 field 数",
        hlen=True,
    )

    #: HMGET 多 field
    HASH_MULTI_FIELD = RedisCommandMeta.linear(
        "HMGET 等，k 为 field 数",
    )

    # ── List ───────────────────────────────────────────────────────

    #: LRANGE 等
    LIST_RANGE = RedisCommandMeta.linear(
        "LRANGE/LINDEX 等与区间/下标相关，注意范围",
        llen=True,
    )

    # ── Key ────────────────────────────────────────────────────────

    #: KEYS 模式匹配
    KEYS_PATTERN = RedisCommandMeta.linear(
        "KEYS pattern，O(键空间)，严禁 toC",
    )

    # ── ZSet ───────────────────────────────────────────────────────

    #: ZRANK/ZRANGE 等
    ZSET_ORDERED = RedisCommandMeta.log_n("ZSet 排名/区间，O(log n) 量级")

    #: ZUNIONSTORE / ZINTERSTORE / ZDIFF 等多 key 聚合
    ZSET_MULTI_KEY = RedisCommandMeta.linear(
        "ZSet 多 key 交并差，与参与集合元素规模相关",
        zcard=True,
    )

    #: pipeline 批量 ZSet
    ZSET_BATCH = RedisCommandMeta.linear(
        "pipeline 批量 ZSet，与批大小相关",
        zcard=True,
    )

    # ── Set ────────────────────────────────────────────────────────

    #: SMEMBERS 全量
    SET_MEMBERS = RedisCommandMeta.linear(
        "SMEMBERS 全量，O(n)",
        scard=True,
    )

    #: SUNION/SINTER 多 key
    SET_COMBINE = RedisCommandMeta.linear(
        "集合交并，规模与参与集合大小相关",
        scard=True,
    )

    # ── Geo ────────────────────────────────────────────────────────

    #: GEO 半径
    GEO_RADIUS = RedisCommandMeta.linear(
        "GEO 查询，与范围内点数相关",
    )

    #: GEOADD 单成员
    GEO_ADD = RedisCommandMeta.o1("GEOADD 单成员")

    #: GEODIST
    GEO_DIST = RedisCommandMeta.o1("GEODIST 两点")

    # ── Script ─────────────────────────────────────────────────────

    #: EVAL
    LUA_EVAL = RedisCommandMeta.script("EVAL 脚本，复杂度由脚本决定")

    # ── Lock ───────────────────────────────────────────────────────

    #: 单 key 锁尝试
    LOCK_TRY = RedisCommandMeta.o1("SET NX/EX 等加锁尝试，O(1) 量级")

    # ── Stream ─────────────────────────────────────────────────────

    #: Stream XADD
    STREAM_XADD = RedisCommandMeta.script("Stream XADD，负载与序列化相关")

    #: Stream XACK
    STREAM_ACK = RedisCommandMeta.o1("Stream XACK")

    # ── Pub/Sub ────────────────────────────────────────────────────

    #: Pub/Sub PUBLISH
    PUBLISH = RedisCommandMeta.o1("PUBLISH 广播")

    # ── Bitmap ─────────────────────────────────────────────────────

    #: SETBIT/GETBIT
    BIT_OP = RedisCommandMeta.o1("SETBIT/GETBIT")

    # ── HyperLogLog ────────────────────────────────────────────────

    #: PFADD，k 为元素个数
    HLL_PFADD = RedisCommandMeta.linear(
        "PFADD，k 为元素个数",
    )

    #: PFCOUNT
    HLL_PF_COUNT = RedisCommandMeta.o1("PFCOUNT")

    # ── Event ──────────────────────────────────────────────────────

    #: 注册 Pub/Sub 监听器（本地容器侧 O(1) 注册）
    EVENT_SUBSCRIBE = RedisCommandMeta.o1("订阅注册")

    # ── Limiter ────────────────────────────────────────────────────

    #: 限流 Lua
    LIMITER_LUA = RedisCommandMeta.script("滑动窗口限流 Lua")


__all__ = ["RedisOperationCatalog"]
