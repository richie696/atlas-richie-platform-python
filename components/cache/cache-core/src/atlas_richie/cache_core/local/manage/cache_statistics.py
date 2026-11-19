"""L1 本地缓存统计快照。
----
单个 region 的累计统计。计数只在 region 的 ``statistics_enabled`` 为真时
才维护——关闭时是零开销的空操作（与 JSR-107 的
``MutableConfiguration.setStatisticsEnabled`` 语义一致）。

English
--------
Cumulative statistics snapshot for one local-cache region. Counters are
only maintained when the region has `statistics_enabled` set — with the
flag off, collecting them is a no-op (matching JSR-107's
`MutableConfiguration.setStatisticsEnabled` semantics).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CacheStatistics:
    """单 region 的累计统计快照（不可变）。

    字段与 JSR-107 ``CacheStatistics`` 对齐（hits / misses / gets /
    puts / removals），并额外记录 ``expirations``（因过期被淘汰的条目数）
    与 ``evictions``（因容量上限被 LRU 淘汰的条目数）——这两项在
    JSR-107 里没有，但本地缓存要区分"过期"和"挤掉"两种淘汰原因。

    **刻意差异**：JSR-107 的 ``averageGetTime`` / ``averagePutTime`` /
    ``averageRemoveTime`` 没有移植——它们只对本机时钟分段求平均，对 L1
    这种微秒级操作意义有限，却会给每次操作加上计时开销。需要耗时分布时
    请用外部 tracing，不要用这里的计数推断。

    English
    --------
    Immutable cumulative snapshot for one region.

    The hit/miss/get/put/removal counters align with JSR-107
    `CacheStatistics`; `expirations` and `evictions` are additions that
    separate the two eviction causes a local cache must distinguish.

    **Deliberate deviation**: JSR-107's `averageGetTime` /
    `averagePutTime` / `averageRemoveTime` are not ported — they only
    average wall-clock segments, add per-operation overhead, and carry
    little meaning for microsecond-scale L1 work.
    """

    #: 命中次数（get 命中本地缓存）。
    hits: int = 0
    #: 未命中次数（get 未命中本地缓存）。
    misses: int = 0
    #: get 调用总次数（命中 + 未命中）。
    gets: int = 0
    #: 写入次数。
    puts: int = 0
    #: 删除次数（显式 remove / removeAll / clear）。
    removals: int = 0
    #: 因到达过期时间而被淘汰的条目数。
    expirations: int = 0
    #: 因超出容量上限被 LRU 淘汰的条目数。
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        """命中率 = hits / gets；没有任何 get 时返回 0.0。

        English
        --------
        Hit rate = hits / gets; 0.0 when there was no get at all.
        """
        if self.gets <= 0:
            return 0.0
        return self.hits / self.gets


__all__ = ["CacheStatistics"]
