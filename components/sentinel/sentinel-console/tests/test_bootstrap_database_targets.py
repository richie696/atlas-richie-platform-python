"""Focused policy tests for bootstrap database network targets."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import unittest

from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_targets import (
    BootstrapDatabaseTargetPolicy,
    BootstrapDatabaseTargetRejected,
    BootstrapDatabaseTargetRule,
)


def _address_info(address: str) -> tuple[int, int, int, str, tuple[object, ...]]:
    parsed = ipaddress.ip_address(address)
    if parsed.version == 4:
        sockaddr: tuple[object, ...] = (address, 5432)
        family = socket.AF_INET
    else:
        sockaddr = (address, 5432, 0, 0)
        family = socket.AF_INET6
    return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr


class BootstrapDatabaseTargetPolicyTest(unittest.IsolatedAsyncioTestCase):
    def _policy(self, resolver, *rules):
        return BootstrapDatabaseTargetPolicy(rules, resolver=resolver)

    async def test_allowed_hostname_returns_normalized_pinned_addresses(self) -> None:
        calls: list[tuple[str, int]] = []

        async def resolver(hostname: str, port: int):
            calls.append((hostname, port))
            return (_address_info("10.30.1.8"), _address_info("10.30.1.9"))

        policy = self._policy(
            resolver,
            BootstrapDatabaseTargetRule.create(
                BootstrapDatabaseKind.POSTGRESQL,
                "10.30.0.0/16",
                frozenset({5432}),
            ),
        )

        target = await policy.resolve(
            BootstrapDatabaseKind.POSTGRESQL, "DB.INTERNAL.EXAMPLE.", 5432
        )

        self.assertEqual(target.hostname, "db.internal.example")
        self.assertEqual(target.addresses, (ipaddress.ip_address("10.30.1.8"),
                                            ipaddress.ip_address("10.30.1.9")))
        self.assertEqual(calls, [("db.internal.example", 5432)])

    async def test_ip_literal_uses_allowlist_without_dns(self) -> None:
        async def unexpected_resolver(_hostname: str, _port: int):
            self.fail("IP literals must not invoke DNS")

        policy = self._policy(
            unexpected_resolver,
            BootstrapDatabaseTargetRule.create(
                BootstrapDatabaseKind.MYSQL,
                "10.40.0.0/16",
                frozenset({3306}),
            ),
        )

        target = await policy.resolve(BootstrapDatabaseKind.MYSQL, "10.40.2.3", 3306)

        self.assertEqual(target.addresses, (ipaddress.ip_address("10.40.2.3"),))

    async def test_mixed_dns_answers_reject_the_entire_target(self) -> None:
        async def resolver(_hostname: str, _port: int):
            return (_address_info("10.30.1.8"), _address_info("203.0.113.4"))

        policy = self._policy(
            resolver,
            BootstrapDatabaseTargetRule.create(
                BootstrapDatabaseKind.POSTGRESQL,
                "10.30.0.0/16",
                frozenset({5432}),
            ),
        )

        with self.assertRaises(BootstrapDatabaseTargetRejected):
            await policy.resolve(
                BootstrapDatabaseKind.POSTGRESQL, "db.internal.example", 5432
            )

    async def test_excessive_dns_answers_reject_the_target(self) -> None:
        async def resolver(_hostname: str, _port: int):
            return tuple(
                _address_info(f"10.30.1.{last_octet}")
                for last_octet in range(1, 10)
            )

        policy = self._policy(
            resolver,
            BootstrapDatabaseTargetRule.create(
                BootstrapDatabaseKind.POSTGRESQL,
                "10.30.0.0/16",
                frozenset({5432}),
            ),
        )

        with self.assertRaises(BootstrapDatabaseTargetRejected):
            await policy.resolve(
                BootstrapDatabaseKind.POSTGRESQL, "db.internal.example", 5432
            )

    async def test_kind_and_port_are_checked_before_dns(self) -> None:
        async def unexpected_resolver(_hostname: str, _port: int):
            self.fail("A disallowed port must not trigger DNS")

        policy = self._policy(
            unexpected_resolver,
            BootstrapDatabaseTargetRule.create(
                BootstrapDatabaseKind.POSTGRESQL,
                "10.30.0.0/16",
                frozenset({5432}),
            ),
        )

        with self.assertRaises(BootstrapDatabaseTargetRejected):
            await policy.resolve(
                BootstrapDatabaseKind.MYSQL, "db.internal.example", 3306
            )

    async def test_link_local_address_is_rejected_even_if_allowlisted(self) -> None:
        async def resolver(_hostname: str, _port: int):
            return (_address_info("169.254.169.254"),)

        policy = self._policy(
            resolver,
            BootstrapDatabaseTargetRule.create(
                BootstrapDatabaseKind.POSTGRESQL,
                "169.254.169.254/32",
                frozenset({5432}),
            ),
        )

        with self.assertRaises(BootstrapDatabaseTargetRejected):
            await policy.resolve(
                BootstrapDatabaseKind.POSTGRESQL, "metadata.internal", 5432
            )

    async def test_invalid_host_and_broad_allowlist_reject(self) -> None:
        with self.assertRaises(ValueError):
            BootstrapDatabaseTargetRule.create(
                BootstrapDatabaseKind.POSTGRESQL,
                "0.0.0.0/0",
                frozenset({5432}),
            )

        policy = self._policy(
            None,
            BootstrapDatabaseTargetRule.create(
                BootstrapDatabaseKind.POSTGRESQL,
                "10.30.0.0/16",
                frozenset({5432}),
            ),
        )
        for host in ("", " db.internal", "db/internal", "fe80::1%en0"):
            with self.subTest(host=host):
                with self.assertRaises(BootstrapDatabaseTargetRejected):
                    await policy.resolve(
                        BootstrapDatabaseKind.POSTGRESQL, host, 5432
                    )

    async def test_dns_failure_is_normalized_to_target_rejection(self) -> None:
        async def resolver(_hostname: str, _port: int):
            raise asyncio.TimeoutError

        policy = self._policy(
            resolver,
            BootstrapDatabaseTargetRule.create(
                BootstrapDatabaseKind.POSTGRESQL,
                "10.30.0.0/16",
                frozenset({5432}),
            ),
        )

        with self.assertRaises(BootstrapDatabaseTargetRejected):
            await policy.resolve(
                BootstrapDatabaseKind.POSTGRESQL, "db.internal.example", 5432
            )
