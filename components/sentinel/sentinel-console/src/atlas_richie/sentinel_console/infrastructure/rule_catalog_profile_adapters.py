"""Strictly translate supported native rule profiles into catalog values."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Protocol

from ..application.rule_value_codec import parse_rule_value
from ..domain.rule_bindings import RuleKind
from ..domain.rule_snapshots import (
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
    RuleValue,
)

_MAX_RULES = 1_000
_MAX_RESOURCE_BYTES = 200
_MAX_THRESHOLD = Decimal(1_000_000_000)
_RAW_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_NORMALIZED_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?$")


class UnsupportedRuleCatalogCapability(ValueError):
    """The profile is known but does not model this rule-family capability."""


class RuleCatalogProfileAdapter(Protocol):
    """Translate one profile's native JSON rule value into Console semantics."""

    def parse(self, kind: RuleKind, value: object) -> RuleValue:
        """Return one typed rule or reject the unsupported semantic shape."""


class SentinelPythonCatalogAdapter:
    """Use the existing strict native codec for the Python profile."""

    def parse(self, kind: RuleKind, value: object) -> RuleValue:
        return parse_rule_value(kind, value)


class SentinelJavaCatalogAdapter:
    """Map the explicitly supported Sentinel Java FlowRule V1 subset."""

    def parse(self, kind: RuleKind, value: object) -> RuleValue:
        if kind is not RuleKind.FLOW:
            raise UnsupportedRuleCatalogCapability
        data = _object(
            value,
            required={"resource", "grade", "count"},
            optional={
                "strategy",
                "controlBehavior",
                "limitApp",
                "warmUpPeriodSec",
                "maxQueueingTimeMs",
                "clusterMode",
                "refResource",
            },
        )
        if (
            _integer(data, "grade") != 1
            or _integer(data, "strategy", default=0) != 0
            or _integer(data, "controlBehavior", default=0) != 0
            or _integer(data, "warmUpPeriodSec", default=0) != 0
            or _integer(data, "maxQueueingTimeMs", default=0) != 0
            or _boolean(data, "clusterMode", default=False) is not False
            or _optional_text(data, "limitApp", "default") != "default"
            or _optional_text(data, "refResource", "") != ""
        ):
            raise ValueError("rule is outside sentinel-java-v1 flow semantics")
        return _flow_value(data["resource"], data["count"])


class SentinelGoCatalogAdapter:
    """Map the explicitly supported Sentinel Go FlowRule V1 subset."""

    def parse(self, kind: RuleKind, value: object) -> RuleValue:
        if kind is not RuleKind.FLOW:
            raise UnsupportedRuleCatalogCapability
        data = _object(
            value,
            required={"resource", "threshold", "statIntervalInMs"},
            optional={
                "tokenCalculateStrategy",
                "controlBehavior",
                "relationStrategy",
                "refResource",
            },
        )
        if (
            _integer(data, "statIntervalInMs") != 1000
            or _integer(data, "tokenCalculateStrategy", default=0) != 0
            or _integer(data, "controlBehavior", default=0) != 0
            or _integer(data, "relationStrategy", default=0) != 0
            or _optional_text(data, "refResource", "") != ""
        ):
            raise ValueError("rule is outside sentinel-go-v1 flow semantics")
        return _flow_value(data["resource"], data["threshold"])


class SentinelRustCatalogAdapter:
    """Map the explicitly supported Sentinel Rust FlowRule V1 subset."""

    def parse(self, kind: RuleKind, value: object) -> RuleValue:
        if kind is not RuleKind.FLOW:
            raise UnsupportedRuleCatalogCapability
        common = {
            "strategy",
            "controlBehavior",
            "limitApp",
            "warmUpPeriodSec",
            "maxQueueingTimeMs",
            "clusterMode",
            "refResource",
        }
        data = _object(
            value,
            required={"resource"},
            optional=common
            | {
                "count",
                "grade",
                "threshold",
                "statIntervalInMs",
                "tokenCalculateStrategy",
                "relationStrategy",
            },
        )
        count_shape = "count" in data and "threshold" not in data
        threshold_shape = "threshold" in data and "count" not in data
        if count_shape:
            if (
                _integer(data, "grade", default=1) != 1
                or any(
                    key in data
                    for key in (
                        "statIntervalInMs",
                        "tokenCalculateStrategy",
                        "relationStrategy",
                    )
                )
            ):
                raise ValueError("rule is outside sentinel-rust-v1 flow semantics")
            threshold = data["count"]
        elif threshold_shape:
            if "grade" in data:
                raise ValueError("rule is outside sentinel-rust-v1 flow semantics")
            if (
                _integer(data, "statIntervalInMs", default=1_000) != 1_000
                or _integer(data, "tokenCalculateStrategy", default=0) != 0
                or _integer(data, "relationStrategy", default=0) != 0
            ):
                raise ValueError("rule is outside sentinel-rust-v1 flow semantics")
            threshold = data["threshold"]
        else:
            raise ValueError("rule is outside sentinel-rust-v1 flow semantics")

        if (
            _integer(data, "strategy", default=0) != 0
            or _integer(data, "controlBehavior", default=0) != 0
            or _integer(data, "warmUpPeriodSec", default=0) != 0
            or _integer(data, "maxQueueingTimeMs", default=0) != 0
            or _boolean(data, "clusterMode", default=False) is not False
            or _optional_text(data, "limitApp", "default") != "default"
            or _optional_text(data, "refResource", "") != ""
        ):
            raise ValueError("rule is outside sentinel-rust-v1 flow semantics")
        return _flow_value(data["resource"], threshold)


