"""Deployment-owned allowlist and DNS pinning for monitoring backends."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
type IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
type AddressInfo = tuple[int, int, int, str, tuple[object, ...]]
type AddressResolver = Callable[[str, int], Awaitable[Sequence[AddressInfo]]]
_MAX_HOST_LENGTH = 253
_MAX_DNS_ANSWERS = 8


class MonitoringTargetRejected(ValueError):
    """A monitoring endpoint is not allowed by deployment network policy."""


@dataclass(frozen=True, slots=True)
class MonitoringTargetRule:
    """One exact hostname, network and port grant owned by deployment config."""

    hostname: str
    networks: tuple[IPNetwork, ...]
    ports: frozenset[int]
    allow_private_http: bool = False
    allow_loopback_http: bool = False

    def __post_init__(self) -> None:
        networks = tuple(self.networks)
        ports = frozenset(self.ports)
        object.__setattr__(self, "hostname", _normalize_hostname(self.hostname))
        object.__setattr__(self, "networks", networks)
        object.__setattr__(self, "ports", ports)
        if not self.hostname or len(self.hostname) > _MAX_HOST_LENGTH:
            raise ValueError("monitoring target hostname is invalid")
        if not networks or any(network.prefixlen == 0 for network in networks):
            raise ValueError("monitoring target networks must be explicit")
        if not ports or any(
            type(port) is not int or not 1 <= port <= 65535 for port in ports
        ):
            raise ValueError("monitoring target ports must be explicit")
        if (
            type(self.allow_private_http) is not bool
            or type(self.allow_loopback_http) is not bool
        ):
            raise TypeError("monitoring HTTP policy flags must be boolean")
        if self.allow_private_http and any(
            not network.is_private for network in networks
        ):
            raise ValueError("plain HTTP allowlist must contain only private networks")
        if self.allow_loopback_http and any(
            not network.is_loopback for network in networks
        ):
            raise ValueError(
                "loopback HTTP allowlist must contain only loopback networks"
            )

    @classmethod
    def create(
        cls,
        hostname: str,
        networks: Sequence[str],
        ports: frozenset[int],
        *,
        allow_private_http: bool = False,
        allow_loopback_http: bool = False,
    ) -> MonitoringTargetRule:
        """Parse deployment-owned CIDRs without broad catch-all grants."""
        try:
            parsed_networks = tuple(
                ipaddress.ip_network(value, strict=True) for value in networks
            )
        except ValueError as error:
            raise ValueError("monitoring target network is invalid") from error
        return cls(
            hostname=hostname,
            networks=parsed_networks,
            ports=ports,
            allow_private_http=allow_private_http,
            allow_loopback_http=allow_loopback_http,
        )


@dataclass(frozen=True, slots=True)
class PinnedMonitoringTarget:
    """Validated destination facts used for one request without DNS relookup."""

    hostname: str
    port: int
    addresses: tuple[IPAddress, ...]
    secure: bool

    def __post_init__(self) -> None:
        if not self.hostname or not self.addresses:
            raise ValueError("pinned monitoring target is incomplete")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("pinned monitoring target port is invalid")
        if len(set(self.addresses)) != len(self.addresses):
            raise ValueError("pinned monitoring target addresses must be unique")


class MonitoringTargetPolicy:
    """Resolve a configured endpoint once and require every answer allowlisted."""

    def __init__(
        self,
        rules: Sequence[MonitoringTargetRule],
        resolver: AddressResolver | None = None,
    ) -> None:
        self._rules = tuple(rules)
        self._resolver = resolver
        if not self._rules:
            raise ValueError("monitoring target rules are required")

    async def resolve(
        self, endpoint: str, *, authenticated: bool
    ) -> PinnedMonitoringTarget:
        """Validate origin/path policy, resolve DNS, and pin an allowed address set."""
        if type(authenticated) is not bool:
            raise TypeError("monitoring authentication state must be boolean")
        try:
            parsed = urlsplit(endpoint)
            parsed_port = parsed.port
            port = (
                (443 if parsed.scheme.lower() == "https" else 80)
                if parsed_port is None
                else parsed_port
            )
            hostname = _normalize_hostname(parsed.hostname or "")
            decoded_path = unquote(parsed.path)
        except (UnicodeError, ValueError) as error:
            raise MonitoringTargetRejected from error
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "\\" in decoded_path
            or any(segment in {".", ".."} for segment in decoded_path.split("/"))
            or type(port) is not int
            or not 1 <= port <= 65535
        ):
            raise MonitoringTargetRejected
        matching = tuple(
            rule
            for rule in self._rules
            if rule.hostname == hostname and port in rule.ports
        )
        if not matching:
            raise MonitoringTargetRejected
        secure = parsed.scheme.lower() == "https"
        if authenticated and not secure:
            raise MonitoringTargetRejected
        if not secure and not any(
            rule.allow_private_http or rule.allow_loopback_http for rule in matching
        ):
            raise MonitoringTargetRejected

        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            addresses = await self._resolve_hostname(hostname, port)
        else:
            addresses = (literal,)
        if not addresses:
            raise MonitoringTargetRejected
        for address in addresses:
            if (
                address.is_unspecified
                or address.is_multicast
                or address.is_link_local
                or address.is_reserved
            ):
                raise MonitoringTargetRejected
            if address.is_loopback and not (
                not secure and any(rule.allow_loopback_http for rule in matching)
            ):
                raise MonitoringTargetRejected
            if not any(
                address in network for rule in matching for network in rule.networks
            ):
                raise MonitoringTargetRejected
            if (
                not secure
                and not address.is_loopback
                and not (
                    address.is_private
                    and any(rule.allow_private_http for rule in matching)
                )
            ):
                raise MonitoringTargetRejected
        return PinnedMonitoringTarget(hostname, port, addresses, secure)

    async def _resolve_hostname(
        self, hostname: str, port: int
    ) -> tuple[IPAddress, ...]:
        resolver = self._resolver or _system_resolver
        try:
            async with asyncio.timeout(2.0):
                records = await resolver(hostname, port)
        except (OSError, TimeoutError) as error:
            raise MonitoringTargetRejected from error
        addresses: list[IPAddress] = []
        for family, _kind, _protocol, _canonical, sockaddr in records:
            if family not in {socket.AF_INET, socket.AF_INET6} or not sockaddr:
                continue
            try:
                address = ipaddress.ip_address(str(sockaddr[0]))
            except ValueError:
                continue
            if address not in addresses:
                addresses.append(address)
                if len(addresses) > _MAX_DNS_ANSWERS:
                    raise MonitoringTargetRejected
        return tuple(addresses)


async def _system_resolver(hostname: str, port: int) -> Sequence[AddressInfo]:
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(
        hostname,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )


def _normalize_hostname(value: str) -> str:
    candidate = value.rstrip(".").lower()
    if not candidate or len(candidate) > _MAX_HOST_LENGTH:
        return ""
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        try:
            ascii_value = candidate.encode("idna").decode("ascii")
        except UnicodeError:
            return ""
        labels = ascii_value.split(".")
        if any(
            not label
            or len(label) > 63
            or not label[0].isalnum()
            or not label[-1].isalnum()
            or any(not (character.isalnum() or character == "-") for character in label)
            for label in labels
        ):
            return ""
        return ascii_value


__all__ = [
    "MonitoringTargetPolicy",
    "MonitoringTargetRejected",
    "MonitoringTargetRule",
    "PinnedMonitoringTarget",
]
