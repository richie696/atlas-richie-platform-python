"""Shared provider identity for server-owned configuration-source facts."""

from __future__ import annotations

from enum import StrEnum


class ConfigurationSourceProvider(StrEnum):
    """Configuration-center providers supported by the Console contract."""

    NACOS = "nacos"
    CONSUL = "consul"

