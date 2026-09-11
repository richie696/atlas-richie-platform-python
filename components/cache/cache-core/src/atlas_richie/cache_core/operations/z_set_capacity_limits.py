"""ZSet capacity governance constants.

Mirrors `cn.richie696.component.cache.redis.operations.ZSetCapacityLimits`.
"""

from __future__ import annotations


class ZSetCapacityLimits:
    """ZSet（有序集合）结构容量治理常量。"""

    #: README 定义的 ZSet 推荐业务上限（元素个数）
    ZSET_RECOMMENDED_MAX_ELEMENTS: int = 5_000

    #: ZSet 硬性上限（= 推荐上限 × 2）
    ZSET_HARD_MAX_ELEMENTS: int = ZSET_RECOMMENDED_MAX_ELEMENTS * 2

    @staticmethod
    def exceeds_recommended(current_size: int) -> bool:
        return current_size >= ZSetCapacityLimits.ZSET_RECOMMENDED_MAX_ELEMENTS

    @staticmethod
    def exceeds_hard_limit(current_size: int) -> bool:
        return current_size >= ZSetCapacityLimits.ZSET_HARD_MAX_ELEMENTS


__all__ = ["ZSetCapacityLimits"]
