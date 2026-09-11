"""Set capacity governance constants.

Mirrors `cn.richie696.component.cache.redis.operations.SetCapacityLimits`.
Aligned with README "Set BIGKEY ceiling" (5,000 elements).
"""

from __future__ import annotations


class SetCapacityLimits:
    """Set 结构容量治理常量。"""

    #: README 定义的 Set 推荐业务上限（元素个数）
    SET_RECOMMENDED_MAX_ELEMENTS: int = 5_000

    #: Set 硬性上限（= 推荐上限 × 2），超过则直接拒绝写入。
    SET_HARD_MAX_ELEMENTS: int = SET_RECOMMENDED_MAX_ELEMENTS * 2

    @staticmethod
    def exceeds_recommended(current_size: int) -> bool:
        """当前元素数是否已超过推荐上限（WARN 级别）。"""
        return current_size >= SetCapacityLimits.SET_RECOMMENDED_MAX_ELEMENTS

    @staticmethod
    def exceeds_hard_limit(current_size: int) -> bool:
        """当前元素数是否已超过硬性上限（拒绝写入）。"""
        return current_size >= SetCapacityLimits.SET_HARD_MAX_ELEMENTS


__all__ = ["SetCapacityLimits"]
