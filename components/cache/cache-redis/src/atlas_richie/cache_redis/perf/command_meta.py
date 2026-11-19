"""单条 Redis 封装调用的元数据。
----
一条调用的复杂度分级 + BIGKEY 探测建议 + 简短说明。

对位 Java `cn.richie696.component.cache.redis.perf.RedisCommandMeta`
（Java 是 record，Python 用 frozen dataclass）。

**BIGKEY 探测建议**是这张表真正的价值所在：分级只说"这条命令是 O(n)"，
但没说"在读之前该先探一下多大"。五个探测位分别对应 Redis 的
`STRLEN` / `HLEN` / `LLEN` / `SCARD` / `ZCARD`。

English
--------
Metadata for one Redis call: complexity tier, BIGKEY probe hints and a
short description.
"""

from __future__ import annotations

from dataclasses import dataclass

from .complexity_tier import RedisComplexityTier


@dataclass(frozen=True)
class RedisCommandMeta:
    """复杂度分级 + BIGKEY 探测建议 + 说明。

    Attributes:
        tier: 复杂度分级。
        suggest_strlen_probe: 读 String 全量前建议 `STRLEN` / `MEMORY USAGE`。
        suggest_hlen_probe: 读 Hash 全量前建议 `HLEN`。
        suggest_llen_probe: 读 List 全量/大范围前建议 `LLEN`。
        suggest_scard_probe: 读 Set 全量前建议 `SCARD`。
        suggest_zcard_probe: 读 ZSet 大范围前建议 `ZCARD`。
        description: 简短说明（Redis 命令主导项、变量 n/k 含义）。

    English
    --------
    Complexity tier plus BIGKEY probe hints and a description.
    """

    tier: RedisComplexityTier
    suggest_strlen_probe: bool = False
    suggest_hlen_probe: bool = False
    suggest_llen_probe: bool = False
    suggest_scard_probe: bool = False
    suggest_zcard_probe: bool = False
    description: str = ""

    @classmethod
    def o1(cls, description: str) -> "RedisCommandMeta":
        """无额外探测提示的 O(1) 操作。"""
        return cls(RedisComplexityTier.O1, description=description)

    @classmethod
    def log_n(cls, description: str) -> "RedisCommandMeta":
        """有序结构，典型 O(log n)。

        **与 Java 一致**：`logN` 预设会带上 `ZCARD` 探测建议——ZSet 的
        单点操作是 O(log n)，但**结果集大小**可能很大，探一下 ZCARD 才能
        知道要不要分页。
        """
        return cls(
            RedisComplexityTier.LOG_N,
            suggest_zcard_probe=True,
            description=description,
        )

    @classmethod
    def linear(
        cls,
        description: str,
        *,
        strlen: bool = False,
        hlen: bool = False,
        llen: bool = False,
        scard: bool = False,
        zcard: bool = False,
    ) -> "RedisCommandMeta":
        """与元素数或扫描规模线性相关的操作。"""
        return cls(
            RedisComplexityTier.LINEAR_N,
            suggest_strlen_probe=strlen,
            suggest_hlen_probe=hlen,
            suggest_llen_probe=llen,
            suggest_scard_probe=scard,
            suggest_zcard_probe=zcard,
            description=description,
        )

    @classmethod
    def script(cls, description: str) -> "RedisCommandMeta":
        """Lua / 自定义脚本，复杂度由脚本内容决定。"""
        return cls(
            RedisComplexityTier.SCRIPT_OR_UNKNOWN,
            description=description,
        )

    @classmethod
    def worse(cls, description: str) -> "RedisCommandMeta":
        """理论更差或明确禁止在 ToC 使用的封装。"""
        return cls(
            RedisComplexityTier.WORSE,
            description=description,
        )

    def probe_hints(self) -> list[str]:
        """返回本条调用建议的探测命令列表（按固定顺序）。

        English
        --------
        The probe commands suggested for this call, in a stable order.
        """
        hints: list[str] = []
        if self.suggest_strlen_probe:
            hints.append("STRLEN/MEMORY_USAGE")
        if self.suggest_hlen_probe:
            hints.append("HLEN")
        if self.suggest_llen_probe:
            hints.append("LLEN")
        if self.suggest_scard_probe:
            hints.append("SCARD")
        if self.suggest_zcard_probe:
            hints.append("ZCARD")
        return hints


__all__ = ["RedisCommandMeta"]
