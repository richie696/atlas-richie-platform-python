import asyncio
import ipaddress
import socket

import pytest

from atlas_richie.sentinel_console.infrastructure.monitoring_target_policy import (
    MonitoringTargetPolicy,
    MonitoringTargetRejected,
    MonitoringTargetRule,
)


def _address_info(address: str) -> tuple[int, int, int, str, tuple[object, ...]]:
    parsed = ipaddress.ip_address(address)
    family = socket.AF_INET6 if parsed.version == 6 else socket.AF_INET
    sockaddr: tuple[object, ...] = (
        (address, 9090, 0, 0) if family == socket.AF_INET6 else (address, 9090)
    )
    return family, socket.SOCK_STREAM, 6, "", sockaddr


def _resolver_for(*addresses: str):
    async def resolve(_host: str, _port: int):
        return tuple(_address_info(address) for address in addresses)

    return resolve


def _rule(
    *,
    hostname: str = "prometheus.internal",
    networks: tuple[str, ...] = ("10.0.0.0/8",),
    ports: frozenset[int] = frozenset({9090}),
    allow_private_http: bool = False,
    allow_loopback_http: bool = False,
) -> MonitoringTargetRule:
    return MonitoringTargetRule.create(
        hostname,
        networks,
        ports,
        allow_private_http=allow_private_http,
        allow_loopback_http=allow_loopback_http,
    )


def test_https_private_target_resolves_once_and_returns_pinned_addresses() -> None:
    policy = MonitoringTargetPolicy(
        (_rule(),), resolver=_resolver_for("10.12.3.4", "10.12.3.5")
    )

    result = asyncio.run(
        policy.resolve(
            "https://prometheus.internal:9090/prometheus", authenticated=True
        )
    )

    assert result.hostname == "prometheus.internal"
    assert result.port == 9090
    assert tuple(map(str, result.addresses)) == ("10.12.3.4", "10.12.3.5")
    assert result.secure is True


def test_private_http_requires_explicit_private_allowlist_and_no_auth() -> None:
    policy = MonitoringTargetPolicy(
        (_rule(allow_private_http=True),),
        resolver=_resolver_for("10.10.0.2"),
    )

    result = asyncio.run(
        policy.resolve("http://prometheus.internal:9090", authenticated=False)
    )

    assert result.secure is False
    with pytest.raises(MonitoringTargetRejected):
        asyncio.run(
            policy.resolve("http://prometheus.internal:9090", authenticated=True)
        )


def test_plain_http_requires_deployment_opt_in() -> None:
    policy = MonitoringTargetPolicy((_rule(),), resolver=_resolver_for("10.10.0.2"))
    with pytest.raises(MonitoringTargetRejected):
        asyncio.run(
            policy.resolve("http://prometheus.internal:9090", authenticated=False)
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:secret@prometheus.internal:9090",
        "https://prometheus.internal:9090?token=secret",
        "https://prometheus.internal:9090/#fragment",
        "https://prometheus.internal:0",
        "https://prometheus.internal:9090/a/%2e%2e/admin",
    ],
)
def test_endpoint_rejects_credentials_query_fragments_bad_port_and_dot_segments(
    endpoint: str,
) -> None:
    policy = MonitoringTargetPolicy(
        (_rule(),),
        resolver=_resolver_for("10.10.0.2"),
    )
    with pytest.raises((MonitoringTargetRejected, ValueError)):
        asyncio.run(policy.resolve(endpoint, authenticated=False))


def test_all_dns_answers_must_match_allowlist_and_network_policy() -> None:
    mixed = MonitoringTargetPolicy(
        (_rule(),), resolver=_resolver_for("10.10.0.2", "8.8.8.8")
    )
    with pytest.raises(MonitoringTargetRejected):
        asyncio.run(
            mixed.resolve("https://prometheus.internal:9090", authenticated=False)
        )

    metadata = MonitoringTargetPolicy(
        (
            _rule(
                hostname="metadata.internal",
                networks=("169.254.0.0/16",),
            ),
        ),
        resolver=_resolver_for("169.254.169.254"),
    )
    with pytest.raises(MonitoringTargetRejected):
        asyncio.run(
            metadata.resolve("https://metadata.internal:9090", authenticated=False)
        )


def test_plain_http_rule_cannot_allow_non_private_or_catch_all_networks() -> None:
    with pytest.raises(ValueError, match="only private networks"):
        _rule(networks=("8.8.8.0/24",), allow_private_http=True)
    with pytest.raises(ValueError, match="explicit"):
        _rule(networks=("0.0.0.0/0",))


def test_loopback_http_is_only_allowed_by_exact_loopback_rule() -> None:
    policy = MonitoringTargetPolicy(
        (
            _rule(
                hostname="127.0.0.1",
                networks=("127.0.0.0/8",),
                ports=frozenset({9090}),
                allow_loopback_http=True,
            ),
        )
    )

    target = asyncio.run(policy.resolve("http://127.0.0.1:9090", authenticated=False))
    assert target.addresses == (ipaddress.ip_address("127.0.0.1"),)

    with pytest.raises(MonitoringTargetRejected):
        asyncio.run(policy.resolve("http://localhost:9090", authenticated=False))
