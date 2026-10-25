"""Runtime database URL validation and engine construction tests."""

from __future__ import annotations

import asyncio
import ipaddress
import unittest
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.application.runtime_database_locator import (
    RuntimeDatabaseLocator,
    RuntimeDatabaseTarget,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_targets import (
    ResolvedBootstrapDatabaseTarget,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    database_engine_adapters,
    database_runtime,
)
from atlas_richie.sentinel_console.infrastructure.persistence.database_runtime import (
    ConsoleDatabaseConfiguration,
    ConsoleDatabaseConfigurationError,
)
from sqlalchemy import text
from sqlalchemy.engine import URL

_DATABASE_URL_ENV = "SENTINEL_CONSOLE_DATABASE_URL"


class ConsoleDatabaseConfigurationTests(unittest.TestCase):
    def test_default_adapter_registry_is_runtime_dialect_source_of_truth(self) -> None:
        self.assertEqual(
            database_engine_adapters.default_database_engine_adapters().supported_dialects,
            frozenset({"mysql", "postgresql", "sqlite"}),
        )
        self.assertEqual(
            database_runtime.SUPPORTED_RUNTIME_DATABASE_DIALECTS,
            database_engine_adapters.default_database_engine_adapters().supported_dialects,
        )

    def test_runtime_registry_rejects_duplicate_and_unknown_adapters(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique and non-empty"):
            database_engine_adapters.default_database_engine_adapters(
                additional_adapters=(
                    database_engine_adapters.SQLiteAsyncEngineAdapter(),
                )
            )

        registry = database_engine_adapters.default_database_engine_adapters()
        with self.assertRaisesRegex(ValueError, "driver is unsupported"):
            registry.resolve("future+async")

    def test_future_dialect_adapter_can_be_added_without_changing_facade_rules(
        self,
    ) -> None:
        class FutureDatabaseKind(StrEnum):
            FUTURE = "future"

        expected_engine = object()

        class FutureDatabaseAdapter:
            drivername = "future+async"
            dialect = "future"
            bootstrap_kind = FutureDatabaseKind.FUTURE
            supports_bootstrap = True
            requires_remote_target = True

            def create_bootstrap_url(
                self,
                candidate: BootstrapDatabaseCandidate,
                *,
                sqlite_database_path: Path | None = None,
            ) -> URL:
                del sqlite_database_path
                return URL.create(
                    self.drivername,
                    username=candidate.username,
                    password=candidate.password,
                    host=candidate.host,
                    port=candidate.port,
                    database=candidate.database,
                )

            def create_engine(self, url, options):
                del url, options
                return expected_engine

            def create_pinned_bootstrap_engine(
                self,
                candidate,
                url,
                target,
                *,
                postgresql_root_certificate,
                mysql_ssl_context,
            ):
                del candidate, postgresql_root_certificate, mysql_ssl_context
                self.last_bootstrap = (url, target)
                return expected_engine, RuntimeDatabaseTarget(
                    target.hostname,
                    tuple(address.compressed for address in target.addresses),
                )

        adapter = FutureDatabaseAdapter()
        registry = database_engine_adapters.default_database_engine_adapters(
            additional_adapters=(adapter,)
        )
        runtime = ConsoleDatabaseConfiguration.from_url(
            "future+async://operator:secret@db.internal/sentinel",
            adapter_registry=registry,
        )
        self.assertEqual(runtime.dialect, "future")
        self.assertIs(runtime.create_engine(), expected_engine)
        locator = RuntimeDatabaseLocator(
            "future+async://operator:secret@db.internal/sentinel",
            "e51f4e79-6894-48b0-8e5f-6d2a50863560",
        )
        self.assertIs(
            database_runtime.create_database_engine_from_locator(
                locator, adapter_registry=registry
            ),
            expected_engine,
        )

        candidate = BootstrapDatabaseCandidate(
            kind=FutureDatabaseKind.FUTURE,  # type: ignore[arg-type]
            host="db.internal",
            port=7443,
            database="sentinel",
            username="operator",
            password="secret",
        )
        bootstrap = ConsoleDatabaseConfiguration.from_bootstrap_candidate(
            candidate, adapter_registry=registry
        )
        target = ResolvedBootstrapDatabaseTarget(
            hostname="db.internal",
            port=7443,
            addresses=(ipaddress.ip_address("10.30.1.8"),),
        )
        engine, locator_target = bootstrap.create_pinned_bootstrap_engine(
            candidate,
            target,
            postgresql_root_certificate=None,
            mysql_ssl_context=None,
        )

        self.assertIs(engine, expected_engine)
        self.assertEqual(
            locator_target,
            RuntimeDatabaseTarget("db.internal", ("10.30.1.8",)),
        )
        self.assertEqual(adapter.last_bootstrap[0].drivername, "future+async")

    def test_maps_setup_candidate_to_secret_safe_supported_async_url(self) -> None:
        candidate = BootstrapDatabaseCandidate(
            kind=BootstrapDatabaseKind.POSTGRESQL,
            host="db.internal",
            port=5432,
            database="sentinel",
            username="console operator",
            password="p@ss /word",
        )
        configuration = ConsoleDatabaseConfiguration.from_bootstrap_candidate(candidate)

        self.assertEqual(configuration.dialect, "postgresql")
        self.assertEqual(configuration._url.password, "p@ss /word")
        self.assertEqual(configuration._url.host, "db.internal")
        self.assertNotIn("p@ss", repr(configuration))
        parsed = ConsoleDatabaseConfiguration.from_url(
            configuration.secret_url_for_storage()
        )
        self.assertEqual(parsed._url.password, "p@ss /word")

    def test_bootstrap_candidate_rejects_sqlite_missing_fields_and_bad_port(
        self,
    ) -> None:
        candidates = (
            BootstrapDatabaseCandidate(kind=BootstrapDatabaseKind.SQLITE),
            BootstrapDatabaseCandidate(
                kind=BootstrapDatabaseKind.MYSQL,
                host="db.internal",
                port=70000,
                database="sentinel",
                username="console",
                password="secret",
            ),
            BootstrapDatabaseCandidate(
                kind=BootstrapDatabaseKind.MYSQL,
                host="db.internal",
                port=3306,
                database="sentinel",
                username="console",
                password=None,
            ),
        )
        for candidate in candidates:
            with (
                self.subTest(kind=candidate.kind, port=candidate.port),
                self.assertRaises(ConsoleDatabaseConfigurationError),
            ):
                ConsoleDatabaseConfiguration.from_bootstrap_candidate(candidate)

    def test_bootstrap_engine_facade_rejects_cross_adapter_candidate(self) -> None:
        configuration = ConsoleDatabaseConfiguration.from_bootstrap_candidate(
            BootstrapDatabaseCandidate(
                kind=BootstrapDatabaseKind.POSTGRESQL,
                host="db.internal",
                port=5432,
                database="sentinel",
                username="console",
                password="secret",
            )
        )
        mysql_candidate = BootstrapDatabaseCandidate(
            kind=BootstrapDatabaseKind.MYSQL,
            host="db.internal",
            port=3306,
            database="sentinel",
            username="console",
            password="secret",
        )
        target = ResolvedBootstrapDatabaseTarget(
            hostname="db.internal",
            port=3306,
            addresses=(ipaddress.ip_address("10.30.1.8"),),
        )

        with self.assertRaisesRegex(
            ConsoleDatabaseConfigurationError, "does not match"
        ):
            configuration.create_pinned_bootstrap_engine(
                mysql_candidate,
                target,
                postgresql_root_certificate=None,
                mysql_ssl_context=None,
            )

    def test_accepts_supported_async_postgresql_and_mysql_urls(self) -> None:
        cases = (
            (
                "postgresql+psycopg://console:p%40ss@db.internal:5432/sentinel",
                "postgresql",
                "p@ss",
            ),
            (
                "mysql+asyncmy://console:p%40ss@db.internal:3306/sentinel",
                "mysql",
                "p@ss",
            ),
        )
        for raw_url, expected_dialect, expected_password in cases:
            with self.subTest(dialect=expected_dialect):
                config = ConsoleDatabaseConfiguration.from_environment(
                    {_DATABASE_URL_ENV: raw_url}
                )
                self.assertEqual(config.dialect, expected_dialect)
                self.assertEqual(config._url.password, expected_password)
                self.assertNotIn("p%40ss", repr(config))
                self.assertNotIn(expected_password, repr(config))

    def test_accepts_only_file_backed_local_sqlite_runtime_urls(self) -> None:
        config = ConsoleDatabaseConfiguration.from_url(
            "sqlite+aiosqlite:////var/lib/sentinel/console.db"
        )

        self.assertEqual(config.dialect, "sqlite")
        self.assertEqual(config._url.database, "/var/lib/sentinel/console.db")
        self.assertNotIn("/var/lib/sentinel", repr(config))

    def test_sqlite_runtime_engine_is_created_through_its_adapter(self) -> None:
        locator = RuntimeDatabaseLocator(
            "sqlite+aiosqlite:////var/lib/sentinel/console.db",
            "a3f0c28b-05ee-4a8d-90e9-bdef63fdbff7",
        )
        engine = object()
        with patch.object(
            database_engine_adapters, "create_async_engine", return_value=engine
        ) as create:
            actual = database_runtime.create_database_engine_from_locator(locator)

        self.assertIs(actual, engine)
        self.assertEqual(create.call_args.args[0].drivername, "sqlite+aiosqlite")
        self.assertEqual(
            create.call_args.kwargs,
            {"pool_pre_ping": True, "hide_parameters": True},
        )

    def test_file_backed_sqlite_runtime_engine_executes_sql(self) -> None:
        async def scenario(database_path: Path) -> None:
            configuration = ConsoleDatabaseConfiguration.from_url(
                f"sqlite+aiosqlite:///{database_path.as_posix()}"
            )
            engine = configuration.create_engine()
            try:
                async with engine.connect() as connection:
                    self.assertEqual(await connection.scalar(text("SELECT 1")), 1)
            finally:
                await engine.dispose()

        with TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory) / "console.db"))

    def test_sqlite_locator_rejects_remote_target(self) -> None:
        locator = RuntimeDatabaseLocator(
            "sqlite+aiosqlite:////var/lib/sentinel/console.db",
            "a3f0c28b-05ee-4a8d-90e9-bdef63fdbff7",
            RuntimeDatabaseTarget("db.internal", ("10.30.1.8",)),
        )

        with self.assertRaisesRegex(
            ConsoleDatabaseConfigurationError, "target does not match"
        ):
            ConsoleDatabaseConfiguration.from_locator(locator)

    def test_rejects_missing_local_or_sync_urls_without_sqlite_fallback(self) -> None:
        invalid_environments = (
            {},
            {_DATABASE_URL_ENV: ""},
            {_DATABASE_URL_ENV: "not-a-url"},
            {_DATABASE_URL_ENV: "sqlite+aiosqlite:///:memory:"},
            {_DATABASE_URL_ENV: ("postgresql://console:password@db.internal/sentinel")},
            {_DATABASE_URL_ENV: "mysql+asyncmy://console@db.internal/sentinel"},
        )
        for environment in invalid_environments:
            with (
                self.subTest(configured=bool(environment)),
                self.assertRaises(ConsoleDatabaseConfigurationError),
            ):
                ConsoleDatabaseConfiguration.from_environment(environment)

    def test_engine_composition_is_lazy_and_hides_sql_parameters(self) -> None:
        config = ConsoleDatabaseConfiguration.from_environment(
            {
                _DATABASE_URL_ENV: (
                    "postgresql+psycopg://console:secret@db.internal/sentinel"
                )
            }
        )
        engine = object()
        with patch.object(
            database_engine_adapters, "create_async_engine", return_value=engine
        ) as create:
            self.assertIs(config.create_engine(), engine)
        create.assert_called_once_with(
            config._url,
            pool_pre_ping=True,
            hide_parameters=True,
        )

    def test_persisted_locator_resolves_to_lazy_engine_or_setup_mode(self) -> None:
        database_url = "postgresql+psycopg://console:secret@db.internal/sentinel"
        expected_engine = object()

        class _LocatorStore:
            def __init__(self, locator):
                self._locator = locator

            async def read(self):
                return self._locator

        async def scenario() -> None:
            self.assertIsNone(
                await database_runtime.create_runtime_database_engine(
                    _LocatorStore(None)
                )
            )
            locator = RuntimeDatabaseLocator(
                database_url,
                "a3f0c28b-05ee-4a8d-90e9-bdef63fdbff7",
            )
            with patch.object(
                database_engine_adapters,
                "create_async_engine",
                return_value=expected_engine,
            ) as create:
                actual = await database_runtime.create_runtime_database_engine(
                    _LocatorStore(locator)
                )
            self.assertIs(actual, expected_engine)
            self.assertEqual(create.call_args.args[0].password, "secret")
            self.assertNotIn("secret", repr(create.call_args.args[0]))
            self.assertNotIn("secret", repr(locator))

        asyncio.run(scenario())

    def test_pinned_locator_keeps_runtime_postgresql_off_dns(self) -> None:
        locator = RuntimeDatabaseLocator(
            "postgresql+psycopg://console:secret@db.internal/sentinel",
            "a3f0c28b-05ee-4a8d-90e9-bdef63fdbff7",
            RuntimeDatabaseTarget("db.internal", ("10.30.1.8",)),
        )

        class _LocatorStore:
            async def read(self):
                return locator

        engine = object()
        with patch.object(
            database_engine_adapters, "create_async_engine", return_value=engine
        ) as create:
            result = asyncio.run(
                database_runtime.create_runtime_database_engine(_LocatorStore())
            )

        self.assertIs(result, engine)
        options = create.call_args.kwargs
        self.assertEqual(options["connect_args"]["hostaddr"], "10.30.1.8")
        self.assertEqual(options["connect_args"]["sslmode"], "verify-full")

    def test_pinned_postgresql_runtime_engine_uses_configured_root_certificate(
        self,
    ) -> None:
        locator = RuntimeDatabaseLocator(
            "postgresql+psycopg://console:secret@db.internal/sentinel",
            "a3f0c28b-05ee-4a8d-90e9-bdef63fdbff7",
            RuntimeDatabaseTarget("db.internal", ("10.30.1.8",)),
        )
        engine = object()
        with patch.object(
            database_engine_adapters, "create_async_engine", return_value=engine
        ) as create:
            result = database_runtime.create_database_engine_from_locator(
                locator,
                postgresql_root_certificate="/etc/sentinel/database-ca.pem",
            )

        self.assertIs(result, engine)
        self.assertEqual(
            create.call_args.kwargs["connect_args"],
            {
                "hostaddr": "10.30.1.8",
                "sslmode": "verify-full",
                "sslrootcert": "/etc/sentinel/database-ca.pem",
            },
        )

    def test_pinned_locator_rejects_hostname_mismatch(self) -> None:
        locator = RuntimeDatabaseLocator(
            "postgresql+psycopg://console:secret@other.internal/sentinel",
            "a3f0c28b-05ee-4a8d-90e9-bdef63fdbff7",
            RuntimeDatabaseTarget("db.internal", ("10.30.1.8",)),
        )

        with self.assertRaisesRegex(
            database_runtime.ConsoleDatabaseConfigurationError,
            "does not match",
        ):
            ConsoleDatabaseConfiguration.from_locator(locator)

    def test_pinned_locator_uses_runtime_mysql_connector_with_tls_hostname(
        self,
    ) -> None:
        locator = RuntimeDatabaseLocator(
            "mysql+asyncmy://console:secret@db.internal:3306/sentinel",
            "a3f0c28b-05ee-4a8d-90e9-bdef63fdbff7",
            RuntimeDatabaseTarget("db.internal", ("10.30.1.8",)),
        )

        class _LocatorStore:
            async def read(self):
                return locator

        engine = object()
        creator = object()
        with (
            patch.object(
                database_engine_adapters,
                "create_pinned_mysql_async_creator",
                return_value=creator,
            ) as make_creator,
            patch.object(
                database_engine_adapters, "create_async_engine", return_value=engine
            ) as create,
        ):
            result = asyncio.run(
                database_runtime.create_runtime_database_engine(_LocatorStore())
            )

        self.assertIs(result, engine)
        self.assertEqual(make_creator.call_args.kwargs["hostname"], "db.internal")
        self.assertEqual(make_creator.call_args.kwargs["addresses"], ("10.30.1.8",))
        self.assertEqual(make_creator.call_args.kwargs["connect_timeout_seconds"], 10)
        self.assertIs(create.call_args.kwargs["async_creator"], creator)

    def test_mysql_connection_timeout_can_be_configured_with_a_safe_bound(self) -> None:
        with patch.dict(
            "os.environ",
            {"SENTINEL_CONSOLE_DATABASE_CONNECT_TIMEOUT_SECONDS": "18"},
        ):
            self.assertEqual(
                database_engine_adapters._database_connect_timeout_seconds(), 18
            )

        for invalid_value in ("0", "61", "not-a-number"):
            with (
                self.subTest(value=invalid_value),
                patch.dict(
                    "os.environ",
                    {
                        "SENTINEL_CONSOLE_DATABASE_CONNECT_TIMEOUT_SECONDS": (
                            invalid_value
                        )
                    },
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "SENTINEL_CONSOLE_DATABASE_CONNECT_TIMEOUT_SECONDS",
                ),
            ):
                database_engine_adapters._database_connect_timeout_seconds()


if __name__ == "__main__":
    unittest.main()
