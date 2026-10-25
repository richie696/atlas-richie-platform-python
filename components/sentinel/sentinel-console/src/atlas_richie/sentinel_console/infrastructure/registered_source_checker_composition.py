"""Explicit assembly for production registered-source HTTP probes."""

from __future__ import annotations

import ssl
from collections.abc import Sequence

from ..application.check_registered_source import RegisteredSourceChecker
from .registered_source_checker import (
    AddressResolver,
    ConsulRegisteredSourceChecker,
    NacosRegisteredSourceChecker,
    PinnedAioHttpJsonClient,
    ProviderRegisteredSourceChecker,
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)


def compose_provider_registered_source_checker(
    rules: Sequence[RegisteredSourceTargetRule],
    *,
    ssl_context: ssl.SSLContext | None = None,
    resolver: AddressResolver | None = None,
) -> RegisteredSourceChecker:
    """Build a checker with deployment-owned targets and optional verified CA trust."""
    policy = RegisteredSourceTargetPolicy(rules, resolver)
    client = PinnedAioHttpJsonClient(ssl_context=ssl_context)
    return ProviderRegisteredSourceChecker(
        nacos=NacosRegisteredSourceChecker(policy, client.request),
        consul=ConsulRegisteredSourceChecker(policy, client.request),
    )
