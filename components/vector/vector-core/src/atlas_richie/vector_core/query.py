"""高级向量查询的参数解析与安全上限。

对应 Java `cn.richie696.component.vector.query`。

优先级冻结为 **Core < Provider < Store < Request**：Core 提供安全兜底，
provider 适配器声明自己的默认，单个 Store 可再覆盖，请求显式值最终生效。
`source_for` 让每个标量选项都能归因到胜出层，供执行回执审计。

硬上限（MAX_TOP_K / MAX_CANDIDATES / MAX_RETURN_FIELDS / MAX_TIMEOUT）
不可被任何层覆盖 —— 它们是资源保护，不是偏好。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from .filters import VectorFilter
from .topology import (
    VectorScoreDescriptor,
    VectorScoreSemantics,
    VectorScoreStage,
    VectorScoreThresholdKind,
)

MAX_TOP_K = 1_000
MAX_CANDIDATES = 2_000
MAX_RETURN_FIELDS = 64
MAX_TIMEOUT = timedelta(minutes=2)

_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}")


class VectorConsistencyPreference(StrEnum):
    PROVIDER_DEFAULT = "PROVIDER_DEFAULT"
    EVENTUAL = "EVENTUAL"
    BOUNDED = "BOUNDED"
    STRONG = "STRONG"


class VectorParameterSource(StrEnum):
    CORE_DEFAULT = "CORE_DEFAULT"
    PROVIDER_DEFAULT = "PROVIDER_DEFAULT"
    STORE_DEFAULT = "STORE_DEFAULT"
    REQUEST = "REQUEST"


class VectorParameterDisposition(StrEnum):
    APPLIED = "APPLIED"
    DEFAULTED = "DEFAULTED"
    REJECTED = "REJECTED"
    IGNORED = "IGNORED"


class VectorQueryErrorCode(StrEnum):
    INVALID_VALUE = "INVALID_VALUE"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    TIMEOUT = "TIMEOUT"
    CONCURRENCY_LIMIT = "CONCURRENCY_LIMIT"
    UNSUPPORTED_OPTION = "UNSUPPORTED_OPTION"
    CONFLICTING_OPTIONS = "CONFLICTING_OPTIONS"


class VectorQueryValidationException(ValueError):
    def __init__(self, code: VectorQueryErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@runtime_checkable
class ProviderQueryOptions(Protocol):
    """provider 私有调参入口，必须自带扩展标识与版本以便审计。"""

    def extension_id(self) -> str: ...

    def version(self) -> str: ...


@dataclass(frozen=True, slots=True)
class VectorDiversificationOptions:
    include_vectors: bool = False
    mmr_enabled: bool = False
    lambda_: float = 0.5

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.lambda_)
            or self.lambda_ < 0.0
            or self.lambda_ > 1.0
        ):
            raise VectorQueryValidationException(
                VectorQueryErrorCode.INVALID_VALUE, "MMR lambda must be within [0,1]"
            )

    def requires_candidate_vectors(self) -> bool:
        return self.include_vectors or self.mmr_enabled


DISABLED_DIVERSIFICATION = VectorDiversificationOptions()


@dataclass(frozen=True, slots=True)
class VectorQueryDefaults:
    top_k: int | None = None
    min_score: float | None = None
    candidate_limit: int | None = None
    timeout: timedelta | None = None
    consistency: VectorConsistencyPreference | None = None
    return_fields: frozenset[str] = field(default_factory=frozenset)
    threshold_kind: VectorScoreThresholdKind | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "return_fields", frozenset(self.return_fields or ()))

    def overlay(self, override: VectorQueryDefaults | None) -> VectorQueryDefaults:
        if override is None:
            return self
        return VectorQueryDefaults(
            top_k=override.top_k if override.top_k is not None else self.top_k,
            min_score=(
                override.min_score if override.min_score is not None else self.min_score
            ),
            candidate_limit=(
                override.candidate_limit
                if override.candidate_limit is not None
                else self.candidate_limit
            ),
            timeout=override.timeout if override.timeout is not None else self.timeout,
            consistency=(
                override.consistency
                if override.consistency is not None
                else self.consistency
            ),
            return_fields=(
                override.return_fields if override.return_fields else self.return_fields
            ),
            threshold_kind=(
                override.threshold_kind
                if override.threshold_kind is not None
                else self.threshold_kind
            ),
        )


CORE_SAFE_DEFAULTS = VectorQueryDefaults(
    top_k=10,
    min_score=0.0,
    candidate_limit=10,
    timeout=timedelta(seconds=30),
    consistency=VectorConsistencyPreference.PROVIDER_DEFAULT,
    return_fields=frozenset(),
    threshold_kind=VectorScoreThresholdKind.NORMALIZED_RELEVANCE,
)


@dataclass(frozen=True, slots=True)
class VectorQueryRequest:
    query: str
    top_k: int | None = None
    min_score: float | None = None
    threshold_kind: VectorScoreThresholdKind | None = None
    filter: VectorFilter | None = None
    return_fields: frozenset[str] = field(default_factory=frozenset)
    candidate_limit: int | None = None
    timeout: timedelta | None = None
    consistency: VectorConsistencyPreference | None = None
    diversification: VectorDiversificationOptions = DISABLED_DIVERSIFICATION
    provider_options: ProviderQueryOptions | None = None

    def __post_init__(self) -> None:
        if not self.query or not self.query.strip():
            raise VectorQueryValidationException(
                VectorQueryErrorCode.INVALID_VALUE, "query must not be blank"
            )
        if self.min_score is not None and not math.isfinite(self.min_score):
            raise VectorQueryValidationException(
                VectorQueryErrorCode.INVALID_VALUE, "minScore must be finite"
            )
        object.__setattr__(self, "return_fields", frozenset(self.return_fields or ()))
        if self.diversification is None:
            object.__setattr__(self, "diversification", DISABLED_DIVERSIFICATION)

    @classmethod
    def of(cls, query: str) -> VectorQueryRequest:
        return cls(query=query)


@dataclass(frozen=True, slots=True)
class ResolvedVectorQuery:
    query: str
    top_k: int
    min_score: float
    threshold_kind: VectorScoreThresholdKind
    filter: VectorFilter | None
    return_fields: frozenset[str]
    candidate_limit: int
    timeout: timedelta
    consistency: VectorConsistencyPreference
    diversification: VectorDiversificationOptions
    provider_options: ProviderQueryOptions | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "return_fields", frozenset(self.return_fields or ()))
        if self.diversification is None:
            object.__setattr__(self, "diversification", DISABLED_DIVERSIFICATION)
        if self.threshold_kind is None:
            object.__setattr__(
                self, "threshold_kind", VectorScoreThresholdKind.NORMALIZED_RELEVANCE
            )


@dataclass(frozen=True, slots=True)
class VectorParameterEvidence:
    name: str
    requested: str | None
    configured: str | None
    effective: str | None
    applied: str | None
    source: VectorParameterSource
    disposition: VectorParameterDisposition
    evidence: str

    def __post_init__(self) -> None:
        if (
            not self.name
            or not self.name.strip()
            or self.source is None
            or self.disposition is None
            or not self.evidence
            or not self.evidence.strip()
        ):
            raise ValueError("vector parameter evidence is incomplete")


class VectorQueryResolver:
    """按 Core < Provider < Store < Request 解析并校验一次查询。"""

    def __init__(
        self,
        provider_defaults: VectorQueryDefaults | None = None,
        store_defaults: VectorQueryDefaults | None = None,
        score_semantics: VectorScoreSemantics | None = None,
    ) -> None:
        self._provider_defaults = provider_defaults
        self._store_defaults = store_defaults
        self._score_semantics = score_semantics
        self._configured = CORE_SAFE_DEFAULTS.overlay(provider_defaults).overlay(
            store_defaults
        )
        self._validate_defaults(self._configured)

    @property
    def configured(self) -> VectorQueryDefaults:
        return self._configured

    def resolve(self, request: VectorQueryRequest | None) -> ResolvedVectorQuery:
        if request is None:
            raise VectorQueryValidationException(
                VectorQueryErrorCode.INVALID_VALUE, "query request is required"
            )
        configured = self._configured
        top_k = request.top_k if request.top_k is not None else configured.top_k
        min_score = (
            request.min_score if request.min_score is not None else configured.min_score
        )
        candidate_limit = (
            request.candidate_limit
            if request.candidate_limit is not None
            else max(top_k, configured.candidate_limit)
        )
        timeout = request.timeout if request.timeout is not None else configured.timeout
        consistency = (
            request.consistency
            if request.consistency is not None
            else configured.consistency
        )
        return_fields = (
            request.return_fields if request.return_fields else configured.return_fields
        )
        threshold_kind = self._resolve_threshold_kind(request)
        _validate(
            top_k, min_score, candidate_limit, timeout, return_fields, threshold_kind,
            self._score_semantics,
        )
        return ResolvedVectorQuery(
            query=request.query,
            top_k=top_k,
            min_score=min_score,
            threshold_kind=threshold_kind,
            filter=request.filter,
            return_fields=return_fields,
            candidate_limit=candidate_limit,
            timeout=timeout,
            consistency=consistency,
            diversification=request.diversification,
            provider_options=request.provider_options,
        )

    def source_for(self, option: str, request_override: bool) -> VectorParameterSource:
        if request_override:
            return VectorParameterSource.REQUEST
        if _has_value(self._store_defaults, option):
            return VectorParameterSource.STORE_DEFAULT
        if _has_value(self._provider_defaults, option):
            return VectorParameterSource.PROVIDER_DEFAULT
        return VectorParameterSource.CORE_DEFAULT

    def _resolve_threshold_kind(
        self, request: VectorQueryRequest
    ) -> VectorScoreThresholdKind:
        if request.threshold_kind is not None:
            return request.threshold_kind
        if self._score_semantics is None:
            return VectorScoreThresholdKind.NORMALIZED_RELEVANCE
        descriptor = self._score_semantics.descriptor(VectorScoreStage.FINAL_SCORE)
        if descriptor is None:
            return VectorScoreThresholdKind.PROVIDER_RAW
        return descriptor.threshold_kind

    def _validate_defaults(self, defaults: VectorQueryDefaults) -> None:
        if (
            defaults.top_k is None
            or defaults.min_score is None
            or defaults.candidate_limit is None
            or defaults.timeout is None
            or defaults.consistency is None
        ):
            raise VectorQueryValidationException(
                VectorQueryErrorCode.INVALID_VALUE,
                "resolved query defaults must be complete",
            )
        _validate(
            defaults.top_k,
            defaults.min_score,
            max(defaults.top_k, defaults.candidate_limit),
            defaults.timeout,
            defaults.return_fields,
            defaults.threshold_kind or VectorScoreThresholdKind.NORMALIZED_RELEVANCE,
            self._score_semantics,
        )


def _has_value(defaults: VectorQueryDefaults | None, option: str) -> bool:
    if defaults is None:
        return False
    if option == "returnFields":
        return bool(defaults.return_fields)
    return getattr(defaults, _OPTION_ATTRS.get(option, ""), None) is not None


_OPTION_ATTRS = {
    "topK": "top_k",
    "minScore": "min_score",
    "candidateLimit": "candidate_limit",
    "timeout": "timeout",
    "consistency": "consistency",
}


def _validate(
    top_k: int,
    min_score: float,
    candidate_limit: int,
    timeout: timedelta | None,
    return_fields: frozenset[str],
    threshold_kind: VectorScoreThresholdKind,
    score_semantics: VectorScoreSemantics | None,
) -> None:
    if (
        top_k < 1
        or candidate_limit < top_k
        or min_score < 0.0
        or timeout is None
        or timeout <= timedelta(0)
    ):
        raise VectorQueryValidationException(
            VectorQueryErrorCode.INVALID_VALUE,
            "advanced vector query contains an invalid value",
        )
    if (
        top_k > MAX_TOP_K
        or candidate_limit > MAX_CANDIDATES
        or timeout > MAX_TIMEOUT
        or len(return_fields) > MAX_RETURN_FIELDS
    ):
        raise VectorQueryValidationException(
            VectorQueryErrorCode.LIMIT_EXCEEDED,
            "advanced vector query exceeds a safety limit",
        )
    if any(
        not isinstance(f, str) or not _FIELD.fullmatch(f) for f in return_fields
    ):
        raise VectorQueryValidationException(
            VectorQueryErrorCode.INVALID_VALUE,
            "advanced vector query contains an invalid return field",
        )
    _validate_threshold(min_score, threshold_kind, score_semantics)


def _validate_threshold(
    min_score: float,
    threshold_kind: VectorScoreThresholdKind,
    score_semantics: VectorScoreSemantics | None,
) -> None:
    if threshold_kind is VectorScoreThresholdKind.NORMALIZED_RELEVANCE:
        if min_score > 1.0:
            raise VectorQueryValidationException(
                VectorQueryErrorCode.INVALID_VALUE,
                "NORMALIZED_RELEVANCE minScore must be within [0, 1]",
            )
        return
    if score_semantics is None:
        return
    descriptor: VectorScoreDescriptor | None = score_semantics.descriptor(
        VectorScoreStage.FINAL_SCORE
    )
    if descriptor is None:
        return
    if descriptor.maximum is not None and min_score > descriptor.maximum:
        raise VectorQueryValidationException(
            VectorQueryErrorCode.INVALID_VALUE,
            f"PROVIDER_RAW minScore exceeds Store declared maximum {descriptor.maximum}",
        )
    if descriptor.minimum is not None and min_score < descriptor.minimum:
        raise VectorQueryValidationException(
            VectorQueryErrorCode.INVALID_VALUE,
            f"PROVIDER_RAW minScore is below Store declared minimum {descriptor.minimum}",
        )


@dataclass(frozen=True, slots=True)
class VectorSearchExecutionReceipt:
    store_id: Any
    provider: str
    contract_version: str
    adapter_version: str
    capability_version: str
    provider_extension_version: str
    logical_index_fingerprint: str
    parameters: tuple[VectorParameterEvidence, ...] = ()

    def __post_init__(self) -> None:
        if self.store_id is None or not self.provider:
            raise ValueError("storeId and provider must not be None")
        for name in (
            "contract_version",
            "adapter_version",
            "capability_version",
            "provider_extension_version",
            "logical_index_fingerprint",
        ):
            value = getattr(self, name)
            if not value or not str(value).strip():
                raise ValueError(f"{name} must not be blank")
        object.__setattr__(self, "parameters", tuple(self.parameters or ()))


@dataclass(frozen=True, slots=True)
class VectorSearchExecution:
    results: tuple[Any, ...]
    receipt: VectorSearchExecutionReceipt

    def __post_init__(self) -> None:
        if self.receipt is None:
            raise ValueError("receipt must not be None")
        object.__setattr__(self, "results", tuple(self.results or ()))


__all__ = [
    "MAX_TOP_K",
    "MAX_CANDIDATES",
    "MAX_RETURN_FIELDS",
    "MAX_TIMEOUT",
    "VectorConsistencyPreference",
    "VectorParameterSource",
    "VectorParameterDisposition",
    "VectorQueryErrorCode",
    "VectorQueryValidationException",
    "ProviderQueryOptions",
    "VectorDiversificationOptions",
    "DISABLED_DIVERSIFICATION",
    "VectorQueryDefaults",
    "CORE_SAFE_DEFAULTS",
    "VectorQueryRequest",
    "ResolvedVectorQuery",
    "VectorParameterEvidence",
    "VectorQueryResolver",
    "VectorSearchExecutionReceipt",
    "VectorSearchExecution",
]