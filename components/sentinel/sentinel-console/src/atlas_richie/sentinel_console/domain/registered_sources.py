"""Safe, validated facts for the Console's registered configuration sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .configuration_source import ConfigurationSourceProvider
from .source_endpoint import is_safe_source_endpoint
from .wire_strings import (
    is_bounded_wire_identifier,
    is_bounded_wire_text,
    utf16_length,
)

_MAX_IDENTIFIER_UNITS = 200
_MAX_TEXT_UNITS = 200
_MAX_REGISTERED_SOURCES = 500
_MIN_SUPPORTED_UTC_YEAR = 1970


class SourceAuthenticationMode(StrEnum):
    """Safe authentication classification; secret and reference values are absent."""

    NONE = "none"
    CREDENTIAL_REFERENCE = "credential-reference"
    DIRECT = "direct"


def _utf16_length(value: str) -> int:
    return utf16_length(value)


def _valid_identifier(value: str) -> bool:
    return (
        is_bounded_wire_identifier(value, _MAX_IDENTIFIER_UNITS)
    )


def _valid_text(value: str) -> bool:
    return is_bounded_wire_text(value, _MAX_TEXT_UNITS)


def _valid_endpoint(value: str) -> bool:
    return is_safe_source_endpoint(value)


def _valid_instant(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and _MIN_SUPPORTED_UTC_YEAR <= value.year <= 9999
    )


@dataclass(frozen=True, slots=True)
class RegisteredConfigurationSource:
    """One read-only source identity, with provider-specific location normalized."""

    id: str
    revision: str
    name: str
    endpoint: str
    provider: ConfigurationSourceProvider
    location: str
    authentication_mode: SourceAuthenticationMode
    credential_configured: bool

    def __post_init__(self) -> None:
        if not _valid_identifier(self.id) or not _valid_identifier(self.revision):
            raise ValueError("registered source identity or revision is invalid")
        if not _valid_identifier(self.name):
            raise ValueError("registered source name is invalid")
        if not _valid_endpoint(self.endpoint):
            raise ValueError("registered source endpoint is invalid")
        if not isinstance(self.provider, ConfigurationSourceProvider):
            raise ValueError("registered source provider is unsupported")
        if not _valid_text(self.location):
            raise ValueError("registered source location is invalid")
        if not isinstance(self.authentication_mode, SourceAuthenticationMode):
            raise ValueError("registered source authentication mode is unsupported")
        if not isinstance(self.credential_configured, bool):
            raise ValueError("registered source credential state must be boolean")
        if (
            self.authentication_mode is SourceAuthenticationMode.NONE
            and self.credential_configured
        ):
            raise ValueError(
                "unauthenticated source cannot have configured credentials"
            )


@dataclass(frozen=True, slots=True)
class RegisteredSourcesSnapshot:
    """One bounded registry read; it never carries credential or reference values."""

    as_of: datetime
    items: tuple[RegisteredConfigurationSource, ...]

    def __post_init__(self) -> None:
        if not _valid_instant(self.as_of):
            raise ValueError("registered source snapshot time must be aware")
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > _MAX_REGISTERED_SOURCES
            or any(
                not isinstance(item, RegisteredConfigurationSource)
                for item in self.items
            )
        ):
            raise ValueError("registered source snapshot must be a bounded tuple")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("registered source identities must be unique")