_ADAPTERS: dict[str, RuleCatalogProfileAdapter] = {
    "sentinel-python-v1": SentinelPythonCatalogAdapter(),
    "sentinel-java-v1": SentinelJavaCatalogAdapter(),
    "sentinel-go-v1": SentinelGoCatalogAdapter(),
    "sentinel-rust-v1": SentinelRustCatalogAdapter(),
}


def parse_rule_catalog_values(
    profile: str,
    kind: RuleKind,
    values: object,
) -> tuple[RuleValue, ...]:
    """Parse a complete bounded native array without partial acceptance."""
    adapter = _ADAPTERS.get(profile)
    if adapter is None:
        raise UnsupportedRuleCatalogCapability
    if not isinstance(values, list) or len(values) > _MAX_RULES:
        raise ValueError("rule configuration is not a bounded array")
    parsed = tuple(adapter.parse(kind, value) for value in values)
    if profile in {"sentinel-java-v1", "sentinel-go-v1", "sentinel-rust-v1"}:
        resources = tuple(
            rule.resource for rule in parsed if isinstance(rule, FlowRuleValue)
        )
        if len(resources) != len(parsed) or len(set(resources)) != len(resources):
            raise ValueError("cross-language flow snapshot has duplicate resources")
    return parsed


def _flow_value(resource: object, threshold: object) -> FlowRuleValue:
    if not isinstance(resource, str) or not resource or resource != resource.strip():
        raise ValueError("flow resource is invalid")
    try:
        resource_size = len(resource.encode("utf-8", errors="strict"))
    except UnicodeEncodeError:
        raise ValueError("flow resource is invalid") from None
    if resource_size > _MAX_RESOURCE_BYTES:
        raise ValueError("flow resource is invalid")

    decimal = _plain_decimal(threshold)
    normalized = decimal.normalize()
    if decimal <= 0 or decimal > _MAX_THRESHOLD:
        raise TypeError("flow threshold has an invalid type")
    normalized_text = format(normalized, "f")
    if not _NORMALIZED_DECIMAL.fullmatch(normalized_text):
        raise ValueError("flow threshold precision is unsupported")
    numeric: int | float = (
        int(normalized)
        if normalized == normalized.to_integral_value()
        else float(normalized)
    )
    return FlowRuleValue(
        resource=resource,
        limit_app="default",
        grade=FlowGrade.QPS,
        count=numeric,
        strategy=FlowStrategy.DIRECT,
        control_behavior=FlowControlBehavior.REJECT,
        cluster_mode=False,
    )


def _plain_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise TypeError("flow threshold has an invalid type")
    raw = str(value)
    if not _RAW_DECIMAL.fullmatch(raw):
        raise ValueError("flow threshold must use plain decimal notation")
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError("flow threshold is invalid") from None


def _object(
    value: object,
    *,
    required: set[str],
    optional: set[str],
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("rule value must be an object")
    if not required.issubset(value) or not set(value).issubset(required | optional):
        raise ValueError("rule value fields do not match the profile contract")
    return value


def _integer(data: dict[str, object], key: str, *, default: int | None = None) -> int:
    value = data.get(key, default)
    if type(value) is not int:
        raise ValueError("rule integer field is invalid")
    return value


def _boolean(data: dict[str, object], key: str, *, default: bool | None = None) -> bool:
    value = data.get(key, default)
    if type(value) is not bool:
        raise ValueError("rule boolean field is invalid")
    return value


def _optional_text(data: dict[str, object], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise TypeError("rule text field is invalid")
    return value


__all__ = [
    "RuleCatalogProfileAdapter",
    "SentinelGoCatalogAdapter",
    "SentinelJavaCatalogAdapter",
    "SentinelPythonCatalogAdapter",
    "SentinelRustCatalogAdapter",
    "UnsupportedRuleCatalogCapability",
    "parse_rule_catalog_values",
]
