"""Runtime database URL validation and engine construction tests."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from atlas_richie.sentinel_console.application.runtime_database_locator import (
    RuntimeDatabaseLocator,
    RuntimeDatabaseTarget,
)
from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.infrastructure.persistence import database_runtime
from atlas_richie.sentinel_console.infrastructure.persistence.database_runtime import (
    ConsoleDatabaseConfiguration,
    ConsoleDatabaseConfigurationError,
)

_DATABASE_URL_ENV = "SENTINEL_CONSOLE_DATABASE_URL"


class ConsoleDatabaseConfigurationTests(unittest.TestCase):
    def test_maps_setup_candidate_to_secret_safe_supported_async_url(self) -> None:
        candidate = BootstrapDatabaseCandidate(
            kind=BootstrapDatabaseKind.POSTGRESQL,
            host="db.internal",
            port=5432,
            database="sentinel",
            username="console operator",
            password="p@ss /word",
        )
        configuration = ConsoleDatabaseConfiguration.from_bootstrap_candidate(
            candidate
        )

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
            with self.subTest(kind=candidate.kind, port=candidate.port):
                with self.assertRaises(ConsoleDatabaseConfigurationError):
                    ConsoleDatabaseConfiguration.from_bootstrap_candidate(candidate)

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

    def test_rejects_missing_local_or_sync_urls_without_sqlite_fallback(self) -> None:
        invalid_environments = (
            {},
            {_DATABASE_URL_ENV: ""},
            {_DATABASE_URL_ENV: "not-a-url"},
            {_DATABASE_URL_ENV: "sqlite+aiosqlite:///:memory:"},
            {
                _DATABASE_URL_ENV: (
                    "postgresql://console:password@db.internal/sentinel"
                )
            },
            {
                _DATABASE_URL_ENV: "mysql+asyncmy://console@db.internal/sentinel"
            },
        )
        for environment in invalid_environments:
            with self.subTest(configured=bool(environment)):
                with self.assertRaises(ConsoleDatabaseConfigurationError):
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
            database_runtime, "create_async_engine", return_value=engine
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
                database_runtime,
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
            database_runtime, "create_async_engine", return_value=engine
        ) as create:
            result = asyncio.run(
                database_runtime.create_runtime_database_engine(_LocatorStore())
            )

        self.assertIs(result, engine)
        options = create.call_args.kwargs
        self.assertEqual(options["connect_args"]["hostaddr"], "10.30.1.8")
        self.assertEqual(options["connect_args"]["sslmode"], "verify-full")

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

    def test_pinned_locator_uses_runtime_mysql_connector_with_tls_hostname(self) -> None:
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
        with patch.object(
            database_runtime,
            "create_pinned_mysql_async_creator",
            return_value=creator,
        ) as make_creator:
            with patch.object(
                database_runtime, "create_async_engine", return_value=engine
            ) as create:
                result = asyncio.run(
                    database_runtime.create_runtime_database_engine(
                        _LocatorStore()
                    )
                )

        self.assertIs(result, engine)
        self.assertEqual(make_creator.call_args.kwargs["hostname"], "db.internal")
        self.assertEqual(make_creator.call_args.kwargs["addresses"], ("10.30.1.8",))
        self.assertIs(create.call_args.kwargs["async_creator"], creator)


if __name__ == "__main__":
    unittest.main()
