"""Sentinel ParamFlowRule(M2.3)。

中文
----
``ParamFlowRule`` 是"热点参数限流":同一 Resource 下,按特定参数
(用户 id / 商品 id / URI 段 / header / cookie / 自定义 extractor)
的 value 分桶,每个 value 独立限流。**防止** 1 个热点 value 打爆
整个 Resource。

设计要点:

- 6 种 ``ParameterSource``:POSITIONAL / KEYWORD / HEADER / QUERY /
  COOKIE / CUSTOM(extractor 注入)
- 校验:
  - POSITIONAL 必填 ``arg_index`` (>= 0)
  - KEYWORD / HEADER / QUERY / COOKIE 必填 ``arg_key`` (非空)
  - CUSTOM 必填 ``extractor_id``
- 基数治理:``max_distinct_values`` + ``idle_ttl_ms`` + overflow policy
  (ERROR / EVICT_OLDEST,跟 ResourceRegistry 一致)

English
--------
Sentinel ParamFlowRule (M2.3).

``ParamFlowRule`` is "hot-spot parameter limiting": under the same
Resource, bucket by a specific parameter value (user id / item id /
URI segment / header / cookie / custom extractor); each value has its
own limit. **Prevents** a single hot value from blowing up the whole
Resource.

Design points:

- 6 ``ParameterSource``s: POSITIONAL / KEYWORD / HEADER / QUERY /
  COOKIE / CUSTOM (extractor injection).
- Validation:
  - POSITIONAL requires ``arg_index`` (>= 0).
  - KEYWORD / HEADER / QUERY / COOKIE require ``arg_key`` (non-empty).
  - CUSTOM requires ``extractor_id``.
- Cardinality governance: ``max_distinct_values`` + ``idle_ttl_ms`` +
  overflow policy (ERROR / EVICT_OLDEST, consistent with
  ResourceRegistry)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..errors import SentinelConfigurationError
from .selector import ResourceSelector


class ParameterSource(StrEnum):
    """中文
    ----
    热点参数来源。

    English
    --------
    Hot-spot parameter source.
    """

    POSITIONAL = "positional"  # 用 arg_index
    KEYWORD = "keyword"        # 用 arg_key
    HEADER = "header"          # 从 request header 取
    QUERY = "query"            # 从 query string 取
    COOKIE = "cookie"          # 从 cookie 取
    CUSTOM = "custom"          # 自定义 extractor_id


@dataclass(frozen=True, slots=True)
class ParamFlowRule:
    """中文
    ----
    不可变 ParamFlowRule。

    字段:

    - ``rule_id``, ``selector``, ``priority`` — 共享
    - ``source`` — 6 种 ParameterSource
    - ``arg_index`` — POSITIONAL 必填
    - ``arg_key`` — KEYWORD / HEADER / QUERY / COOKIE 必填
    - ``extractor_id`` — CUSTOM 必填(M3.x 注入)
    - ``threshold`` — 单 value 的 QPS / 并发阈值
    - ``stat_window_ms`` — 统计窗口
    - ``max_distinct_values`` — 基数上限(防止 1M+ QPS 用户打爆内存)
    - ``idle_ttl_ms`` — 闲置淘汰(0 = 永不)
    - ``overflow_error`` — True 时基数达上限 → 拒绝;False → 退化到
      "全局 bucket"(共享一个统计)

    构造校验(违反抛 ``SentinelConfigurationError``):

    - source-specific 必填字段缺失
    - threshold > 0
    - max_distinct_values >= 1

    English
    --------
    Immutable ParamFlowRule.

    Fields:

    - ``rule_id``, ``selector``, ``priority`` — shared.
    - ``source`` — 6 ParameterSources.
    - ``arg_index`` — required for POSITIONAL.
    - ``arg_key`` — required for KEYWORD / HEADER / QUERY / COOKIE.
    - ``extractor_id`` — required for CUSTOM.
    - ``threshold`` — per-value QPS / concurrency limit.
    - ``stat_window_ms`` — stat window.
    - ``max_distinct_values`` — cardinality cap.
    - ``idle_ttl_ms`` — idle eviction (0 = never).
    - ``overflow_error`` — True: hit cap → reject; False: degrade to
      "global bucket" (shared).

    Validation (violations raise ``SentinelConfigurationError``):

    - source-specific required fields.
    - threshold > 0.
    - max_distinct_values >= 1.
    """

    rule_id: str
    selector: ResourceSelector
    priority: int
    source: ParameterSource
    arg_index: int = -1
    arg_key: str = ""
    extractor_id: str = ""
    threshold: float = 0.0
    stat_window_ms: int = 1000
    max_distinct_values: int = 100
    idle_ttl_ms: int = 0
    overflow_error: bool = True

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.rule_id:
            errors.append("rule_id must be non-empty")
        if self.threshold <= 0:
            errors.append(f"threshold must be > 0 (got {self.threshold})")
        if self.max_distinct_values < 1:
            errors.append(
                f"max_distinct_values must be >= 1 (got {self.max_distinct_values})"
            )
        if self.stat_window_ms <= 0:
            errors.append(f"stat_window_ms must be > 0 (got {self.stat_window_ms})")
        if self.source is ParameterSource.POSITIONAL:
            if self.arg_index < 0:
                errors.append("POSITIONAL requires arg_index >= 0")
        elif self.source is ParameterSource.CUSTOM:
            if not self.extractor_id:
                errors.append("CUSTOM requires extractor_id")
        else:  # KEYWORD / HEADER / QUERY / COOKIE
            if not self.arg_key:
                errors.append(f"{self.source.value} requires arg_key")
        if errors:
            raise SentinelConfigurationError(
                f"ParamFlowRule {self.rule_id!r} validation failed: " + "; ".join(errors),
                field=f"param_flow.{self.rule_id}",
                reason="validation_failed",
                value=errors,
            )


__all__ = ["ParameterSource", "ParamFlowRule"]
