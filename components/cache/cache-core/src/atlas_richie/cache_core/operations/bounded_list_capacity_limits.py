"""Bounded List (queue / stack) capacity governance constants.

Mirrors `cn.richie696.component.cache.redis.operations.BoundedListCapacityLimits`.
Aligned with the README "List BIGKEY ceiling" reference (5,000 elements);
`BOUNDED_MAX_LEN_CEILING` is the absolute cap (strictly below the BIGKEY line).
"""

from __future__ import annotations


class BoundedListCapacityLimits:
    """有界 List 结构（队列 / 栈）容量治理常量。

    与 README「大 Key 阈值参考 — List 推荐业务上限 5,000 元素」对齐；
    `BOUNDED_MAX_LEN_CEILING` 为 maxLen 绝对封顶（严格低于 BIGKEY 红线）。
    """

    #: README 定义的 List 推荐业务上限（元素个数）
    LIST_BIGKEY_RECOMMENDED_MAX_ELEMENTS: int = 5_000

    #: 有界队列 / 栈的 maxLen 绝对上限（= 推荐业务上限 − 1）
    BOUNDED_MAX_LEN_CEILING: int = LIST_BIGKEY_RECOMMENDED_MAX_ELEMENTS - 1

    MIN_MAX_LEN: int = 1

    META_KEY_SUFFIX: str = ":meta"

    @staticmethod
    def meta_key(key: str) -> str:
        if key.endswith(BoundedListCapacityLimits.META_KEY_SUFFIX):
            raise ValueError(
                f"key must not already end with '{BoundedListCapacityLimits.META_KEY_SUFFIX}': {key}"
            )
        return key + BoundedListCapacityLimits.META_KEY_SUFFIX

    @staticmethod
    def validate_max_len(max_len: int) -> None:
        if max_len < BoundedListCapacityLimits.MIN_MAX_LEN or max_len > BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING:
            raise ValueError(
                f"maxLen must be in [{BoundedListCapacityLimits.MIN_MAX_LEN}, "
                f"{BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING}] (List BIGKEY ceiling), "
                f"got {max_len}"
            )

    @staticmethod
    def assert_max_len_matches(key: str, requested: int, existing: int) -> None:
        if requested != existing:
            raise ValueError(
                f"Bounded structure '{key}' already exists with maxLen={existing}, "
                f"requested maxLen={requested}"
            )

    @staticmethod
    def parse_meta_max_len(logical_key: str, raw) -> int:
        if raw is None:
            raise KeyError(f"Bounded meta missing for key: {logical_key}")
        try:
            max_len = int(str(raw).strip())
            BoundedListCapacityLimits.validate_max_len(max_len)
            return max_len
        except (TypeError, ValueError) as ex:
            raise KeyError(
                f"Invalid bounded meta for key: {logical_key}, raw={raw}"
            ) from ex

    @staticmethod
    def compute_doubled_capacity(current: int) -> int:
        BoundedListCapacityLimits.validate_max_len(current)
        if current >= BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING:
            return BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING
        doubled = current * 2
        return min(doubled, BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING)

    @staticmethod
    def can_grow(current_max_len: int) -> bool:
        BoundedListCapacityLimits.validate_max_len(current_max_len)
        return current_max_len < BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING


__all__ = ["BoundedListCapacityLimits"]
