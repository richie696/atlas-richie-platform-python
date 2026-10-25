"""Focused tests for the read-only remote database connector adapter."""

from __future__ import annotations

import importlib.util
import ipaddress
import sqlite3
import ssl
import sys
import tempfile
import unittest
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar, Self
from unittest.mock import AsyncMock, patch

from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseCheckResult,
    BootstrapDatabaseCheckUnavailable,
    BootstrapDatabaseFailureReason,
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_check_adapters import (
    BootstrapDatabaseCheckAdapterRegistry,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_connector import (
    BootstrapDatabaseConnector,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_targets import (
    ResolvedBootstrapDatabaseTarget,
)
from atlas_richie.sentinel_console.infrastructure.pinned_mysql_connection import (
    PinnedHostnameMySQLConnectionMixin,
)
from atlas_richie.sentinel_console.infrastructure.postgresql_bootstrap_database_check_adapter import (
    BootstrapDatabaseAuthenticationRejected,
    probe_postgresql_address,
)
from atlas_richie.sentinel_console.infrastructure.sqlite_bootstrap_database_check_adapter import (
    SQLiteBootstrapDatabaseCheckAdapter,
)


class _FakeCursor:
    def __init__(self, calls: list[tuple[str, str]]) -> None:
        self._calls = calls

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, statement: str) -> None:
        self._calls.append(("execute", statement))

    async def fetchone(self) -> tuple[int]:
        self._calls.append(("fetchone", ""))
        return (1,)


class _FakePostgreSQLConnection:
    def __init__(self, calls: list[tuple[str, str]]) -> None:
        self._calls = calls

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._calls)


class _FakeMySQLConnection:
    instances: ClassVar[list[_FakeMySQLConnection]] = []

    def __init__(self, **options: object) -> None:
        self.options = options
        self._host = str(options["host"])
        self.calls: list[tuple[str, str]] = []
        self.tls_hostname: str | None = None
        self.closed = False
        self.instances.append(self)

    async def connect(self) -> None:
        await self._request_authentication()

    async def _request_authentication(self) -> None:
        self.tls_hostname = self._host

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.calls)

    async def ensure_closed(self) -> None:
        self.closed = True


class _FakeTargetPolicy:
    def __init__(self, target: ResolvedBootstrapDatabaseTarget) -> None:
        self.target = target

    async def resolve(self, *_args: object) -> ResolvedBootstrapDatabaseTarget:
        return self.target


class BootstrapDatabaseConnectorTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _FakeMySQLConnection.instances.clear()

    def _candidate(
        self, kind: BootstrapDatabaseKind = BootstrapDatabaseKind.POSTGRESQL
    ) -> BootstrapDatabaseCandidate:
        return BootstrapDatabaseCandidate(
            kind=kind,
            host="db.internal.example",
            port=5432 if kind is BootstrapDatabaseKind.POSTGRESQL else 3306,
            database="sentinel",
            username="bootstrap",
            password="secret-is-not-logged",
        )

    def _target(self, port: int = 5432) -> ResolvedBootstrapDatabaseTarget:
        return ResolvedBootstrapDatabaseTarget(
            hostname="db.internal.example",
            port=port,
            addresses=(ipaddress.ip_address("10.30.1.8"),),
        )

    async def test_sqlite_is_unsupported_without_a_deployment_path(self) -> None:
        checker = BootstrapDatabaseConnector(_FakeTargetPolicy(self._target()))

        result = await checker.check(
            BootstrapDatabaseCandidate(kind=BootstrapDatabaseKind.SQLITE)
        )
        self.assertEqual(
            result,
            BootstrapDatabaseCheckResult(
                reachable=False,
                reason=BootstrapDatabaseFailureReason.UNSUPPORTED,
            ),
        )

    async def test_unknown_database_kind_returns_unsupported(self) -> None:
        checker = BootstrapDatabaseConnector(_FakeTargetPolicy(self._target()))
        candidate = BootstrapDatabaseCandidate(kind="future-db")  # type: ignore[arg-type]

        result = await checker.check(candidate)

        self.assertEqual(
            result.reason,
            BootstrapDatabaseFailureReason.UNSUPPORTED,
        )

    async def test_composition_owned_future_check_adapter_is_selected(self) -> None:
        class FutureDatabaseKind(StrEnum):
            FUTURE = "future"

        class FutureDatabaseCheckAdapter:
            kind = FutureDatabaseKind.FUTURE

            async def check(
                self, candidate: BootstrapDatabaseCandidate
            ) -> BootstrapDatabaseCheckResult:
                self.candidate = candidate
                return BootstrapDatabaseCheckResult(reachable=True)

        adapter = FutureDatabaseCheckAdapter()
        checker = BootstrapDatabaseConnector(
            _FakeTargetPolicy(self._target()),
            additional_adapters=(adapter,),
        )
        candidate = BootstrapDatabaseCandidate(
            kind=FutureDatabaseKind.FUTURE,  # type: ignore[arg-type]
            host="db.internal.example",
            port=7443,
            database="sentinel",
            username="bootstrap",
            password="never-log-this-secret",
        )

        result = await checker.check(candidate)

        self.assertEqual(result, BootstrapDatabaseCheckResult(reachable=True))
        self.assertIs(adapter.candidate, candidate)
        self.assertNotIn("never-log-this-secret", repr(adapter.candidate))

    async def test_future_check_adapter_exposes_only_stable_failure_reason(
        self,
    ) -> None:
        class FutureDatabaseKind(StrEnum):
            FUTURE = "future"

        class FutureDatabaseCheckAdapter:
            kind = FutureDatabaseKind.FUTURE

            async def check(
                self, candidate: BootstrapDatabaseCandidate
            ) -> BootstrapDatabaseCheckResult:
                del candidate
                return BootstrapDatabaseCheckResult(
                    reachable=False,
                    reason=BootstrapDatabaseFailureReason.CONNECTION,
                )

        checker = BootstrapDatabaseConnector(
            _FakeTargetPolicy(self._target()),
            additional_adapters=(FutureDatabaseCheckAdapter(),),
        )

        result = await checker.check(
            BootstrapDatabaseCandidate(
                kind=FutureDatabaseKind.FUTURE,  # type: ignore[arg-type]
            )
        )

        self.assertEqual(
            result,
            BootstrapDatabaseCheckResult(
                reachable=False,
                reason=BootstrapDatabaseFailureReason.CONNECTION,
            ),
        )
        self.assertNotIn("driver", repr(result))

    def test_check_adapter_registry_rejects_duplicate_kinds(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be unique"):
            BootstrapDatabaseCheckAdapterRegistry(
                (
                    SQLiteBootstrapDatabaseCheckAdapter(),
                    SQLiteBootstrapDatabaseCheckAdapter(),
                )
            )

    async def test_sqlite_uses_only_the_deployment_owned_path_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "console.db"
            with sqlite3.connect(database_path) as connection:
                connection.execute("CREATE TABLE sentinel_probe (value INTEGER)")
            original_bytes = database_path.read_bytes()
            checker = BootstrapDatabaseConnector(
                _FakeTargetPolicy(self._target()),
                sqlite_database_path=database_path,
            )

            result = await checker.check(
                BootstrapDatabaseCandidate(kind=BootstrapDatabaseKind.SQLITE)
            )

            self.assertTrue(result.reachable)
            self.assertEqual(database_path.read_bytes(), original_bytes)

    async def test_sqlite_missing_database_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "not-created.db"
            checker = BootstrapDatabaseConnector(
                _FakeTargetPolicy(self._target()),
                sqlite_database_path=database_path,
            )

            result = await checker.check(
                BootstrapDatabaseCandidate(kind=BootstrapDatabaseKind.SQLITE)
            )

            self.assertEqual(
                result,
                BootstrapDatabaseCheckResult(
                    reachable=False,
                    reason=BootstrapDatabaseFailureReason.CONNECTION,
                ),
            )
            self.assertFalse(database_path.exists())

    def test_sqlite_path_must_be_absolute(self) -> None:
        with self.assertRaises(ValueError):
            BootstrapDatabaseConnector(
                _FakeTargetPolicy(self._target()),
                sqlite_database_path=Path("relative/console.db"),
            )

    async def test_postgresql_uses_pinned_address_and_verifies_original_hostname(
        self,
    ) -> None:
        calls: list[tuple[str, str]] = []
        fake_driver = SimpleNamespace(
            AsyncConnection=SimpleNamespace(
                connect=AsyncMock(return_value=_FakePostgreSQLConnection(calls))
            ),
            Error=Exception,
        )

        await probe_postgresql_address(
            fake_driver,
            self._candidate(),
            "db.internal.example",
            "10.30.1.8",
            None,
        )

        options = fake_driver.AsyncConnection.connect.await_args.kwargs
        self.assertEqual(options["host"], "db.internal.example")
        self.assertEqual(options["hostaddr"], "10.30.1.8")
        self.assertEqual(options["sslmode"], "verify-full")
        self.assertNotIn("sslrootcert", options)
        self.assertEqual(options["autocommit"], True)
        self.assertEqual(calls, [("execute", "SELECT 1"), ("fetchone", "")])

    async def test_postgresql_authentication_sqlstate_is_normalized(self) -> None:
        class FakeAuthenticationError(Exception):
            sqlstate = "28P01"

        fake_driver = SimpleNamespace(
            AsyncConnection=SimpleNamespace(
                connect=AsyncMock(side_effect=FakeAuthenticationError())
            ),
            Error=FakeAuthenticationError,
        )

        with self.assertRaises(BootstrapDatabaseAuthenticationRejected):
            await probe_postgresql_address(
                fake_driver,
                self._candidate(),
                "db.internal.example",
                "10.30.1.8",
                None,
            )

    async def test_postgresql_libpq_connect_authentication_is_normalized(self) -> None:
        class LibpqConnectError(Exception):
            sqlstate = None

        fake_driver = SimpleNamespace(
            AsyncConnection=SimpleNamespace(
                connect=AsyncMock(
                    side_effect=LibpqConnectError(
                        "connection failed: FATAL: password authentication failed "
                        'for user "bootstrap"'
                    )
                )
            ),
            Error=LibpqConnectError,
        )

        with self.assertRaises(BootstrapDatabaseAuthenticationRejected):
            await probe_postgresql_address(
                fake_driver,
                self._candidate(),
                "db.internal.example",
                "10.30.1.8",
                None,
            )

    async def test_mysql_connects_to_pin_but_keeps_hostname_for_tls(self) -> None:
        fake_driver = SimpleNamespace(
            Connection=_FakeMySQLConnection,
            errors=SimpleNamespace(Error=Exception),
        )
        checker = BootstrapDatabaseConnector(_FakeTargetPolicy(self._target(port=3306)))

        with patch.dict(sys.modules, {"asyncmy": fake_driver}):
            result = await checker.check(self._candidate(BootstrapDatabaseKind.MYSQL))

        connection = _FakeMySQLConnection.instances[0]
        self.assertTrue(result.reachable)
        self.assertEqual(connection.options["host"], "10.30.1.8")
        self.assertEqual(connection.tls_hostname, "db.internal.example")
        self.assertEqual(connection._host, "10.30.1.8")
        self.assertIsInstance(connection.options["ssl"], ssl.SSLContext)
        self.assertTrue(connection.options["ssl"].check_hostname)
        self.assertEqual(connection.options["ssl"].verify_mode, ssl.CERT_REQUIRED)
        self.assertFalse(connection.options["local_infile"])
        self.assertTrue(connection.closed)
        self.assertEqual(connection.calls, [("execute", "SELECT 1"), ("fetchone", "")])

    async def test_mysql_authentication_error_uses_a_bounded_reason(self) -> None:
        class AuthenticationError(Exception):
            def __init__(self) -> None:
                super().__init__(1045, "raw password rejected by database")

        class RejectingConnection(_FakeMySQLConnection):
            async def connect(self) -> None:
                raise AuthenticationError()

        fake_driver = SimpleNamespace(
            Connection=RejectingConnection,
            errors=SimpleNamespace(Error=AuthenticationError),
        )
        checker = BootstrapDatabaseConnector(_FakeTargetPolicy(self._target(port=3306)))

        with patch.dict(sys.modules, {"asyncmy": fake_driver}):
            result = await checker.check(self._candidate(BootstrapDatabaseKind.MYSQL))

        self.assertEqual(result.reason, BootstrapDatabaseFailureReason.AUTHENTICATION)

    async def test_mysql_close_driver_error_is_normalized_as_connection_failure(
        self,
    ) -> None:
        class DriverError(Exception):
            pass

        class CloseFailingConnection(_FakeMySQLConnection):
            async def ensure_closed(self) -> None:
                self.closed = True
                raise DriverError("private cleanup detail")

        fake_driver = SimpleNamespace(
            Connection=CloseFailingConnection,
            errors=SimpleNamespace(Error=DriverError),
        )
        checker = BootstrapDatabaseConnector(_FakeTargetPolicy(self._target(port=3306)))

        with patch.dict(sys.modules, {"asyncmy": fake_driver}):
            result = await checker.check(self._candidate(BootstrapDatabaseKind.MYSQL))

        self.assertFalse(result.reachable)
        self.assertEqual(result.reason, BootstrapDatabaseFailureReason.CONNECTION)
        self.assertTrue(CloseFailingConnection.instances[0].closed)

    async def test_mysql_close_driver_error_does_not_mask_authentication_rejection(
        self,
    ) -> None:
        class DriverError(Exception):
            pass

        class AuthenticationAndCloseFailingConnection(_FakeMySQLConnection):
            async def connect(self) -> None:
                raise DriverError(1045, "private authentication detail")

            async def ensure_closed(self) -> None:
                self.closed = True
                raise DriverError("private cleanup detail")

        fake_driver = SimpleNamespace(
            Connection=AuthenticationAndCloseFailingConnection,
            errors=SimpleNamespace(Error=DriverError),
        )
        checker = BootstrapDatabaseConnector(_FakeTargetPolicy(self._target(port=3306)))

        with patch.dict(sys.modules, {"asyncmy": fake_driver}):
            result = await checker.check(self._candidate(BootstrapDatabaseKind.MYSQL))

        self.assertFalse(result.reachable)
        self.assertEqual(result.reason, BootstrapDatabaseFailureReason.AUTHENTICATION)

    async def test_missing_driver_is_not_reported_as_database_reachable(self) -> None:
        checker = BootstrapDatabaseConnector(_FakeTargetPolicy(self._target()))
        candidate = self._candidate()

        with (
            patch.dict(sys.modules, {"psycopg": None}),
            self.assertRaises(BootstrapDatabaseCheckUnavailable),
        ):
            await checker.check(candidate)

    async def test_mysql_rejects_unverified_tls_context(self) -> None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False

        with self.assertRaises(ValueError):
            BootstrapDatabaseConnector(
                _FakeTargetPolicy(self._target()),
                mysql_ssl_context=context,
            )

    @unittest.skipUnless(
        importlib.util.find_spec("asyncmy"),
        "the MySQL optional extra is required for this driver contract check",
    )
    async def test_asyncmy_supports_the_pinned_hostname_override_hook(self) -> None:
        import asyncmy

        connection_class = type(
            "_PinnedHostnameAsyncMySQLConnection",
            (PinnedHostnameMySQLConnectionMixin, asyncmy.Connection),
            {},
        )
        connection = connection_class(
            host="10.30.1.8",
            port=3306,
            user="bootstrap",
            password="synthetic",
            database="sentinel",
            ssl=ssl.create_default_context(),
            connect_timeout=1,
        )
        connection._target_hostname = "db.internal.example"

        self.assertTrue(issubclass(connection_class, asyncmy.Connection))
        self.assertIs(
            connection_class._request_authentication,
            PinnedHostnameMySQLConnectionMixin._request_authentication,
        )
        self.assertEqual(connection._host, "10.30.1.8")
        self.assertTrue(connection._ssl_context.check_hostname)
        connection.close()


if __name__ == "__main__":
    unittest.main()
