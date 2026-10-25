"""Real-MySQL, cross-process acceptance for bootstrap source-key rotation."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import ssl
import subprocess
import sys
import unittest
from pathlib import Path

from sqlalchemy import select
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
    registered_source_store,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.base import ConsoleBase
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    RegisteredConfigurationSourceRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    bootstrap_initialization_transaction as _bootstrap_transactions,
)
from atlas_richie.sentinel_console.infrastructure.security import (
    registered_source_keys as _registered_source_keys,
)
from sqlalchemy.engine import make_url

_TEST_FILE = Path(__file__).resolve()
_MYSQL_URL_ENV = "SENTINEL_CONSOLE_TEST_MYSQL_URL"
_MYSQL_CA_ENV = "SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"
_TEST_KEY_PREFIX = "SENTINEL_B0_2_TEST_"
_OLD_KEY = b"bootstrap-secret-key-v1-acceptance"[:32]
_NEW_KEY = b"bootstrap-secret-key-v2-acceptance"[:32]
_FINGERPRINT_KEY = b"bootstrap-source-fingerprint-acceptance"
_SOURCE_USERNAME = "synthetic-rotation-user"
_SOURCE_PASSWORD = "synthetic-mysql-bootstrap-source-password"
_ADMIN_PASSWORD = "synthetic-mysql-bootstrap-admin-password"
_OPERATOR_SESSION = "synthetic-mysql-bootstrap-operator-session"


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return opaque_session == _OPERATOR_SESSION


class _PasswordHasher:
    def hash_password(self, password: str) -> str:
        return f"test-hash:{len(password)}"


def _test_key_environment(
    *, active_secret_key_id: str, secret_keys: dict[str, bytes]
) -> dict[str, str]:
    prefix = _TEST_KEY_PREFIX

    def encode(value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    return {
        f"{prefix}SECRET_ACTIVE_KEY_ID": active_secret_key_id,
        f"{prefix}SECRET_KEY_RING": ";".join(
            f"{key_id}={encode(key)}" for key_id, key in secret_keys.items()
        ),
        f"{prefix}FINGERPRINT_ACTIVE_KEY_ID": "source-fingerprint-v1",
        f"{prefix}FINGERPRINT_KEY_RING": (
            "source-fingerprint-v1=" + encode(_FINGERPRINT_KEY)
        ),
    }


def _configure_source_keys(environment: dict[str, str]) -> None:
    prefix = _TEST_KEY_PREFIX
    environment[
        "SENTINEL_CONSOLE_SOURCE_SECRET_ACTIVE_KEY_ID"
    ] = environment.pop(f"{prefix}SECRET_ACTIVE_KEY_ID")
    environment["SENTINEL_CONSOLE_SOURCE_SECRET_KEY_RING"] = environment.pop(
        f"{prefix}SECRET_KEY_RING"
    )
    environment[
        "SENTINEL_CONSOLE_SOURCE_FINGERPRINT_ACTIVE_KEY_ID"
    ] = environment.pop(f"{prefix}FINGERPRINT_ACTIVE_KEY_ID")
    environment["SENTINEL_CONSOLE_SOURCE_FINGERPRINT_KEY_RING"] = environment.pop(
        f"{prefix}FINGERPRINT_KEY_RING"
    )


class MySqlBootstrapSecretRotationAcceptanceTests(unittest.TestCase):
    def test_restart_retains_old_key_and_missing_key_fails_closed(self) -> None:
        database_url = os.environ.get(_MYSQL_URL_ENV)
        root_certificate = os.environ.get(_MYSQL_CA_ENV)
        if not database_url or not root_certificate:
            self.skipTest(
                "run through with_disposable_e2e_dependencies.sh for real MySQL"
            )

        run_id = os.urandom(12).hex()
        request_key = f"mysql-bootstrap-key-rotation-{run_id}"
        initialization = self._run_worker(
            "initialize",
            request_key=request_key,
            key_environment=_test_key_environment(
                active_secret_key_id="source-v1",
                secret_keys={"source-v1": _OLD_KEY},
            ),
        )
        source_id = initialization["sourceId"]
        source_revision = initialization["revision"]
        self.assertTrue(initialization["tlsCipher"])
        self.assertEqual(initialization["cipherKeyId"], "source-v1")

        retained_key_runtime = self._run_worker(
            "resolve",
            source_id=source_id,
            revision=source_revision,
            key_environment=_test_key_environment(
                active_secret_key_id="source-v2",
                secret_keys={"source-v2": _NEW_KEY, "source-v1": _OLD_KEY},
            ),
        )
        self.assertEqual(retained_key_runtime, {"resolved": True, "keyId": "source-v1"})

        missing_old_key_runtime = self._run_worker(
            "resolve-without-previous-key",
            source_id=source_id,
            revision=source_revision,
            key_environment=_test_key_environment(
                active_secret_key_id="source-v2",
                secret_keys={"source-v2": _NEW_KEY},
            ),
        )
        self.assertEqual(missing_old_key_runtime, {"failedClosed": True})

    def _run_worker(
        self,
        mode: str,
        *,
        key_environment: dict[str, str],
        request_key: str | None = None,
        source_id: str | None = None,
        revision: str | None = None,
    ) -> dict[str, object]:
        environment = os.environ.copy()
        environment.update(key_environment)
        _configure_source_keys(environment)
        environment["SENTINEL_B0_2_WORKER_MODE"] = mode
        if request_key is not None:
            environment["SENTINEL_B0_2_REQUEST_KEY"] = request_key
        if source_id is not None:
            environment["SENTINEL_B0_2_SOURCE_ID"] = source_id
        if revision is not None:
            environment["SENTINEL_B0_2_SOURCE_REVISION"] = revision

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
    database_url = os.environ[_MYSQL_URL_ENV]
    url = make_url(database_url)
    if (
        url.drivername != "mysql+asyncmy"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database is None
        or not url.database.startswith("sentinel_console_test_")
    ):
        raise RuntimeError("worker requires the isolated loopback MySQL test database")
    root_certificate = os.environ[_MYSQL_CA_ENV]
    tls_context = ssl.create_default_context(cafile=root_certificate)
    engine = create_async_engine(
        database_url,
        connect_args={"ssl": tls_context},
        hide_parameters=True,
        pool_pre_ping=True,
    )
    async with engine.connect() as connection:
        status = await connection.exec_driver_sql(
            "SHOW SESSION STATUS LIKE 'Ssl_cipher'"
        )
        if not status.one()[1]:
            await engine.dispose()
            raise RuntimeError("TLS connection is required")
    return engine


async def _initialize_worker() -> dict[str, object]:
    engine = await _worker_engine()
    try:
        # Other MySQL acceptance classes share this disposable schema. Recreate
        # the isolated test schema so this first-run scenario always starts empty.
        async with engine.begin() as connection:
            await connection.run_sync(ConsoleBase.metadata.drop_all)
            await connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        await upgrade_database(engine)
        key_configuration = (
            _registered_source_keys.RegisteredSourceKeyConfiguration.from_environment()
        )
        initializer = (
            _bootstrap_transactions.SqlAlchemyBootstrapInitializationTransaction(
                engine,
                operator_verifier=_OperatorVerifier(),
                password_hasher=_PasswordHasher(),
                source_secret_cipher=key_configuration.create_secret_cipher(),
                idempotency_key=b"mysql-bootstrap-idempotency-key-v1",
            )
        )
        receipt = await initializer.initialize(
            operator_session=_OPERATOR_SESSION,
            request_key=os.environ["SENTINEL_B0_2_REQUEST_KEY"],
            input=BootstrapInitializationInput(
                database=BootstrapDatabaseCandidate(BootstrapDatabaseKind.MYSQL),
                admin_username=AccountUsername("bootstrap-admin"),
                admin_password=AccountPassword(_ADMIN_PASSWORD),
                source=BootstrapSourceCandidate(
                    provider=BootstrapSourceProvider.NACOS,
                    endpoint="https://nacos.synthetic.invalid:8848",
                    location="sentinel/bootstrap-secret-rotation",
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
                    select(RegisteredConfigurationSourceRecord.__table__)
                )
            ).mappings().one()
            status = await connection.exec_driver_sql(
                "SHOW SESSION STATUS LIKE 'Ssl_cipher'"
            )
            tls_cipher = status.one()[1]
        if _SOURCE_PASSWORD in repr(dict(row)) or _ADMIN_PASSWORD in repr(receipt):
            raise RuntimeError("secret appeared in persisted projection")
        return {
            "sourceId": row["source_id"],
            "revision": row["revision"],
            "cipherKeyId": row["credential_key_id"],
            "tlsCipher": tls_cipher,
        }
    finally:
        await engine.dispose()


async def _resolve_worker(*, require_previous_key: bool) -> dict[str, object]:
    engine = await _worker_engine()
    try:
        key_configuration = (
            _registered_source_keys.RegisteredSourceKeyConfiguration.from_environment()
        )
        store = registered_source_store.SqlAlchemyRegisteredSourceStore(
            engine,
            secret_cipher=key_configuration.create_secret_cipher(),
            fingerprint_keys=key_configuration.fingerprint_keys,
            active_fingerprint_key_id=key_configuration.active_fingerprint_key_id,
        )
        try:
            credentials = await store.resolve_credentials(
                os.environ["SENTINEL_B0_2_SOURCE_ID"],
                os.environ["SENTINEL_B0_2_SOURCE_REVISION"],
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
    mode = os.environ.get("SENTINEL_B0_2_WORKER_MODE")
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


if __name__ == "__main__":
    _run_worker_mode()

