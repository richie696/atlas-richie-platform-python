"""Deployment allowlist and DNS pin facts for bootstrap database checks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
import ipaddress
import re
import socket
from typing import TypeAlias

from ..application.bootstrap_database_check import BootstrapDatabaseKind

IPAddress: TypeAlias = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork: TypeAlias = ipaddress.IPv4Network | ipaddress.IPv6Network
AddressInfo: TypeAlias = tuple[int, int, int, str, tuple[object, ...]]
AddressResolver: TypeAlias = Callable[
    [str, int], Awaitable[Sequence[AddressInfo]]
]
_MIN_PORT = 1
_MAX_PORT = 65535
_MAX_HOST_LENGTH = 253
_MAX_LABEL_LENGTH = 63
_MAX_RESOLVED_ADDRESSES = 8
_DNS_RESOLUTION_TIMEOUT_SECONDS = 2.0
_DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


class BootstrapDatabaseTargetRejected(ValueError):
    """The requested host or resolved address is outside deployment policy."""


@dataclass(frozen=True, slots=True)
class BootstrapDatabaseTargetRule:
    """One explicit database-kind, destination-network and port grant."""

    kind: BootstrapDatabaseKind
    network: IPNetwork
    ports: frozenset[int]

    def __post_init__(self) -> None:
        normalized_ports = frozenset(self.ports)
        object.__setattr__(self, "ports", normalized_ports)
        if self.network.prefixlen == 0:
            raise ValueError("database target networks must not grant all addresses")
        if not self.ports or any(
            type(port) is not int or not _MIN_PORT <= port <= _MAX_PORT
            for port in self.ports
        ):
            raise ValueError("database target rules require valid explicit ports")

    @classmethod
    def create(
        cls,
        kind: BootstrapDatabaseKind,
        network: str,
        ports: frozenset[int],
    ) -> BootstrapDatabaseTargetRule:
        """Build a rule from deployment-owned CIDR and port configuration."""
        try:
            parsed_network = ipaddress.ip_network(network, strict=True)
        except ValueError as error:
            raise ValueError("database target CIDR is invalid") from error
        return cls(kind=kind, network=parsed_network, ports=ports)


@dataclass(frozen=True, slots=True)
class ResolvedBootstrapDatabaseTarget:
    """Immutable addresses that have passed policy and can be pinned."""

    hostname: str
    port: int
    addresses: tuple[IPAddress, ...]

    def __post_init__(self) -> None:
        normalized_addresses = tuple(self.addresses)
        object.__setattr__(self, "addresses", normalized_addresses)
        if not self.hostname or not self.addresses:
            raise ValueError("resolved database target is incomplete")
        if type(self.port) is not int or not _MIN_PORT <= self.port <= _MAX_PORT:
            raise ValueError("resolved database target port is invalid")
        if len(set(self.addresses)) != len(self.addresses):
            raise ValueError("resolved database target addresses must be unique")


class BootstrapDatabaseTargetPolicy:
    """Resolve once, require every answer to be allowlisted, and pin the set."""

    def __init__(
        self,
        rules: Sequence[BootstrapDatabaseTargetRule],
        resolver: AddressResolver | None = None,
    ) -> None:
        normalized_rules = tuple(rules)
        if not normalized_rules:
            raise ValueError("at least one database target rule is required")
        self._rules = normalized_rules
        self._resolver = resolver

    async def resolve(
        self,
        kind: BootstrapDatabaseKind,
        host: str,
        port: int,
    ) -> ResolvedBootstrapDatabaseTarget:
        """Return only addresses that all match an explicit deployment rule."""
        literal_address = _parse_ip_literal(host)
        normalized_host = (
            literal_address.compressed
            if literal_address is not None
            else _normalize_host(host)
        )
        if type(port) is not int or not _MIN_PORT <= port <= _MAX_PORT:
            raise BootstrapDatabaseTargetRejected
        if not any(
            rule.kind is kind and port in rule.ports for rule in self._rules
        ):
            # This keeps the port/kind check independent of DNS resolution.
            raise BootstrapDatabaseTargetRejected

        if literal_address is not None:
            resolved_addresses = (literal_address,)
        else:
            resolved_addresses = await self._resolve_hostname(normalized_host, port)

        if not resolved_addresses or any(
            address.is_link_local
            or address.is_unspecified
            or address.is_multicast
            or not self._allows(kind, port, address)
            for address in resolved_addresses
        ):
            raise BootstrapDatabaseTargetRejected

        return ResolvedBootstrapDatabaseTarget(
            hostname=normalized_host,
            port=port,
            addresses=resolved_addresses,
        )

    async def _resolve_hostname(
        self, hostname: str, port: int
    ) -> tuple[IPAddress, ...]:
        resolver = self._resolver or _system_resolver
        try:
            async with asyncio.timeout(_DNS_RESOLUTION_TIMEOUT_SECONDS):
                records = await resolver(hostname, port)
        except (OSError, asyncio.TimeoutError) as error:
            raise BootstrapDatabaseTargetRejected from error

        addresses: list[IPAddress] = []
        for family, *_rest, sockaddr in records:
            if family not in {socket.AF_INET, socket.AF_INET6} or not sockaddr:
                continue
            address_text = sockaddr[0]
            try:
                rendered_address = str(address_text)
                if "%" in rendered_address:
                    continue
                address = ipaddress.ip_address(rendered_address)
            except ValueError:
                continue
            if address not in addresses:
                addresses.append(address)
                if len(addresses) > _MAX_RESOLVED_ADDRESSES:
                    raise BootstrapDatabaseTargetRejected
        return tuple(addresses)

    def _allows(
        self,
        kind: BootstrapDatabaseKind,
        port: int,
        address: IPAddress | None,
    ) -> bool:
        return any(
            rule.kind is kind
            and port in rule.ports
            and (address is None or address in rule.network)
            for rule in self._rules
        )


async def _system_resolver(hostname: str, port: int) -> Sequence[AddressInfo]:
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(
        hostname,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )


def _normalize_host(host: str) -> str:
    if not isinstance(host, str) or not host or host != host.strip():
        raise BootstrapDatabaseTargetRejected
    if any(character in host for character in ("/", "\\", "@", "?", "#", "%")):
        raise BootstrapDatabaseTargetRejected

    candidate = host[:-1] if host.endswith(".") else host
    if not candidate or ".." in candidate:
        raise BootstrapDatabaseTargetRejected
    try:
        ascii_host = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise BootstrapDatabaseTargetRejected from error
    if len(ascii_host) > _MAX_HOST_LENGTH:
        raise BootstrapDatabaseTargetRejected
    labels = ascii_host.split(".")
    if any(not label or len(label) > _MAX_LABEL_LENGTH for label in labels):
        raise BootstrapDatabaseTargetRejected
    if any(not _DNS_LABEL_PATTERN.fullmatch(label) for label in labels):
        raise BootstrapDatabaseTargetRejected
    return ascii_host


def _parse_ip_literal(host: str) -> IPAddress | None:
    if not isinstance(host, str) or "%" in host:
        return None
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None
