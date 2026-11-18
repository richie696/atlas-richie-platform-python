"""URL fetch policy: SSRF guard rails for downloading remote documents.

Ported from `UrlFetchPolicy` (Java). Defaults deny plain HTTP and private IPs,
cap the download at 200 MB, and use 5s connect / 60s read timeouts.

Deviation: Java's `CidrBlock.contains` is a Phase-1 placeholder that always
returns False, so an explicitly configured allowlist silently never matches.
This implements real IPv4/IPv6 CIDR matching with the standard library.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

DEFAULT_MAX_BYTES = 200 * 1024 * 1024
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 60.0


@dataclass(frozen=True, slots=True)
class CidrBlock:
    """An explicit opt-in allowlist entry."""

    cidr: str
    _network: ipaddress.IPv4Network | ipaddress.IPv6Network | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.cidr or not self.cidr.strip():
            raise ValueError("cidr must not be blank")
        try:
            network = ipaddress.ip_network(self.cidr, strict=False)
        except ValueError as error:
            raise ValueError(f"invalid CIDR: {self.cidr}") from error
        object.__setattr__(self, "_network", network)

    def contains(self, address: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        if self._network is None:
            return False
        try:
            parsed = ipaddress.ip_address(address) if isinstance(address, str) else address
        except ValueError:
            return False
        return parsed.version == self._network.version and parsed in self._network


@dataclass(frozen=True, slots=True)
class UrlFetchPolicy:
    allow_http: bool = False
    allow_private_ip: bool = False
    follow_redirects: bool = True
    max_bytes: int = DEFAULT_MAX_BYTES
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    read_timeout: float = DEFAULT_READ_TIMEOUT
    allowlist: tuple[CidrBlock, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.max_bytes <= 0:
            object.__setattr__(self, "max_bytes", DEFAULT_MAX_BYTES)
        if self.connect_timeout <= 0:
            object.__setattr__(self, "connect_timeout", DEFAULT_CONNECT_TIMEOUT)
        if self.read_timeout <= 0:
            object.__setattr__(self, "read_timeout", DEFAULT_READ_TIMEOUT)
        object.__setattr__(self, "allowlist", tuple(self.allowlist or ()))

    @classmethod
    def defaults(cls) -> UrlFetchPolicy:
        return cls()

    def is_private_address(self, address: str) -> bool:
        """Private, loopback, link-local, reserved or otherwise non-global address."""
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return True  # unparseable hosts are treated as unsafe
        return (
            parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_reserved
            or parsed.is_multicast
            or parsed.is_unspecified
        )

    def permits(self, scheme: str, host_address: str) -> bool:
        """Whether a fetch to this scheme/host is allowed under the policy.

        An allowlist entry is an explicit opt-in and overrides the private-IP
        denial, but never the plain-HTTP denial.
        """
        if scheme.lower() not in ("http", "https"):
            return False
        if scheme.lower() == "http" and not self.allow_http:
            return False
        if any(block.contains(host_address) for block in self.allowlist):
            return True
        if self.is_private_address(host_address) and not self.allow_private_ip:
            return False
        return True


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_READ_TIMEOUT",
    "CidrBlock",
    "UrlFetchPolicy",
]
