"""Typed, secret-free facts for Prometheus-compatible monitoring sources."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .source_endpoint import is_safe_source_endpoint
from .wire_strings import is_bounded_wire_identifier, is_bounded_wire_text

MAX_MONITORING_SOURCES = 500
MAX_IDENTITY_LABELS = 10
MAX_SELECTOR_LABELS = 20
MAX_LABEL_NAME_LENGTH = 128
MAX_LABEL_VALUE_LENGTH = 256
MIN_SCRAPE_INTERVAL_SECONDS = 1
MAX_SCRAPE_INTERVAL_SECONDS = 300
MAX_STALE_AFTER_SECONDS = 3600
_LABEL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class MonitoringProvider(StrEnum):
    """Finite query-backend choices supported by this Console release."""

    PROMETHEUS_COMPATIBLE = "prometheus-compatible"


class MonitoringProfile(StrEnum):
    """Finite, unit-bearing profiles; never accept a caller-defined query."""

    NODE_EXPORTER_V1 = "node-exporter-v1"


class MonitoringAuthenticationMode(StrEnum):
    """Safe authentication classification with no credential material."""

    NONE = "none"
    DIRECT_BASIC = "direct-basic"
    DIRECT_BEARER = "direct-bearer"
    CREDENTIAL_REFERENCE = "credential-reference"


@dataclass(frozen=True, slots=True)
class MonitoringLabel:
    """One exact Prometheus label selector, not a PromQL expression."""

    name: str
    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or len(self.name) > MAX_LABEL_NAME_LENGTH
            or self.name.startswith("__")
            or _LABEL_NAME.fullmatch(self.name) is None
        ):
            raise ValueError("monitoring label name is invalid")
        if not is_bounded_wire_text(self.value, MAX_LABEL_VALUE_LENGTH):
            raise ValueError("monitoring label value is invalid")


@dataclass(frozen=True, slots=True)
class MonitoringSource:
    """Persistable source metadata; credentials are represented only by flags."""

    source_id: str
    revision: str
    display_name: str
    environment_id: str
    endpoint: str
    provider: MonitoringProvider
    profile: MonitoringProfile
    authentication_mode: MonitoringAuthenticationMode
    credential_configured: bool
    enabled: bool
    identity_labels: tuple[str, ...]
    selector_labels: tuple[MonitoringLabel, ...]
    scrape_interval_seconds: int
    stale_after_seconds: int

    def __post_init__(self) -> None:
        if not is_bounded_wire_identifier(self.source_id, 200):
            raise ValueError("monitoring source id is invalid")
        if not is_bounded_wire_identifier(self.revision, 200):
            raise ValueError("monitoring source revision is invalid")
        if not is_bounded_wire_text(self.display_name, 200):
            raise ValueError("monitoring source display name is invalid")
        if not is_bounded_wire_identifier(self.environment_id, 200):
            raise ValueError("monitoring source environment is invalid")
        if not is_safe_source_endpoint(self.endpoint):
            raise ValueError("monitoring source endpoint is invalid")
        if not isinstance(self.provider, MonitoringProvider):
            raise TypeError("monitoring source provider is unsupported")
        if not isinstance(self.profile, MonitoringProfile):
            raise TypeError("monitoring source profile is unsupported")
        if not isinstance(self.authentication_mode, MonitoringAuthenticationMode):
            raise TypeError("monitoring authentication mode is unsupported")
        if (
            type(self.credential_configured) is not bool
            or type(self.enabled) is not bool
        ):
            raise ValueError("monitoring source flags must be boolean")
        if (
            self.authentication_mode is MonitoringAuthenticationMode.NONE
            and self.credential_configured
        ):
            raise ValueError(
                "unauthenticated monitoring source cannot have credentials"
            )
        if (
            self.authentication_mode is not MonitoringAuthenticationMode.NONE
            and not self.credential_configured
        ):
            raise ValueError(
                "authenticated monitoring source requires configured credentials"
            )
        if (
            not isinstance(self.identity_labels, tuple)
            or not 1 <= len(self.identity_labels) <= MAX_IDENTITY_LABELS
        ):
            raise ValueError("monitoring identity labels are invalid")
        if len(set(self.identity_labels)) != len(self.identity_labels) or any(
            not _valid_label_name(value) for value in self.identity_labels
        ):
            raise ValueError("monitoring identity labels must be unique label names")
        if (
            not isinstance(self.selector_labels, tuple)
            or len(self.selector_labels) > MAX_SELECTOR_LABELS
        ):
            raise ValueError("monitoring selector labels are invalid")
        if any(not isinstance(item, MonitoringLabel) for item in self.selector_labels):
            raise ValueError("monitoring selectors must be exact labels")
        names = tuple(item.name for item in self.selector_labels)
        if len(set(names)) != len(names):
            raise ValueError("monitoring selector labels must be unique")
        if (
            type(self.scrape_interval_seconds) is not int
            or not MIN_SCRAPE_INTERVAL_SECONDS
            <= self.scrape_interval_seconds
            <= MAX_SCRAPE_INTERVAL_SECONDS
        ):
            raise ValueError("monitoring scrape interval is invalid")
        if (
            type(self.stale_after_seconds) is not int
            or self.stale_after_seconds <= self.scrape_interval_seconds
            or self.stale_after_seconds > MAX_STALE_AFTER_SECONDS
        ):
            raise ValueError("monitoring stale threshold is invalid")


@dataclass(frozen=True, slots=True)
class MonitoringSourcesSnapshot:
    """One bounded, safe read of the independent monitoring-source registry."""

    as_of: datetime
    items: tuple[MonitoringSource, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.as_of, datetime)
            or self.as_of.tzinfo is None
            or self.as_of.utcoffset() is None
        ):
            raise ValueError("monitoring source snapshot time must be aware")
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > MAX_MONITORING_SOURCES
            or any(not isinstance(item, MonitoringSource) for item in self.items)
        ):
            raise ValueError("monitoring source snapshot must be bounded")
        if len({item.source_id for item in self.items}) != len(self.items):
            raise ValueError("monitoring source ids must be unique")


def _valid_label_name(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= MAX_LABEL_NAME_LENGTH
        and not value.startswith("__")
        and _LABEL_NAME.fullmatch(value) is not None
    )


__all__ = [
    "MAX_IDENTITY_LABELS",
    "MAX_LABEL_NAME_LENGTH",
    "MAX_LABEL_VALUE_LENGTH",
    "MAX_MONITORING_SOURCES",
    "MAX_SCRAPE_INTERVAL_SECONDS",
    "MAX_SELECTOR_LABELS",
    "MAX_STALE_AFTER_SECONDS",
    "MIN_SCRAPE_INTERVAL_SECONDS",
    "MonitoringAuthenticationMode",
    "MonitoringLabel",
    "MonitoringProfile",
    "MonitoringProvider",
    "MonitoringSource",
    "MonitoringSourcesSnapshot",
]
