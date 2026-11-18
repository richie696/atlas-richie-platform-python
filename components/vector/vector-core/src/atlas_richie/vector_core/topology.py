"""向量 Store 的能力与分数语义契约。

对应 Java `cn.richie696.component.vector.topology` 中的声明式部分
（不含 Spring 自动装配、连接注册表与启动编排）。

为什么需要这层：不同 provider 的"score"根本不是同一个量纲 —— Milvus 返回
距离（越小越好）、pgvector 返回余弦距离、Redis 返回归一化相似度。直接把
`minScore` 下推给 provider 会静默改变召回集。所以每个 Store 必须声明
`VectorScoreDescriptor`（量纲、范围、是否归一化、阈值由谁执行），
`VectorQueryResolver` 据此决定阈值语义，`VectorScoreFusionGuard` 据此
拒绝未被证明可比的跨 Store 分数融合。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

_STORE_ID = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")


class VectorStoreId:
    """Store 标识，必须匹配 `[a-z0-9]+(?:[-_][a-z0-9]+)*`。"""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not _STORE_ID.fullmatch(value):
            raise ValueError(
                f"vector store id must match {_STORE_ID.pattern}: {value!r}"
            )
        self._value = value

    @property
    def value(self) -> str:
        return self._value

    @classmethod
    def of(cls, value: str) -> VectorStoreId:
        return cls(value)

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"VectorStoreId({self._value!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, VectorStoreId) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)


class VectorCapability(StrEnum):
    NATIVE_FILTER = "NATIVE_FILTER"
    ACL_FILTER = "ACL_FILTER"
    ACL_SAFE_HYBRID = "ACL_SAFE_HYBRID"
    CANDIDATE_VECTOR = "CANDIDATE_VECTOR"
    SERVER_SIDE_MMR = "SERVER_SIDE_MMR"
    QUERY_TUNING = "QUERY_TUNING"
    INDEX_LIFECYCLE = "INDEX_LIFECYCLE"
    SCORE_STAGES = "SCORE_STAGES"
    PRECOMPUTED_VECTOR = "PRECOMPUTED_VECTOR"

    @property
    def id(self) -> str:
        return self.value

    @classmethod
    def from_id(cls, value: str) -> VectorCapability:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("vector capability id must not be blank")
        try:
            return cls(value.upper())
        except ValueError:
            raise ValueError(f"unknown vector capability: {value}") from None


class VectorCapabilityOperation(StrEnum):
    SEARCH_TEXT = "SEARCH_TEXT"
    SEARCH_VECTOR = "SEARCH_VECTOR"
    SEARCH_IMAGE = "SEARCH_IMAGE"
    HYBRID_SEARCH = "HYBRID_SEARCH"
    UPSERT = "UPSERT"
    INDEX_MANAGEMENT = "INDEX_MANAGEMENT"


class VectorScoreStage(StrEnum):
    RAW_DISTANCE = "RAW_DISTANCE"
    VECTOR_SCORE = "VECTOR_SCORE"
    LEXICAL_SCORE = "LEXICAL_SCORE"
    FUSED_SCORE = "FUSED_SCORE"
    RERANK_SCORE = "RERANK_SCORE"
    FINAL_SCORE = "FINAL_SCORE"


class VectorScoreDirection(StrEnum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"


class VectorScoreThresholdKind(StrEnum):
    NORMALIZED_RELEVANCE = "NORMALIZED_RELEVANCE"
    PROVIDER_RAW = "PROVIDER_RAW"


class VectorScoreThresholdExecution(StrEnum):
    PROVIDER_PUSHED = "PROVIDER_PUSHED"
    ADAPTER_NORMALIZED = "ADAPTER_NORMALIZED"
    UNSUPPORTED = "UNSUPPORTED"


_DEFAULT_OPERATIONS: Mapping[VectorCapability, frozenset[VectorCapabilityOperation]] = {
    VectorCapability.NATIVE_FILTER: frozenset(
        {
            VectorCapabilityOperation.SEARCH_TEXT,
            VectorCapabilityOperation.SEARCH_VECTOR,
            VectorCapabilityOperation.HYBRID_SEARCH,
        }
    ),
    VectorCapability.ACL_FILTER: frozenset(
        {
            VectorCapabilityOperation.SEARCH_TEXT,
            VectorCapabilityOperation.SEARCH_VECTOR,
            VectorCapabilityOperation.HYBRID_SEARCH,
        }
    ),
    VectorCapability.QUERY_TUNING: frozenset(
        {
            VectorCapabilityOperation.SEARCH_TEXT,
            VectorCapabilityOperation.SEARCH_VECTOR,
            VectorCapabilityOperation.HYBRID_SEARCH,
        }
    ),
    VectorCapability.SCORE_STAGES: frozenset(
        {
            VectorCapabilityOperation.SEARCH_TEXT,
            VectorCapabilityOperation.SEARCH_VECTOR,
            VectorCapabilityOperation.HYBRID_SEARCH,
        }
    ),
    VectorCapability.ACL_SAFE_HYBRID: frozenset({VectorCapabilityOperation.HYBRID_SEARCH}),
    VectorCapability.CANDIDATE_VECTOR: frozenset(
        {
            VectorCapabilityOperation.SEARCH_TEXT,
            VectorCapabilityOperation.SEARCH_VECTOR,
            VectorCapabilityOperation.SEARCH_IMAGE,
            VectorCapabilityOperation.HYBRID_SEARCH,
        }
    ),
    VectorCapability.SERVER_SIDE_MMR: frozenset(
        {
            VectorCapabilityOperation.SEARCH_TEXT,
            VectorCapabilityOperation.SEARCH_VECTOR,
            VectorCapabilityOperation.SEARCH_IMAGE,
            VectorCapabilityOperation.HYBRID_SEARCH,
        }
    ),
    VectorCapability.INDEX_LIFECYCLE: frozenset({VectorCapabilityOperation.INDEX_MANAGEMENT}),
    VectorCapability.PRECOMPUTED_VECTOR: frozenset(
        {VectorCapabilityOperation.SEARCH_VECTOR, VectorCapabilityOperation.UPSERT}
    ),
}


def default_operations(capability: VectorCapability) -> frozenset[VectorCapabilityOperation]:
    return _DEFAULT_OPERATIONS[capability]


@dataclass(frozen=True, slots=True)
class VectorCapabilityDescriptor:
    capability: VectorCapability
    version: str = "1.0"
    operations: frozenset[VectorCapabilityOperation] | None = None
    constraints: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.capability is None:
            raise ValueError("capability must not be None")
        if not self.version or not self.version.strip():
            raise ValueError("capability version must not be blank")
        operations = (
            default_operations(self.capability)
            if self.operations is None
            else frozenset(self.operations)
        )
        if not operations:
            raise ValueError("capability operations must not be empty")
        object.__setattr__(self, "operations", operations)
        object.__setattr__(
            self, "constraints", MappingProxyType(dict(self.constraints or {}))
        )

    @classmethod
    def supported(cls, capability: VectorCapability) -> VectorCapabilityDescriptor:
        return cls(capability, "1.0", None, {})


class VectorStoreCapabilities:
    """一个 Store 声明支持的能力集合。"""

    __slots__ = ("_descriptors",)

    def __init__(self, descriptors: Iterable[VectorCapabilityDescriptor]) -> None:
        indexed: dict[VectorCapability, VectorCapabilityDescriptor] = {}
        for descriptor in descriptors:
            if descriptor.capability in indexed:
                raise ValueError(
                    f"duplicate vector capability: {descriptor.capability.id}"
                )
            indexed[descriptor.capability] = descriptor
        self._descriptors = MappingProxyType(indexed)

    @classmethod
    def none(cls) -> VectorStoreCapabilities:
        return cls(())

    @classmethod
    def of(cls, *capabilities: VectorCapability) -> VectorStoreCapabilities:
        return cls(VectorCapabilityDescriptor.supported(c) for c in capabilities)

    def supports(self, capability: VectorCapability) -> bool:
        return capability in self._descriptors

    def descriptor(self, capability: VectorCapability) -> VectorCapabilityDescriptor | None:
        return self._descriptors.get(capability)

    def ids(self) -> frozenset[str]:
        return frozenset(c.id for c in self._descriptors)

    def descriptors(self) -> tuple[VectorCapabilityDescriptor, ...]:
        return tuple(self._descriptors.values())

    def require_all(
        self, store_id: VectorStoreId | str, required_capabilities: Iterable[str]
    ) -> None:
        missing = sorted(
            capability.id
            for capability in (VectorCapability.from_id(c) for c in required_capabilities)
            if not self.supports(capability)
        )
        if missing:
            raise ValueError(
                f"vector store required capabilities are not available: "
                f"{store_id} -> {missing}"
            )


@dataclass(frozen=True, slots=True)
class VectorScoreDescriptor:
    stage: VectorScoreStage
    source: str
    direction: VectorScoreDirection
    minimum: float | None = None
    maximum: float | None = None
    normalized: bool = False
    comparable_across_queries: bool = False
    transformation: str = "identity"
    threshold_kind: VectorScoreThresholdKind | None = None
    threshold_execution: VectorScoreThresholdExecution | None = None

    def __post_init__(self) -> None:
        if self.stage is None:
            raise ValueError("vector score stage must not be None")
        if not self.source or not self.source.strip():
            raise ValueError("vector score source must not be blank")
        if self.direction is None:
            raise ValueError("vector score direction must not be None")
        for name in ("minimum", "maximum"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"vector score {name} must be finite")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("vector score minimum must not exceed maximum")
        if self.normalized and (self.minimum is None or self.maximum is None):
            raise ValueError("normalized vector score requires a declared range")
        if not self.transformation or not self.transformation.strip():
            raise ValueError("vector score transformation must not be blank")

        kind = self.threshold_kind
        if kind is None:
            kind = (
                VectorScoreThresholdKind.NORMALIZED_RELEVANCE
                if self.normalized
                else VectorScoreThresholdKind.PROVIDER_RAW
            )
        execution = self.threshold_execution
        if execution is None:
            execution = (
                VectorScoreThresholdExecution.ADAPTER_NORMALIZED
                if self.normalized
                else VectorScoreThresholdExecution.UNSUPPORTED
            )
        if self.normalized and kind is VectorScoreThresholdKind.PROVIDER_RAW:
            raise ValueError(
                "normalized vector scores cannot declare PROVIDER_RAW threshold kind"
            )
        if not self.normalized and kind is VectorScoreThresholdKind.NORMALIZED_RELEVANCE:
            raise ValueError(
                "unnormalized vector scores cannot declare NORMALIZED_RELEVANCE threshold kind"
            )
        object.__setattr__(self, "threshold_kind", kind)
        object.__setattr__(self, "threshold_execution", execution)


class VectorScoreSemantics:
    """一个 Store 各分数阶段的语义声明，每个阶段至多一个描述符。"""

    __slots__ = ("_descriptors",)

    def __init__(self, descriptors: Iterable[VectorScoreDescriptor]) -> None:
        indexed: dict[VectorScoreStage, VectorScoreDescriptor] = {}
        for descriptor in descriptors:
            if descriptor is None:
                raise ValueError("vector score descriptors must not contain None")
            if descriptor.stage in indexed:
                raise ValueError(f"duplicate vector score stage: {descriptor.stage}")
            indexed[descriptor.stage] = descriptor
        if not indexed:
            raise ValueError("vector score descriptors must not be empty")
        self._descriptors = MappingProxyType(indexed)

    def descriptor(self, stage: VectorScoreStage) -> VectorScoreDescriptor | None:
        if stage is None:
            raise ValueError("vector score stage must not be None")
        return self._descriptors.get(stage)

    def descriptors(self) -> tuple[VectorScoreDescriptor, ...]:
        return tuple(self._descriptors.values())

    @classmethod
    def final_score(
        cls,
        source: str,
        minimum: float | None,
        maximum: float | None,
        normalized: bool,
        transformation: str,
        threshold_kind: VectorScoreThresholdKind | None = None,
        threshold_execution: VectorScoreThresholdExecution | None = None,
    ) -> VectorScoreSemantics:
        return cls(
            [
                VectorScoreDescriptor(
                    stage=VectorScoreStage.FINAL_SCORE,
                    source=source,
                    direction=VectorScoreDirection.HIGHER_IS_BETTER,
                    minimum=minimum,
                    maximum=maximum,
                    normalized=normalized,
                    comparable_across_queries=False,
                    transformation=transformation,
                    threshold_kind=threshold_kind,
                    threshold_execution=threshold_execution,
                )
            ]
        )


class VectorScoreFusionGuard:
    """跨 Store 分数融合前的可比性证明。"""

    @staticmethod
    def require_comparable(
        stage: VectorScoreStage, stores: Sequence[VectorScoreSemantics]
    ) -> VectorScoreDescriptor:
        if stage is None:
            raise ValueError("score stage must not be None")
        if stores is None or len(stores) < 2:
            raise ValueError(
                "cross-Store score comparison requires at least two Stores"
            )
        baseline: VectorScoreDescriptor | None = None
        for semantics in stores:
            descriptor = None if semantics is None else semantics.descriptor(stage)
            if descriptor is None or not (
                descriptor.normalized and descriptor.comparable_across_queries
            ):
                raise _incompatible(stage)
            if baseline is None:
                baseline = descriptor
            elif not _compatible(baseline, descriptor):
                raise _incompatible(stage)
        assert baseline is not None
        return baseline


def _compatible(left: VectorScoreDescriptor, right: VectorScoreDescriptor) -> bool:
    return (
        left.source == right.source
        and left.direction == right.direction
        and left.minimum == right.minimum
        and left.maximum == right.maximum
        and left.transformation == right.transformation
    )


def _incompatible(stage: VectorScoreStage) -> ValueError:
    return ValueError(
        f"cross-Store score comparison is not proven compatible for stage {stage}"
    )


__all__ = [
    "VectorStoreId",
    "VectorCapability",
    "VectorCapabilityOperation",
    "VectorCapabilityDescriptor",
    "VectorStoreCapabilities",
    "VectorScoreStage",
    "VectorScoreDirection",
    "VectorScoreThresholdKind",
    "VectorScoreThresholdExecution",
    "VectorScoreDescriptor",
    "VectorScoreSemantics",
    "VectorScoreFusionGuard",
    "default_operations",
]