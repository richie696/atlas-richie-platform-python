"""布隆过滤器配置类。
----
布隆过滤器配置类。提供布隆过滤器的启用、实现类型、key、预期插入数量、
误判率等配置项。

English
--------
Bloom filter configuration.

Mirrors `cn.richie696.component.cache.config.BloomFilterConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BloomFilterType(StrEnum):
    """布隆过滤器实现类型。

    English
    --------
    Bloom filter backend type.
    """

    #: Redisson
    REDISSON = "redisson"

    #: Guava
    GUAVA = "guava"


@dataclass
class BloomFilterConfig:
    """布隆过滤器配置类。

    Attributes:
        enable: 是否启用布隆过滤器
        type: 布隆过滤器实现类型
        key: 布隆过滤器数据保存路径
        expected_insertions: 预期插入数量。该值应略大于实际最大数据量，
            不能太小，否则误判率会上升。
        false_probability: 误判率（false positive probability）。常用值：
            0.01、0.001、0.0001

    English
    --------
    Bloom filter configuration holder.
    """

    #: 是否启用布隆过滤器
    enable: bool = False
    #: 布隆过滤器实现类型
    type: BloomFilterType = BloomFilterType.REDISSON
    #: 布隆过滤器数据保存路径
    key: str = "platform:cache:bloom:global"
    #: 预期插入数量。该值应略大于实际最大数据量，不能太小，否则误判率会上升。
    expected_insertions: int = 10_000_000
    #: 误判率（false positive probability）。常用值：0.01、0.001、0.0001
    false_probability: float = 0.001


__all__ = ["BloomFilterConfig", "BloomFilterType"]
