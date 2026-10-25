"""Resolve a login client's address without trusting arbitrary proxy headers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import ipaddress

from starlette.requests import Request

_FORWARDED_FOR_HEADER = "x-forwarded-for"

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True, slots=True)
class ClientAddressResolver:
    """Use X-Forwarded-For only when the immediate peer is explicitly trusted.

    Proxies must append each observed peer to the right of the existing
    ``X-Forwarded-For`` chain. Invalid chains fall back to the immediate peer,
    which is safe but may cause users behind one proxy to share a rate-limit
    bucket until deployment configuration is corrected.
    """

    trusted_proxy_networks: tuple[IPNetwork, ...] = ()

    def __post_init__(self) -> None:
        normalized_networks = tuple(self.trusted_proxy_networks)
        if any(network.is_global for network in normalized_networks):
            raise ValueError("trusted proxy networks must not include public addresses")
        object.__setattr__(self, "trusted_proxy_networks", normalized_networks)

    @classmethod
    def from_cidrs(cls, cidrs: Sequence[str]) -> ClientAddressResolver:
        """Parse strict deployment-owned CIDRs; reject broad or malformed input."""
        networks: list[IPNetwork] = []
        for cidr in cidrs:
            try:
                network = ipaddress.ip_network(cidr, strict=True)
            except ValueError as error:
                raise ValueError("trusted proxy CIDR is invalid") from error
            networks.append(network)
        return cls(tuple(networks))

    def resolve(self, request: Request) -> str:
        """Return the nearest untrusted forwarding address or immediate peer."""
        peer_host = request.client.host if request.client is not None else "unknown"
        peer_address = _parse_address(peer_host)
        if peer_address is None or not self._is_trusted_proxy(peer_address):
            return peer_host

        forwarded_values = request.headers.getlist(_FORWARDED_FOR_HEADER)
        if not forwarded_values:
            return peer_host

        forwarded_addresses = _parse_forwarded_chain(forwarded_values)
        if forwarded_addresses is None:
            return peer_host

        for address in reversed(forwarded_addresses):
            if not self._is_trusted_proxy(address):
                return address.compressed
        return forwarded_addresses[0].compressed

    def _is_trusted_proxy(self, address: IPAddress) -> bool:
        return any(
            address.version == network.version and address in network
            for network in self.trusted_proxy_networks
        )


def _parse_forwarded_chain(values: Sequence[str]) -> tuple[IPAddress, ...] | None:
    candidates = tuple(
        item.strip()
        for value in values
        for item in value.split(",")
    )
    if not candidates or any(not candidate for candidate in candidates):
        return None

    parsed = tuple(_parse_address(candidate) for candidate in candidates)
    if any(address is None for address in parsed):
        return None
    return tuple(address for address in parsed if address is not None)


def _parse_address(value: str) -> IPAddress | None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if address.is_unspecified or address.is_multicast:
        return None
    return address
