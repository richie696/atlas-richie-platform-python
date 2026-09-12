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
    """

    at_ns: int
    labels: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    admitted: int = 0
    blocked: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    avg_rt_ns: int = 0

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
    "MetricSnapshot",
    "MetricLabelKey",
    "ALLOWED_LABEL_KEYS",
    "make_label",
    "_validate_label_key",
]
