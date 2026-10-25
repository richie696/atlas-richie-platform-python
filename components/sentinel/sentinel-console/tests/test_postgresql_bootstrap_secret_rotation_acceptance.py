"""Opt-in PostgreSQL, cross-process acceptance for source-key rotation."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.application.bootstrap_initialization import (
    BootstrapInitializationInput,
    BootstrapInitializationStatus,
)
from atlas_richie.sentinel_console.application.bootstrap_source_check import (
    BootstrapSourceCandidate,
    BootstrapSourceProvider,
    NacosDirectCredentials,
)
from atlas_richie.sentinel_console.application.check_registered_source import (
    RegisteredSourceCredentialsUnavailable,
)
from atlas_richie.sentinel_console.domain.account_password import AccountPassword
from atlas_richie.sentinel_console.domain.account_username import AccountUsername
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    bootstrap_initialization_transaction,
    registered_source_store,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.base import ConsoleBase
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    RegisteredConfigurationSourceRecord,
)
from atlas_richie.sentinel_console.infrastructure.security import registered_source_keys

_TEST_FILE = Path(__file__).resolve()
_DATABASE_URL_ENV = "SENTINEL_CONSOLE_TEST_POSTGRES_URL"
_TEST_KEY_PREFIX = "SENTINEL_B0_2_POSTGRES_TEST_"
_OLD_KEY = b"postgres-source-secret-key-v1-acceptance"[:32]
_NEW_KEY = b"postgres-source-secret-key-v2-acceptance"[:32]
_FINGERPRINT_KEY = b"postgres-source-fingerprint-acceptance"
_SOURCE_USERNAME = "synthetic-postgres-source-user"
_SOURCE_PASSWORD = "synthetic-postgres-source-password-never-log"
_ADMIN_PASSWORD = "synthetic-postgres-admin-password-never-log"
_OPERATOR_SESSION = "synthetic-postgres-bootstrap-operator-session"


def _validated_database_url(value: str | None) -> str | None:
    if value is None:
        return None
    url = make_url(value)
    if (
        url.drivername != "postgresql+psycopg"
        or not url.database
        or not url.database.startswith("sentinel_console_test_")
        or url.host not in {"127.0.0.1", "localhost", "postgres"}
    ):
        raise ValueError(
            f"{_DATABASE_URL_ENV} must target an isolated "
            "sentinel_console_test_* database"
        )
    return value


_DATABASE_URL = _validated_database_url(os.environ.get(_DATABASE_URL_ENV))


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return opaque_session == _OPERATOR_SESSION


class _PasswordHasher:
    def hash_password(self, password: str) -> str:
        return f"test-hash:{len(password)}"


def _key_environment(*, active_key_id: str, keys: dict[str, bytes]) -> dict[str, str]:
    def encode(value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    return {
        "SENTINEL_CONSOLE_SOURCE_SECRET_ACTIVE_KEY_ID": active_key_id,
        "SENTINEL_CONSOLE_SOURCE_SECRET_KEY_RING": ";".join(
            f"{key_id}={encode(key)}" for key_id, key in keys.items()
        ),
        "SENTINEL_CONSOLE_SOURCE_FINGERPRINT_ACTIVE_KEY_ID": "source-fingerprint-v1",
        "SENTINEL_CONSOLE_SOURCE_FINGERPRINT_KEY_RING": (
            "source-fingerprint-v1=" + encode(_FINGERPRINT_KEY)
        ),
    }


@unittest.skipUnless(
    _DATABASE_URL,
    f"set {_DATABASE_URL_ENV} to an isolated PostgreSQL acceptance database",
)
class PostgreSQLBootstrapSecretRotationAcceptanceTests(unittest.TestCase):
    """Exercise durable encrypted credentials through independent processes."""

    def test_restart_retains_old_key_and_missing_key_fails_closed(self) -> None:
        assert _DATABASE_URL is not None
        request_key = f"postgres-bootstrap-key-rotation-{os.urandom(12).hex()}"
        initialized = self._run_worker(
            "initialize",
            request_key=request_key,
            keys=_key_environment(
                active_key_id="source-v1", keys={"source-v1": _OLD_KEY}
            ),
        )
        source_id = initialized["sourceId"]
        revision = initialized["revision"]
        self.assertEqual(initialized["cipherKeyId"], "source-v1")

        resolved = self._run_worker(
            "resolve",
            source_id=source_id,
            revision=revision,
            keys=_key_environment(
                active_key_id="source-v2",
                keys={"source-v2": _NEW_KEY, "source-v1": _OLD_KEY},
            ),
        )
        self.assertEqual(resolved, {"resolved": True, "keyId": "source-v1"})

        missing_old_key = self._run_worker(
            "resolve-without-previous-key",
            source_id=source_id,
            revision=revision,
            keys=_key_environment(
                active_key_id="source-v2", keys={"source-v2": _NEW_KEY}
            ),
        )
        self.assertEqual(missing_old_key, {"failedClosed": True})

    def _run_worker(
        self,
        mode: str,
        *,
        keys: dict[str, str],
        request_key: str | None = None,
        source_id: str | None = None,
        revision: str | None = None,
    ) -> dict[str, object]:
        environment = os.environ.copy()
        environment.update(keys)
        environment["SENTINEL_B0_2_POSTGRES_WORKER_MODE"] = mode
        if request_key is not None:
            environment["SENTINEL_B0_2_POSTGRES_REQUEST_KEY"] = request_key
        if source_id is not None:
            environment["SENTINEL_B0_2_POSTGRES_SOURCE_ID"] = source_id
        if revision is not None:
            environment["SENTINEL_B0_2_POSTGRES_SOURCE_REVISION"] = revision

        result = subprocess.run(
            [sys.executable, str(_TEST_FILE)],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
            env=environment,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"isolated worker failed: {result.stdout.strip()}",
        )
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail("isolated worker did not return its bounded result")
        self.assertIsInstance(value, dict)
        return value


async def _worker_engine():
    database_url = os.environ[_DATABASE_URL_ENV]
    return create_async_engine(
        database_url,
        hide_parameters=True,
        pool_pre_ping=True,
    )


async def _initialize_worker() -> dict[str, object]:
    engine = await _worker_engine()
    try:
        # Migration acceptance shares this disposable schema; reset it so this
        # first-run test never inherits a completed initialization guard.
        async with engine.begin() as connection:
            await connection.run_sync(ConsoleBase.metadata.drop_all)
            await connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        await upgrade_database(engine)
        key_configuration = (
            registered_source_keys.RegisteredSourceKeyConfiguration.from_environment()
        )
        initializer = (
            bootstrap_initialization_transaction
            .SqlAlchemyBootstrapInitializationTransaction(
                engine,
                operator_verifier=_OperatorVerifier(),
                password_hasher=_PasswordHasher(),
                source_secret_cipher=key_configuration.create_secret_cipher(),
                idempotency_key=b"postgres-bootstrap-idempotency-key-v1",
            )
        )
        receipt = await initializer.initialize(
            operator_session=_OPERATOR_SESSION,
            request_key=os.environ["SENTINEL_B0_2_POSTGRES_REQUEST_KEY"],
            input=BootstrapInitializationInput(
                database=BootstrapDatabaseCandidate(BootstrapDatabaseKind.POSTGRESQL),
                admin_username=AccountUsername("bootstrap-admin"),
                admin_password=AccountPassword(_ADMIN_PASSWORD),
                source=BootstrapSourceCandidate(
                    provider=BootstrapSourceProvider.NACOS,
                    endpoint="https://nacos.synthetic.invalid:8848",
                    location="sentinel/postgres-bootstrap-secret-rotation",
                    authentication=NacosDirectCredentials(
                        _SOURCE_USERNAME, _SOURCE_PASSWORD
                    ),
                ),
            ),
        )
        if receipt.status is not BootstrapInitializationStatus.COMPLETED:
            raise RuntimeError("bootstrap did not complete")
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    select(RegisteredConfigurationSourceRecord.__table__).where(
                        RegisteredConfigurationSourceRecord.location
                        == "sentinel/postgres-bootstrap-secret-rotation"
                    )
                )
            ).mappings().one()
        if _SOURCE_PASSWORD in repr(dict(row)) or _ADMIN_PASSWORD in repr(receipt):
            raise RuntimeError("secret appeared in persisted projection")
        return {
            "sourceId": row["source_id"],
            "revision": row["revision"],
            "cipherKeyId": row["credential_key_id"],
        }
    finally:
        await engine.dispose()


async def _resolve_worker(*, require_previous_key: bool) -> dict[str, object]:
    engine = await _worker_engine()
    try:
        key_configuration = (
            registered_source_keys.RegisteredSourceKeyConfiguration.from_environment()
        )
        store = registered_source_store.SqlAlchemyRegisteredSourceStore(
            engine,
            secret_cipher=key_configuration.create_secret_cipher(),
            fingerprint_keys=key_configuration.fingerprint_keys,
            active_fingerprint_key_id=key_configuration.active_fingerprint_key_id,
        )
        try:
            credentials = await store.resolve_credentials(
                os.environ["SENTINEL_B0_2_POSTGRES_SOURCE_ID"],
                os.environ["SENTINEL_B0_2_POSTGRES_SOURCE_REVISION"],
                ConfigurationSourceProvider.NACOS,
            )
        except RegisteredSourceCredentialsUnavailable:
            if require_previous_key:
                return {"failedClosed": True}
            raise
        if require_previous_key:
            raise RuntimeError("credential resolved without the retained key")
        if (
            credentials is None
            or credentials.username != _SOURCE_USERNAME
            or credentials.password != _SOURCE_PASSWORD
            or credentials.endpoint != "https://nacos.synthetic.invalid:8848"
        ):
            raise RuntimeError("resolved credential did not match its owner")
        return {"resolved": True, "keyId": "source-v1"}
    finally:
        await engine.dispose()


def _run_worker_mode() -> None:
    mode = os.environ.get("SENTINEL_B0_2_POSTGRES_WORKER_MODE")
    try:
        if mode == "initialize":
            result = asyncio.run(_initialize_worker())
        elif mode == "resolve":
            result = asyncio.run(_resolve_worker(require_previous_key=False))
        elif mode == "resolve-without-previous-key":
            result = asyncio.run(_resolve_worker(require_previous_key=True))
        else:
            raise RuntimeError("worker mode is invalid")
    except Exception as error:
        print(
            json.dumps(
                {"workerFailed": True, "errorType": type(error).__name__},
                separators=(",", ":"),
            )
        )
        raise SystemExit(1)
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__" and os.environ.get(
    "SENTINEL_B0_2_POSTGRES_WORKER_MODE"
):
    _run_worker_mode()
