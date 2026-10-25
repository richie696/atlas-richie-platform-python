"""Sentinel MetricSnapshot(M1.4)。

中文
----
``MetricSnapshot`` 是 MetricRegistry 在某个时间点的不可变视图,供
Dashboard / event 订阅者读取;frozen + slots=True,标签集合**只允许**
低基数枚举(由 ``ALLOWED_LABEL_KEYS`` 强制)。

English
--------
Sentinel MetricSnapshot (M1.4).

``MetricSnapshot`` is MetricRegistry's immutable point-in-time view;
frozen + slots=True, and the label set is restricted to **low-cardinality
enums** (enforced by ``ALLOWED_LABEL_KEYS``)."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from ..model.enums import BlockReason
from ..model.outcome import OutcomeKind
from ..model.resource import Resource, ResourceKind, TrafficType


class MetricLabelKey(StrEnum):
    """中文
    ----
    Metric 标签的合法键(M1.4 白名单)。

    **只**允许 6 类低基数标签;**禁止** ``user_id`` / ``order_id`` /
    ``token`` 等高基数或敏感字段(违反会让指标后端爆炸 / 泄漏隐私)。

    English
    --------
    Allowed metric label keys (M1.4 whitelist).

    Only 6 low-cardinality keys are allowed; ``user_id`` / ``order_id``
    / ``token`` and similar high-cardinality / sensitive fields are
    explicitly forbidden (would blow up metric backends / leak PII)."""

    RESOURCE = "resource"
    RESOURCE_KIND = "resource_kind"
    TRAFFIC_TYPE = "traffic_type"
    RULE_KIND = "rule_kind"
    BLOCK_REASON = "block_reason"
    OUTCOME = "outcome"


# Convenience: set for fast membership check
ALLOWED_LABEL_KEYS: frozenset[str] = frozenset(k.value for k in MetricLabelKey)

# Default upper bounds for bounded response-time buckets, in nanoseconds.
# The final bucket represents values greater than the last boundary.
DEFAULT_RT_HISTOGRAM_BOUNDS_NS: tuple[int, ...] = (
    1_000_000,
    5_000_000,
    10_000_000,
    25_000_000,
    50_000_000,
    100_000_000,
    250_000_000,
    500_000_000,
    1_000_000_000,
)
MAX_RT_HISTOGRAM_BOUND_COUNT = 64
_PERCENTILE_RANK_DENOMINATOR = 100
_P95_RANK_NUMERATOR = 95


def validate_rt_histogram_bounds(bounds: tuple[int, ...]) -> tuple[int, ...]:
    """Validate and freeze bounded response-time histogram boundaries."""
    if not isinstance(bounds, tuple) or not bounds:
        raise ValueError("latency bucket bounds must be a non-empty tuple")
    if len(bounds) > MAX_RT_HISTOGRAM_BOUND_COUNT:
        raise ValueError(
            "latency bucket bounds exceed the maximum count "
            f"({MAX_RT_HISTOGRAM_BOUND_COUNT})"
        )
    previous = -1
    for boundary in bounds:
        if isinstance(boundary, bool) or not isinstance(boundary, int):
            raise ValueError("latency bucket boundaries must be integers")
        if boundary < 0 or boundary <= previous:
            raise ValueError(
                "latency bucket boundaries must be non-negative and strictly increasing"
            )
        previous = boundary
    return bounds


def latency_histogram_bucket_index(
    boundaries_ns: tuple[int, ...], sample_ns: int
) -> int:
    """Return the inclusive bucket index for a non-negative latency sample.

    Callers validate and retain immutable bucket boundaries once when the
    accumulator is created; this helper centralizes only sample validation
    and bucket placement for the Sentinel and framework-adapter registries.
    """
    if isinstance(sample_ns, bool) or not isinstance(sample_ns, int) or sample_ns < 0:
        raise ValueError("latency sample must be a non-negative integer")
    return bisect_left(boundaries_ns, sample_ns)


@dataclass(frozen=True, slots=True)
class LatencyHistogram:
    """Bounded, mergeable response-time distribution without raw samples.

    ``bucket_counts`` contains one count for each inclusive upper boundary,
    followed by an overflow bucket for observations above the final bound.
    ``p95_upper_bound_ns`` uses the nearest-rank position and reports the
    selected bucket's upper boundary; it is not an interpolated percentile.
    """

    boundaries_ns: tuple[int, ...]
    bucket_counts: tuple[int, ...]
    sample_count: int
    total_ns: int
    min_ns: int | None
    max_ns: int | None

    def __post_init__(self) -> None:
        validate_rt_histogram_bounds(self.boundaries_ns)
        if not isinstance(self.bucket_counts, tuple):
            raise ValueError("bucket_counts must be an immutable tuple")
        if len(self.bucket_counts) != len(self.boundaries_ns) + 1:
            raise ValueError("bucket count length must equal bounds length + 1")
        if any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in self.bucket_counts
        ):
            raise ValueError("bucket counts must be non-negative integers")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count < 0
        ):
            raise ValueError("sample_count must be a non-negative integer")
        if sum(self.bucket_counts) != self.sample_count:
            raise ValueError("bucket counts must sum to sample_count")
        if isinstance(self.total_ns, bool) or not isinstance(self.total_ns, int):
            raise ValueError("total_ns must be an integer")
        if self.total_ns < 0:
            raise ValueError("total_ns must be non-negative")
        if self.sample_count == 0:
            if self.total_ns != 0 or self.min_ns is not None or self.max_ns is not None:
                raise ValueError("empty histogram must have zero total and no min/max")
            return
        if self.min_ns is None or self.max_ns is None:
            raise ValueError("non-empty histogram requires min_ns and max_ns")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (self.min_ns, self.max_ns)
        ):
            raise ValueError("min_ns and max_ns must be non-negative integers")
        if self.min_ns > self.max_ns or self.total_ns < self.min_ns:
            raise ValueError("histogram min/max/total are inconsistent")
        if self.total_ns > self.max_ns * self.sample_count:
            raise ValueError("histogram total exceeds max_ns times sample_count")

    def combine(self, other: LatencyHistogram) -> LatencyHistogram:
        """Merge another histogram with identical bucket boundaries.

        Bucket counts are additive, so the result preserves the pooled
        distribution needed for aggregate percentiles. Percentiles themselves
        must never be averaged across histograms.
        """
        if not isinstance(other, LatencyHistogram):
            raise TypeError("other must be a latency histogram")
        if self.boundaries_ns != other.boundaries_ns:
            raise ValueError("latency histograms must use identical boundaries")

        sample_count = self.sample_count + other.sample_count
        if sample_count == 0:
            return LatencyHistogram(
                boundaries_ns=self.boundaries_ns,
                bucket_counts=tuple(0 for _ in self.bucket_counts),
                sample_count=0,
                total_ns=0,
                min_ns=None,
                max_ns=None,
            )

        minimums = tuple(
            value for value in (self.min_ns, other.min_ns) if value is not None
        )
        maximums = tuple(
            value for value in (self.max_ns, other.max_ns) if value is not None
        )
        return LatencyHistogram(
            boundaries_ns=self.boundaries_ns,
            bucket_counts=tuple(
                left + right
                for left, right in zip(
                    self.bucket_counts, other.bucket_counts, strict=True
                )
            ),
            sample_count=sample_count,
            total_ns=self.total_ns + other.total_ns,
            min_ns=min(minimums),
            max_ns=max(maximums),
        )

    @property
    def p95_upper_bound_ns(self) -> int | None:
        """Return the nearest-rank p95 bucket upper bound, if it is bounded.

        The result is a histogram estimate, not an interpolated percentile.
        Empty histograms and percentiles that fall into the overflow bucket
        have no finite upper bound and return ``None``.
        """
        if self.sample_count == 0:
            return None

        rank = (
            self.sample_count * _P95_RANK_NUMERATOR + _PERCENTILE_RANK_DENOMINATOR - 1
        ) // _PERCENTILE_RANK_DENOMINATOR
        cumulative_count = 0
        for index, boundary_ns in enumerate(self.boundaries_ns):
            cumulative_count += self.bucket_counts[index]
            if cumulative_count >= rank:
                return boundary_ns
        return None


def _validate_label_key(key: str) -> None:
    """中文
    ----
    校验 ``key`` 在白名单内;不在则抛 ``ValueError``。M1.4 静态防御。

    English
    --------
    Validate ``key`` is in whitelist; otherwise raise ``ValueError``.
    M1.4 static defense.
    """
    if key not in ALLOWED_LABEL_KEYS:
        raise ValueError(
            f"metric label key {key!r} is not in the allowed whitelist "
            f"{sorted(ALLOWED_LABEL_KEYS)}"
        )


def make_label(
    *,
    resource: Resource,
    outcome: OutcomeKind | None = None,
    block_reason: BlockReason | None = None,
    rule_kind: str | None = None,
) -> dict[str, str]:
    """中文
    ----
    工厂函数:从 ``Resource`` + outcome / block_reason / rule_kind
    构造 metric 标签 dict。**只**返回白名单键,且自动 stringify。

    English
    --------
    Factory: build a metric label dict from ``Resource`` + outcome /
    block_reason / rule_kind. Returns only whitelisted keys, with
    values stringified."""

    label: dict[str, str] = {
        MetricLabelKey.RESOURCE.value: resource.name,
        MetricLabelKey.RESOURCE_KIND.value: resource.kind.value,
        MetricLabelKey.TRAFFIC_TYPE.value: resource.traffic_type.value,
    }
    if outcome is not None:
        label[MetricLabelKey.OUTCOME.value] = outcome.value
    if block_reason is not None:
        label[MetricLabelKey.BLOCK_REASON.value] = block_reason.value
    if rule_kind is not None:
        label[MetricLabelKey.RULE_KIND.value] = rule_kind
    # Static guard: all keys are in whitelist by construction
    for k in label:
        _validate_label_key(k)
    return label


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    """中文
    ----
    不可变指标快照(某时间点的 MetricRegistry 状态)。

    - ``at_ns`` — 快照时间戳(``time.time_ns()``)
    - ``labels`` — 标签 dict(只读视图,白名单)
    - ``admitted`` — 通过 entry 数
    - ``blocked`` — 拒绝 entry 数
    - ``succeeded`` — 业务成功数
    - ``failed`` — 业务失败数
    - ``cancelled`` — 协程取消数
    - ``avg_rt_ns`` — 平均响应时间(纳秒,``0`` 表示无样本)
    - ``latency_histogram`` — bounded RT distribution; ``None`` is
      retained for snapshots manually constructed by older callers.

    English
    --------
    Immutable metric snapshot (MetricRegistry state at one point).

    - ``at_ns`` — snapshot timestamp (``time.time_ns()``).
    - ``labels`` — label dict (read-only view, whitelisted).
    - ``admitted`` — admitted entry count.
    - ``blocked`` — blocked entry count.
    - ``succeeded`` — business success count.
    - ``failed`` — business failure count.
    - ``cancelled`` — coroutine cancellation count.
    - ``avg_rt_ns`` — average response time in ns (``0`` when no
      samples).
    - ``latency_histogram`` — bounded RT distribution; ``None`` is
      retained for snapshots manually constructed by older callers.
    """

    at_ns: int
    labels: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    admitted: int = 0
    blocked: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    avg_rt_ns: int = 0
    latency_histogram: LatencyHistogram | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.labels, MappingProxyType):
            object.__setattr__(self, "labels", MappingProxyType(dict(self.labels)))
        for k in self.labels:
            _validate_label_key(k)

    @property
    def total(self) -> int:
        """中文
        ----
        所有 entry 数(admitted + blocked)。

        English
        --------
        Total entry count (admitted + blocked).
        """
        return self.admitted + self.blocked


__all__ = [
    "ALLOWED_LABEL_KEYS",
    "DEFAULT_RT_HISTOGRAM_BOUNDS_NS",
    "MAX_RT_HISTOGRAM_BOUND_COUNT",
    "LatencyHistogram",
    "MetricLabelKey",
    "MetricSnapshot",
    "_validate_label_key",
    "latency_histogram_bucket_index",
    "make_label",
    "validate_rt_histogram_bounds",
]
