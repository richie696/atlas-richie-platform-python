"""Focused tests for address-pinned first-run SQL engine creation."""

from __future__ import annotations

import ipaddress
import os
import ssl
import sys
import unittest
from types import ModuleType
from unittest.mock import AsyncMock, patch

from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.application.runtime_database_locator import (
    RuntimeDatabaseTarget,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_engine import (
    BootstrapDatabaseEngineFactory,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_targets import (
    BootstrapDatabaseTargetRejected,
    ResolvedBootstrapDatabaseTarget,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    database_engine_adapters,
)


class _TargetPolicy:
    def __init__(self, target: ResolvedBootstrapDatabaseTarget) -> None:
        self.target = target
        self.calls: list[tuple[object, ...]] = []

    async def resolve(self, *args: object) -> ResolvedBootstrapDatabaseTarget:
        self.calls.append(args)
        return self.target


class BootstrapDatabaseEngineFactoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.target = ResolvedBootstrapDatabaseTarget(
            hostname="db.internal.example",
            port=5432,
            addresses=(
                ipaddress.ip_address("10.30.1.8"),
                ipaddress.ip_address("10.30.1.9"),
            ),
        )
        self.policy = _TargetPolicy(self.target)

    def _candidate(
        self, kind: BootstrapDatabaseKind = BootstrapDatabaseKind.POSTGRESQL
    ) -> BootstrapDatabaseCandidate:
        return BootstrapDatabaseCandidate(
            kind=kind,
            host="db.internal.example",
            port=5432 if kind is BootstrapDatabaseKind.POSTGRESQL else 3306,
            database="sentinel",
            username="console",
            password="secret-never-log",
        )

    async def test_postgresql_engine_uses_resolved_ip_and_verified_hostname_tls(
        self,
    ) -> None:
        engine = object()
        factory = BootstrapDatabaseEngineFactory(
            self.policy, postgresql_root_certificate="/etc/ssl/db-ca.pem"
        )
        with patch.object(
            database_engine_adapters, "create_async_engine", return_value=engine
        ) as create:
            result = await factory.create(self._candidate())

        self.assertIs(result.engine, engine)
        self.assertEqual(
            result.locator_target,
            RuntimeDatabaseTarget("db.internal.example", ("10.30.1.8",)),
        )
        self.assertNotIn("secret-never-log", repr(result))
        self.assertEqual(len(self.policy.calls), 1)
        (url,) = create.call_args.args
        self.assertEqual(url.host, "db.internal.example")
        self.assertNotIn("secret-never-log", repr(url))
        self.assertEqual(
            create.call_args.kwargs["connect_args"],
            {
                "hostaddr": "10.30.1.8",
                "sslmode": "verify-full",
                "connect_timeout": 10,
                "sslrootcert": "/etc/ssl/db-ca.pem",
            },
        )

    async def test_configured_connect_timeout_replaces_the_default(self) -> None:
        engine = object()
        factory = BootstrapDatabaseEngineFactory(
            self.policy, postgresql_root_certificate="/etc/ssl/db-ca.pem"
        )
        with patch.dict(
            os.environ,
            {"SENTINEL_CONSOLE_DATABASE_CONNECT_TIMEOUT_SECONDS": "45"},
        ), patch.object(
            database_engine_adapters, "create_async_engine", return_value=engine
        ) as create:
            result = await factory.create(self._candidate())

        self.assertIs(result.engine, engine)
        self.assertEqual(
            create.call_args.kwargs["connect_args"]["connect_timeout"],
            45,
        )

    async def test_out_of_range_connect_timeout_is_a_stable_failure(self) -> None:
        factory = BootstrapDatabaseEngineFactory(
            self.policy, postgresql_root_certificate="/etc/ssl/db-ca.pem"
        )
        with patch.dict(
            os.environ,
            {"SENTINEL_CONSOLE_DATABASE_CONNECT_TIMEOUT_SECONDS": "0"},
        ), patch.object(database_engine_adapters, "create_async_engine") as create:
            with self.assertRaises(ValueError):
                await factory.create(self._candidate())

        create.assert_not_called()

    async def test_denied_target_never_constructs_an_engine(self) -> None:
        self.policy.resolve = AsyncMock(side_effect=BootstrapDatabaseTargetRejected)
        factory = BootstrapDatabaseEngineFactory(self.policy)
        with patch.object(database_engine_adapters, "create_async_engine") as create:
            with self.assertRaises(BootstrapDatabaseTargetRejected):
                await factory.create(self._candidate())
        create.assert_not_called()

    async def test_mysql_creator_connects_to_pinned_ip_but_uses_hostname_for_tls(
        self,
    ) -> None:
        calls: list[tuple[str, str]] = []

        class FakeConnection:
            def __init__(self, **options: object) -> None:
                self._host = str(options["host"])
                self.options = options

            async def connect(self) -> None:
                await self._request_authentication()

            async def _request_authentication(self) -> None:
                calls.append((self._host, str(self.options["host"])))

            async def ensure_closed(self) -> None:
                return None

        fake_driver = ModuleType("asyncmy")
        fake_driver.Connection = FakeConnection
        fake_driver.errors = type("Errors", (), {"Error": RuntimeError})
        factory = BootstrapDatabaseEngineFactory(self.policy)
        engine = object()
        with patch.dict(sys.modules, {"asyncmy": fake_driver}):
            with patch.object(
                database_engine_adapters, "create_async_engine", return_value=engine
            ) as create:
                result = await factory.create(
                    self._candidate(BootstrapDatabaseKind.MYSQL)
                )
                creator = create.call_args.kwargs["async_creator"]
                connection = await creator()

        self.assertIs(result.engine, engine)
        self.assertEqual(connection._host, "10.30.1.8")
        self.assertEqual(calls, [("db.internal.example", "10.30.1.8")])
        self.assertEqual(create.call_args.args[0].host, "db.internal.example")
        self.assertNotIn("secret-never-log", repr(create.call_args))
        self.assertEqual(result.locator_target.addresses, ("10.30.1.8", "10.30.1.9"))

    async def test_unverified_mysql_tls_configuration_is_rejected(self) -> None:
        unsafe_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        unsafe_context.check_hostname = False
        unsafe_context.verify_mode = ssl.CERT_NONE
        with self.assertRaisesRegex(ValueError, "verified TLS"):
            BootstrapDatabaseEngineFactory(
                self.policy, mysql_ssl_context=unsafe_context
            )

    async def test_mysql_optional_driver_missing_is_a_stable_failure(self) -> None:
        factory = BootstrapDatabaseEngineFactory(self.policy)
        with patch.dict(sys.modules, {"asyncmy": None}):
            with self.assertRaisesRegex(RuntimeError, "async driver for mysql"):
                await factory.create(self._candidate(BootstrapDatabaseKind.MYSQL))


if __name__ == "__main__":
    unittest.main()
