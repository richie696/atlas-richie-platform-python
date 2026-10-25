"""Shared real-database acceptance for competing first-run transactions."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import multiprocessing
import os
import shutil
import socket
import ssl
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient, TransportError
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.application.bootstrap_initialization import (
    BootstrapInitializationForbidden,
    BootstrapInitializationIdempotencyConflict,
    BootstrapInitializationInput,
    BootstrapInitializationReason,
    BootstrapInitializationStatus,
)
from atlas_richie.sentinel_console.application.bootstrap_source_check import (
    BootstrapSourceCandidate,
    BootstrapSourceProvider,
    NacosDirectCredentials,
)
from atlas_richie.sentinel_console.application.login_ports import (
    LoginAuthorityUnavailable,
)
from atlas_richie.sentinel_console.application.runtime_database_locator import (
    RuntimeDatabaseLocator,
    RuntimeDatabaseTarget,
)
from atlas_richie.sentinel_console.domain.account_password import AccountPassword
from atlas_richie.sentinel_console.domain.account_username import AccountUsername
from atlas_richie.sentinel_console.domain.session import AccountRole
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_engine import (
    PreparedBootstrapDatabase,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_targets import (
    BootstrapDatabaseTargetPolicy,
    BootstrapDatabaseTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    bootstrap_authorization_file_authority,
    first_run_composition,
    identity_composition,
    login_attempt_configuration,
    login_attempt_limiter,
    runtime_database_engine_provider,
    runtime_database_locator_configuration,
    setup_window_configuration,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    bootstrap_initialization_transaction as transaction_module,
)
from atlas_richie.sentinel_console.infrastructure.persistence.database_runtime import (
    ConsoleDatabaseConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    ConsoleGuardRecord,
    InitializationOperationRecord,
    LoginAttemptRecord,
    RegisteredConfigurationSourceRecord,
)
from atlas_richie.sentinel_console.infrastructure.security import (
    registered_source_keys,
)
from atlas_richie.sentinel_console.infrastructure.security.account_command_keys import (
    AccountCommandKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.client_identity_key import (
    ClientIdentityKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.password_hash import (
    PasswordHashService,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)

_OPERATOR_SESSION = "synthetic-database-acceptance-operator-session"
_SECOND_OPERATOR_SESSION = "synthetic-database-acceptance-second-operator"
_ADMIN_PASSWORD = "synthetic-first-admin-password-42"
_NACOS_PASSWORD = "synthetic-first-source-password-42"
_DATABASE_PASSWORD = "synthetic-database-password-42"
_DATABASE_KIND = {
    "postgresql": BootstrapDatabaseKind.POSTGRESQL,
    "mysql": BootstrapDatabaseKind.MYSQL,
}
_CONSOLE_ORIGIN = "https://console.acceptance.invalid"
_BootstrapAuthorizationConfiguration = (
    bootstrap_authorization_file_authority.BootstrapAuthorizationConfiguration
)
_FirstRunSqlIdentityConfiguration = (
    first_run_composition.FirstRunSqlIdentityConfiguration
)
_RegisteredSourceKeyConfiguration = (
    registered_source_keys.RegisteredSourceKeyConfiguration
)
_RuntimeDatabaseLocatorConfiguration = (
    runtime_database_locator_configuration.RuntimeDatabaseLocatorConfiguration
)
_SetupWindowConfiguration = setup_window_configuration.SetupWindowConfiguration


async def assert_two_uvicorn_workers_serve_sql_login_cooldown(
    test_case: unittest.TestCase,
    engine: AsyncEngine,
    database_url_value: str,
    database_kind: str,
) -> None:
    """Verify login cooldown across a two-worker CLI and a second CLI process."""
    from test_first_run_deployment_configuration import (
        _environment as first_run_environment,
    )

    database_url = make_url(database_url_value)
    test_case.assertIsNotNone(database_url.port)
    origin = "https://console.acceptance.invalid"
    state_directory = Path(
        tempfile.mkdtemp(
            prefix="sentinel-console-two-worker-",
            dir=Path(tempfile.gettempdir()).resolve(),
        )
    )
    environment = first_run_environment()
    postgresql_root_certificate = os.environ.get(
        "SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE"
    )
    if postgresql_root_certificate is not None:
        environment["SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE"] = (
            postgresql_root_certificate
        )
    environment.update(
        {
            "SENTINEL_CONSOLE_SETUP_WINDOW_PATH": str(
                state_directory / "setup-window.json"
            ),
            "SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH": str(
                state_directory / "runtime-locator.json"
            ),
            "SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH": str(
                state_directory / "bootstrap-authority.json"
            ),
            "SENTINEL_CONSOLE_BOOTSTRAP_INITIALIZATION_LOCK_PATH": str(
                state_directory / "initialize.lock"
            ),
            "SENTINEL_CONSOLE_BOOTSTRAP_DATABASE_TARGETS": (
                f"{database_kind}|127.0.0.1/32|{database_url.port}"
            ),
            "SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS": origin,
            "SENTINEL_CONSOLE_LOGIN_FAILURE_THRESHOLD": "2",
            "SENTINEL_CONSOLE_LOGIN_FAILURE_WINDOW_SECONDS": "300",
            "SENTINEL_CONSOLE_LOGIN_BLOCK_DURATION_SECONDS": "120",
        }
    )
    processes: list[asyncio.subprocess.Process] = []
    server_outputs: list[str] = []
    suffix = uuid4().hex
    csrf = f"acceptance-{suffix}-csrf-value-long-enough-0001"
    username = f"missing-worker-http-{suffix}"
    client_digest = hmac.new(
        base64.b64decode(environment["SENTINEL_CONSOLE_CLIENT_IDENTITY_HMAC_KEY"]),
        b"127.0.0.1",
        hashlib.sha256,
    ).hexdigest()
    guard_marked_initialized = False

    def reserve_port() -> int:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    async def start_server(worker_count: int) -> tuple[asyncio.subprocess.Process, int]:
        port = reserve_port()
        server_environment = {
            **environment,
            "SENTINEL_CONSOLE_BIND_HOST": "127.0.0.1",
            "SENTINEL_CONSOLE_PORT": str(port),
            "SENTINEL_CONSOLE_WORKERS": str(worker_count),
        }
        inherited_python_path = server_environment.get("PYTHONPATH", "")
        server_environment["PYTHONPATH"] = os.pathsep.join(
            part for part in (source_directory, inherited_python_path) if part
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "atlas_richie.sentinel_console",
            "serve",
            cwd=str(Path(__file__).resolve().parents[1]),
            env={**os.environ, **server_environment},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        processes.append(process)
        return process, port

    async def wait_for_bootstrap(
        client: AsyncClient, process: asyncio.subprocess.Process, request_id: str
    ) -> None:
        deadline = asyncio.get_running_loop().time() + 45
        while asyncio.get_running_loop().time() < deadline:
            if process.returncode is not None:
                break
            try:
                response = await client.get(
                    "/api/v1/system/bootstrap",
                    headers={"x-request-id": request_id},
                )
                if response.status_code == 200:
                    test_case.assertTrue(response.json()["initialized"])
                    return
            except TransportError:
                pass
            await asyncio.sleep(0.1)
        test_case.fail("a real Console CLI process did not serve initialized bootstrap")

    try:
        runtime_locator = _RuntimeDatabaseLocatorConfiguration.from_environment(
            environment
        )
        await runtime_locator.create_store().write(
            database_url_value,
            expected_revision=None,
            target=RuntimeDatabaseTarget("127.0.0.1", ("127.0.0.1",)),
        )
        async with engine.begin() as connection:
            await connection.execute(
                update(ConsoleGuardRecord)
                .where(ConsoleGuardRecord.singleton_id == 1)
                .values(
                    initialized=True,
                    revision=1,
                    initialized_at=datetime.now(UTC),
                )
            )
        guard_marked_initialized = True

        source_directory = str(Path(__file__).resolve().parents[1] / "src")
        first_process, first_port = await start_server(worker_count=2)
        second_process, second_port = await start_server(worker_count=1)

        async with (
            AsyncClient(base_url=f"http://127.0.0.1:{first_port}") as first_client,
            AsyncClient(base_url=f"http://127.0.0.1:{second_port}") as second_client,
        ):
            await wait_for_bootstrap(
                first_client, first_process, f"worker-a-bootstrap-{suffix}"
            )
            await wait_for_bootstrap(
                second_client, second_process, f"worker-b-bootstrap-{suffix}"
            )

            async def failed_login(client: AsyncClient, index: int):
                return await client.post(
                    "/api/v1/auth/login",
                    headers={
                        "origin": origin,
                        "cookie": f"__Host-sentinel_csrf={csrf}",
                        "x-sentinel-csrf": csrf,
                        "x-request-id": f"worker-login-{suffix}-{index}",
                    },
                    json={
                        "username": username,
                        "password": f"synthetic-invalid-{index}-{suffix}",
                    },
                )

            first_rejected = await failed_login(first_client, 1)
            second_rejected = await failed_login(second_client, 2)
            test_case.assertEqual(first_rejected.status_code, 401)
            test_case.assertEqual(second_rejected.status_code, 401)

            # Process B has seen only one failure. Its next request can be
            # blocked only if the threshold includes process A's SQL write.
            blocked = await failed_login(second_client, 3)
            test_case.assertEqual(blocked.status_code, 429, blocked.text)
            test_case.assertEqual(blocked.json()["error"]["code"], "rate_limited")
            retry_after = blocked.json()["error"]["retryAfterMs"]
            test_case.assertGreaterEqual(retry_after, 1)
            test_case.assertLessEqual(retry_after, 120_000)
            test_case.assertNotIn(username, blocked.text)

        async with engine.connect() as connection:
            attempt = (
                await connection.execute(
                    select(
                        LoginAttemptRecord.failure_count,
                        LoginAttemptRecord.blocked_until_ms,
                    ).where(LoginAttemptRecord.client_identity_digest == client_digest)
                )
            ).one()
        test_case.assertEqual(attempt.failure_count, 2)
        test_case.assertIsNotNone(attempt.blocked_until_ms)
    finally:
        for process in processes:
            if process.returncode is None:
                process.terminate()
            try:
                output, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            except TimeoutError:
                process.kill()
                output, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            server_outputs.append(output.decode("utf-8", errors="replace"))
        async with engine.begin() as connection:
            await connection.execute(
                LoginAttemptRecord.__table__.delete().where(
                    LoginAttemptRecord.client_identity_digest == client_digest
                )
            )
            if guard_marked_initialized:
                await connection.execute(
                    update(ConsoleGuardRecord)
                    .where(ConsoleGuardRecord.singleton_id == 1)
                    .values(initialized=False, revision=0, initialized_at=None)
                )
        shutil.rmtree(state_directory)

    test_case.assertEqual(
        server_outputs[0].count("Started server process"),
        2,
        "the first real CLI must start both configured worker processes",
    )
    test_case.assertEqual(
        server_outputs[1].count("Started server process"),
        1,
        "the second real CLI must start its independent server process",
    )


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return opaque_session in {_OPERATOR_SESSION, _SECOND_OPERATOR_SESSION}


class _InitializedReader:
    async def is_initialized(self) -> bool:
        return True


class _ClosedSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


async def assert_competing_bootstrap_initializations_are_serialized(
    engine: AsyncEngine, dialect: str
) -> None:
    """Prove one bootstrap commits while its competing request sees closure."""
    if dialect not in _DATABASE_KIND:
        raise ValueError("database acceptance dialect is unsupported")

    suffix = uuid4().hex
    admin_username = f"bootstrap-admin-{suffix}"
    request_keys = (f"db-bootstrap-{suffix}-a", f"db-bootstrap-{suffix}-b")
    trigger_name = f"sentinel_test_bootstrap_pause_{suffix}"
    function_name = trigger_name
    cipher = AesGcmSecretCipher("acceptance-v1", {"acceptance-v1": b"s" * 32})
    transaction = transaction_module.SqlAlchemyBootstrapInitializationTransaction(
        engine,
        operator_verifier=_OperatorVerifier(),
        source_secret_cipher=cipher,
        idempotency_key=b"i" * 32,
    )
    initialization_input = BootstrapInitializationInput(
        database=BootstrapDatabaseCandidate(
            kind=_DATABASE_KIND[dialect],
            host="127.0.0.1",
            port=5432 if dialect == "postgresql" else 3306,
            database=f"sentinel_console_test_{suffix}",
            username="synthetic-operator",
            password=_DATABASE_PASSWORD,
        ),
        admin_username=AccountUsername(admin_username),
        admin_password=AccountPassword(_ADMIN_PASSWORD),
        source=BootstrapSourceCandidate(
            provider=BootstrapSourceProvider.NACOS,
            endpoint="https://nacos.invalid:8848",
            location="sentinel",
            authentication=NacosDirectCredentials(
                "synthetic-operator", _NACOS_PASSWORD
            ),
        ),
    )

    async with engine.begin() as connection:
        initialized = await connection.scalar(
            select(ConsoleGuardRecord.initialized).where(
                ConsoleGuardRecord.singleton_id == 1
            )
        )
        if initialized is not False:
            raise AssertionError("the dedicated database must be uninitialized")
        if dialect == "postgresql":
            await connection.exec_driver_sql(_postgres_function_sql(function_name))
            await connection.exec_driver_sql(
                _postgres_trigger_sql(trigger_name, function_name)
            )
        else:
            await connection.exec_driver_sql(_mysql_trigger_sql(trigger_name))

    try:
        start = asyncio.Event()

        async def initialize(index: int):
            await start.wait()
            return await transaction.initialize(
                operator_session=_OPERATOR_SESSION,
                request_key=request_keys[index],
                input=initialization_input,
            )

        tasks = [asyncio.create_task(initialize(index)) for index in range(2)]
        start.set()
        receipts = await asyncio.gather(*tasks)
        if sorted(receipt.status.value for receipt in receipts) != [
            BootstrapInitializationStatus.COMPLETED.value,
            BootstrapInitializationStatus.REJECTED.value,
        ]:
            raise AssertionError("competing bootstrap requests had unexpected outcomes")
        rejected = next(
            receipt
            for receipt in receipts
            if receipt.status is BootstrapInitializationStatus.REJECTED
        )
        if rejected.reason is not BootstrapInitializationReason.SETUP_CLOSED:
            raise AssertionError("losing bootstrap request was not rejected as closed")

        async with engine.begin() as connection:
            initialized = await connection.scalar(
                select(ConsoleGuardRecord.initialized).where(
                    ConsoleGuardRecord.singleton_id == 1
                )
            )
            operation_count = await connection.scalar(
                select(func.count())
                .select_from(InitializationOperationRecord)
                .where(InitializationOperationRecord.request_key.in_(request_keys))
            )
            audit_count = await connection.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(AuditEventRecord.request_id.in_(request_keys))
            )
            admin = (
                (
                    await connection.execute(
                        select(AccountRecord.__table__).where(
                            AccountRecord.username == admin_username,
                            AccountRecord.built_in.is_(True),
                        )
                    )
                )
                .mappings()
                .one()
            )
            source = (
                (
                    await connection.execute(
                        select(RegisteredConfigurationSourceRecord.__table__).where(
                            RegisteredConfigurationSourceRecord.updated_by_account_id
                            == admin["account_id"]
                        )
                    )
                )
                .mappings()
                .one()
            )
            admin_count = await connection.scalar(
                select(func.count())
                .select_from(AccountRecord)
                .where(
                    AccountRecord.username == admin_username,
                    AccountRecord.built_in.is_(True),
                )
            )
            source_count = await connection.scalar(
                select(func.count())
                .select_from(RegisteredConfigurationSourceRecord)
                .where(
                    RegisteredConfigurationSourceRecord.updated_by_account_id
                    == admin["account_id"]
                )
            )
            operation_rows = (
                (
                    await connection.execute(
                        select(InitializationOperationRecord.__table__).where(
                            InitializationOperationRecord.request_key.in_(request_keys)
                        )
                    )
                )
                .mappings()
                .all()
            )
            audit_rows = (
                (
                    await connection.execute(
                        select(AuditEventRecord.__table__).where(
                            AuditEventRecord.request_id.in_(request_keys)
                        )
                    )
                )
                .mappings()
                .all()
            )

        actual_counts = (
            initialized,
            admin_count,
            source_count,
            operation_count,
            audit_count,
        )
        if actual_counts != (
            True,
            1,
            1,
            2,
            2,
        ):
            raise AssertionError(
                "bootstrap transaction did not persist one safe winner: "
                f"{actual_counts!r}"
            )
        persisted_rows = repr(
            (
                dict(admin),
                dict(source),
                [dict(row) for row in operation_rows + audit_rows],
            )
        )
        for secret in (_ADMIN_PASSWORD, _NACOS_PASSWORD, _DATABASE_PASSWORD):
            if secret in persisted_rows:
                raise AssertionError("bootstrap persisted submitted credentials")
    finally:
        async with engine.begin() as connection:
            if dialect == "postgresql":
                await connection.exec_driver_sql(
                    f'DROP TRIGGER IF EXISTS "{trigger_name}" ON console_guard'
                )
                await connection.exec_driver_sql(
                    f'DROP FUNCTION IF EXISTS "{function_name}"()'
                )
            else:
                await connection.exec_driver_sql(
                    f"DROP TRIGGER IF EXISTS `{trigger_name}`"
                )
            await connection.execute(
                RegisteredConfigurationSourceRecord.__table__.delete().where(
                    RegisteredConfigurationSourceRecord.updated_by_account_id
                    == select(AccountRecord.account_id)
                    .where(
                        AccountRecord.username == admin_username,
                        AccountRecord.built_in.is_(True),
                    )
                    .scalar_subquery()
                )
            )
            await connection.execute(
                InitializationOperationRecord.__table__.delete().where(
                    InitializationOperationRecord.request_key.in_(request_keys)
                )
            )
            await connection.execute(
                AuditEventRecord.__table__.delete().where(
                    AuditEventRecord.request_id.in_(request_keys)
                )
            )
            await connection.execute(
                AccountRecord.__table__.delete().where(
                    AccountRecord.username == admin_username,
                    AccountRecord.built_in.is_(True),
                )
            )
            await connection.execute(
                ConsoleGuardRecord.__table__.update()
                .where(ConsoleGuardRecord.singleton_id == 1)
                .values(initialized=False, revision=0, initialized_at=None)
            )


async def assert_bootstrap_retries_are_deduplicated_and_actor_bound(
    engine: AsyncEngine, dialect: str
) -> None:
    """Prove exact retries recover once and conflicting retries are rejected."""
    if dialect not in _DATABASE_KIND:
        raise ValueError("database acceptance dialect is unsupported")

    suffix = uuid4().hex
    admin_username = f"bootstrap-retry-admin-{suffix}"
    request_key = f"db-bootstrap-retry-{suffix}"
    trigger_name = f"sentinel_retry_{suffix}"
    function_name = trigger_name
    cipher = AesGcmSecretCipher("acceptance-v1", {"acceptance-v1": b"s" * 32})

    def new_transaction():
        return transaction_module.SqlAlchemyBootstrapInitializationTransaction(
            engine,
            operator_verifier=_OperatorVerifier(),
            source_secret_cipher=cipher,
            idempotency_key=b"i" * 32,
        )

    transactions = (new_transaction(), new_transaction())
    initialization_input = BootstrapInitializationInput(
        database=BootstrapDatabaseCandidate(
            kind=_DATABASE_KIND[dialect],
            host="127.0.0.1",
            port=5432 if dialect == "postgresql" else 3306,
            database=f"sentinel_console_test_{suffix}",
            username="synthetic-operator",
            password=_DATABASE_PASSWORD,
        ),
        admin_username=AccountUsername(admin_username),
        admin_password=AccountPassword(_ADMIN_PASSWORD),
        source=BootstrapSourceCandidate(
            provider=BootstrapSourceProvider.NACOS,
            endpoint="https://nacos.invalid:8848",
            location="sentinel",
            authentication=NacosDirectCredentials(
                "synthetic-operator", _NACOS_PASSWORD
            ),
        ),
    )

    async with engine.begin() as connection:
        initialized = await connection.scalar(
            select(ConsoleGuardRecord.initialized).where(
                ConsoleGuardRecord.singleton_id == 1
            )
        )
        if initialized is not False:
            raise AssertionError("the dedicated database must be uninitialized")
        if dialect == "postgresql":
            await connection.exec_driver_sql(_postgres_function_sql(function_name))
            await connection.exec_driver_sql(
                _postgres_trigger_sql(trigger_name, function_name)
            )
        else:
            await connection.exec_driver_sql(_mysql_trigger_sql(trigger_name))

    try:
        start = asyncio.Event()

        async def initialize(index: int):
            await start.wait()
            return await transactions[index].initialize(
                operator_session=_OPERATOR_SESSION,
                request_key=request_key,
                input=initialization_input,
            )

        tasks = [asyncio.create_task(initialize(index)) for index in range(2)]
        start.set()
        receipts = await asyncio.gather(*tasks)
        if receipts[0] != receipts[1] or (
            receipts[0].status is not BootstrapInitializationStatus.COMPLETED
        ):
            raise AssertionError("an exact retry did not recover its original receipt")

        async with engine.begin() as connection:
            admin = (
                (
                    await connection.execute(
                        select(AccountRecord.__table__).where(
                            AccountRecord.username == admin_username,
                            AccountRecord.built_in.is_(True),
                        )
                    )
                )
                .mappings()
                .one()
            )
            operation_count = await connection.scalar(
                select(func.count())
                .select_from(InitializationOperationRecord)
                .where(InitializationOperationRecord.request_key == request_key)
            )
            audit_count = await connection.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(AuditEventRecord.request_id == request_key)
            )

        if operation_count != 1 or audit_count != 1:
            raise AssertionError("an exact retry duplicated durable side effects")

        restarted_transaction = new_transaction()
        recovered = await restarted_transaction.initialize(
            operator_session=_OPERATOR_SESSION,
            request_key=request_key,
            input=initialization_input,
        )
        persisted_receipt = await restarted_transaction.read(
            _OPERATOR_SESSION, request_key
        )
        if recovered != receipts[0] or persisted_receipt != receipts[0]:
            raise AssertionError("a reconstructed adapter lost the original receipt")

        changed_input = BootstrapInitializationInput(
            database=initialization_input.database,
            admin_username=initialization_input.admin_username,
            admin_password=AccountPassword(f"{_ADMIN_PASSWORD}-changed"),
            source=initialization_input.source,
        )
        try:
            await restarted_transaction.initialize(
                operator_session=_OPERATOR_SESSION,
                request_key=request_key,
                input=changed_input,
            )
        except BootstrapInitializationIdempotencyConflict:
            pass
        else:
            raise AssertionError("a changed input reused the original request key")

        try:
            await restarted_transaction.initialize(
                operator_session=_SECOND_OPERATOR_SESSION,
                request_key=request_key,
                input=initialization_input,
            )
        except BootstrapInitializationForbidden:
            pass
        else:
            raise AssertionError("a different operator recovered the receipt")

        persisted_rows = repr(dict(admin))
        for secret in (_ADMIN_PASSWORD, _NACOS_PASSWORD, _DATABASE_PASSWORD):
            if secret in persisted_rows:
                raise AssertionError("bootstrap persisted submitted credentials")
    finally:
        async with engine.begin() as connection:
            if dialect == "postgresql":
                await connection.exec_driver_sql(
                    f'DROP TRIGGER IF EXISTS "{trigger_name}" ON console_guard'
                )
                await connection.exec_driver_sql(
                    f'DROP FUNCTION IF EXISTS "{function_name}"()'
                )
            else:
                await connection.exec_driver_sql(
                    f"DROP TRIGGER IF EXISTS `{trigger_name}`"
                )
            await connection.execute(
                RegisteredConfigurationSourceRecord.__table__.delete().where(
                    RegisteredConfigurationSourceRecord.updated_by_account_id
                    == select(AccountRecord.account_id)
                    .where(
                        AccountRecord.username == admin_username,
                        AccountRecord.built_in.is_(True),
                    )
                    .scalar_subquery()
                )
            )
            await connection.execute(
                InitializationOperationRecord.__table__.delete().where(
                    InitializationOperationRecord.request_key == request_key
                )
            )
            await connection.execute(
                AuditEventRecord.__table__.delete().where(
                    AuditEventRecord.request_id == request_key
                )
            )
            await connection.execute(
                AccountRecord.__table__.delete().where(
                    AccountRecord.username == admin_username,
                    AccountRecord.built_in.is_(True),
                )
            )
            await connection.execute(
                ConsoleGuardRecord.__table__.update()
                .where(ConsoleGuardRecord.singleton_id == 1)
                .values(initialized=False, revision=0, initialized_at=None)
            )


def _postgres_function_sql(function_name: str) -> str:
    return f'''CREATE FUNCTION "{function_name}"() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF OLD.initialized = FALSE AND NEW.initialized = TRUE THEN
            PERFORM pg_sleep(0.15);
        END IF;
        RETURN NEW;
        END; $$'''


def _postgres_trigger_sql(trigger_name: str, function_name: str) -> str:
    return f'''CREATE TRIGGER "{trigger_name}" BEFORE UPDATE OF initialized
        ON console_guard FOR EACH ROW
        EXECUTE FUNCTION "{function_name}"()'''


def _mysql_trigger_sql(trigger_name: str) -> str:
    return f"""CREATE TRIGGER `{trigger_name}` BEFORE UPDATE ON console_guard
        FOR EACH ROW
        BEGIN
            IF OLD.initialized = FALSE AND NEW.initialized = TRUE THEN
                DO SLEEP(0.15);
            END IF;
        END"""


async def assert_sql_identity_http_persists_credentials_and_sessions(
    engine: AsyncEngine, dialect: str
) -> None:
    """Exercise the SQL-composed login and own-password HTTP path on real DBs."""
    if dialect not in _DATABASE_KIND:
        raise ValueError("database acceptance dialect is unsupported")

    suffix = uuid4().hex
    account_id = str(uuid4())
    username = f"identity-admin-{suffix}"
    request_prefix = f"sql-identity-{suffix}"
    csrf_token = f"synthetic-{suffix}-initial-csrf-token-0001"
    original_password = "synthetic-identity-original-password-42"
    new_password = "synthetic-identity-rotated-password-42"
    now = datetime.now(UTC)
    username_value = AccountUsername(username)
    password_hasher = PasswordHashService()
    preexisting_attempt_digests: set[str]
    new_attempt_digests: set[str] = set()
    logout_session_digest: str | None = None

    async with engine.begin() as connection:
        initialized = await connection.scalar(
            select(ConsoleGuardRecord.initialized).where(
                ConsoleGuardRecord.singleton_id == 1
            )
        )
        if initialized is not False:
            raise AssertionError("the dedicated database must be uninitialized")
        preexisting_attempt_digests = set(
            (
                await connection.scalars(
                    select(LoginAttemptRecord.client_identity_digest)
                )
            ).all()
        )
        await connection.execute(
            update(ConsoleGuardRecord)
            .where(ConsoleGuardRecord.singleton_id == 1)
            .values(initialized=True, revision=1, initialized_at=now)
        )
        await connection.execute(
            insert(AccountRecord).values(
                account_id=account_id,
                username=username,
                username_key=username_value.lookup_key,
                password_hash=password_hasher.hash_password(original_password),
                role_id=AccountRole.ADMIN.value,
                status="active",
                built_in=True,
                last_login_at=None,
                revision=1,
                created_at=now,
                updated_at=now,
            )
        )

    app = identity_composition.build_sql_identity_app(
        engine,
        attempt_limit=login_attempt_configuration.LoginAttemptLimitConfiguration(
            5, 300, 300
        ),
        account_command_keys=AccountCommandKeyConfiguration(
            "acceptance-v1", {"acceptance-v1": b"a" * 32}
        ),
        client_identity_key=ClientIdentityKeyConfiguration(b"c" * 32),
        session_ttl=timedelta(hours=8),
        setup_window_reader=_ClosedSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        bootstrap_initialization_reader=_InitializedReader(),
        allowed_browser_origins=frozenset({_CONSOLE_ORIGIN}),
    )
    password_request_id = f"{request_prefix}-change-password"
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url=_CONSOLE_ORIGIN,
        ) as client:
            client.cookies.set(
                "__Host-sentinel_csrf",
                csrf_token,
                domain="console.acceptance.invalid",
                path="/",
            )
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": original_password},
                headers={
                    "origin": _CONSOLE_ORIGIN,
                    "x-request-id": f"{request_prefix}-login",
                    "x-sentinel-csrf": csrf_token,
                },
            )
            if login.status_code != 200:
                raise AssertionError(f"real SQL login failed: {login.status_code}")
            identity = login.json()
            if (
                identity.get("accountId") != account_id
                or identity.get("roleId") != AccountRole.ADMIN.value
            ):
                raise AssertionError("login returned the wrong persisted identity")
            first_session = client.cookies.get("sentinel_session")
            current_csrf = login.headers.get("x-sentinel-csrf")
            if not first_session or not current_csrf:
                raise AssertionError("login did not issue browser session proof")
            if client.cookies.get("__Host-sentinel_csrf") != current_csrf:
                raise AssertionError("login response and browser CSRF cookie diverged")

            me = await client.get(
                "/api/v1/auth/me",
                headers={"x-request-id": f"{request_prefix}-me-before"},
            )
            if me.status_code != 200 or me.json() != identity:
                raise AssertionError("current-session read did not match login")

            changed = await client.post(
                "/api/v1/auth/password",
                json={
                    "currentPassword": original_password,
                    "newPassword": new_password,
                },
                headers={
                    "origin": _CONSOLE_ORIGIN,
                    "x-request-id": password_request_id,
                    "x-sentinel-csrf": current_csrf,
                },
            )
            if changed.status_code != 200:
                error_code = changed.json().get("error", {}).get("code")
                raise AssertionError(
                    "real SQL password change failed: "
                    f"{changed.status_code}/{error_code}"
                )
            if any(
                secret in changed.text
                for secret in (original_password, new_password, first_session)
            ):
                raise AssertionError("identity response exposed submitted secrets")

            anonymous = await client.get(
                "/api/v1/auth/me",
                headers={"x-request-id": f"{request_prefix}-me-revoked"},
            )
            if anonymous.status_code != 200 or anonymous.json() is not None:
                raise AssertionError("password change did not revoke old session")

            bootstrap = await client.get(
                "/api/v1/system/bootstrap",
                headers={"x-request-id": f"{request_prefix}-csrf-refresh"},
            )
            if bootstrap.status_code != 200:
                raise AssertionError("anonymous login could not refresh CSRF proof")
            refreshed_csrf = bootstrap.headers.get("x-sentinel-csrf")
            if not refreshed_csrf:
                raise AssertionError("bootstrap did not issue fresh CSRF proof")

            old_login = await client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": original_password},
                headers={
                    "origin": _CONSOLE_ORIGIN,
                    "x-request-id": f"{request_prefix}-login-old",
                    "x-sentinel-csrf": refreshed_csrf,
                },
            )
            if old_login.status_code != 401:
                error_code = old_login.json().get("error", {}).get("code")
                raise AssertionError(
                    "old password login had unexpected outcome: "
                    f"{old_login.status_code}/{error_code}"
                )

            new_login = await client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": new_password},
                headers={
                    "origin": _CONSOLE_ORIGIN,
                    "x-request-id": f"{request_prefix}-login-new",
                    "x-sentinel-csrf": refreshed_csrf,
                },
            )
            if new_login.status_code != 200:
                raise AssertionError("new password could not establish a session")
            final_identity = await client.get(
                "/api/v1/auth/me",
                headers={"x-request-id": f"{request_prefix}-me-after"},
            )
            if final_identity.json() != new_login.json():
                raise AssertionError("rotated credentials lost identity continuity")
            logout_session = client.cookies.get("sentinel_session")
            logout_csrf = client.cookies.get("__Host-sentinel_csrf")
            if not logout_session or not logout_csrf:
                raise AssertionError("confirmed login did not retain browser proofs")
            logout_session_digest = hashlib.sha256(
                logout_session.encode("ascii")
            ).hexdigest()
            logged_out = await client.post(
                "/api/v1/auth/logout",
                headers={
                    "origin": _CONSOLE_ORIGIN,
                    "x-request-id": f"{request_prefix}-logout",
                    "x-sentinel-csrf": logout_csrf,
                },
            )
            if logged_out.status_code != 204 or logged_out.content != b"":
                raise AssertionError("real SQL logout did not return an empty 204")
            deleted_cookies = logged_out.headers.get_list("set-cookie")
            if len(deleted_cookies) != 2 or any(
                "max-age=0" not in cookie.lower() for cookie in deleted_cookies
            ):
                raise AssertionError("logout did not expire both browser cookies")

            # Replaying a previously issued opaque proof must remain anonymous;
            # cookie deletion alone is not evidence of server-side revocation.
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url=_CONSOLE_ORIGIN,
            ) as stale_client:
                stale_client.cookies.set(
                    "sentinel_session",
                    logout_session,
                    domain="console.acceptance.invalid",
                    path="/",
                )
                stale_session = await stale_client.get(
                    "/api/v1/auth/me",
                    headers={"x-request-id": f"{request_prefix}-me-after-logout"},
                )
            if stale_session.status_code != 200 or stale_session.json() is not None:
                raise AssertionError("logout left the persisted session active")

        async with engine.begin() as connection:
            account = (
                (
                    await connection.execute(
                        select(AccountRecord.__table__).where(
                            AccountRecord.account_id == account_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            sessions = (
                (
                    await connection.execute(
                        select(AuthenticationSessionRecord.__table__).where(
                            AuthenticationSessionRecord.account_id == account_id
                        )
                    )
                )
                .mappings()
                .all()
            )
            audit = (
                (
                    await connection.execute(
                        select(AuditEventRecord.__table__).where(
                            AuditEventRecord.request_id == password_request_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            new_attempt_digests = (
                set(
                    (
                        await connection.scalars(
                            select(LoginAttemptRecord.client_identity_digest)
                        )
                    ).all()
                )
                - preexisting_attempt_digests
            )

        if not password_hasher.verify_password(
            account["password_hash"], new_password
        ) or password_hasher.verify_password(
            account["password_hash"], original_password
        ):
            raise AssertionError("database password hash did not rotate correctly")
        session_hashes = {session["session_hash"] for session in sessions}
        csrf_hashes = {session["csrf_hash"] for session in sessions}
        if any(
            value in session_hashes or value in csrf_hashes
            for value in (first_session, csrf_token, current_csrf)
        ):
            raise AssertionError("database persisted raw session or CSRF material")
        if not any(session["revoked_at"] is not None for session in sessions):
            raise AssertionError("password update left the original session active")
        if logout_session_digest is None or not any(
            session["session_hash"] == logout_session_digest
            and session["revoked_at"] is not None
            for session in sessions
        ):
            raise AssertionError("logout did not persist revocation for its session")
        if audit["action"] != "auth.password.change" or audit["outcome"] != "completed":
            raise AssertionError("password change did not persist its audit fact")
        persisted_projection = repr(
            (dict(account), [dict(row) for row in sessions], dict(audit))
        )
        if any(
            secret in persisted_projection
            for secret in (
                original_password,
                new_password,
                first_session,
                logout_session or "",
                csrf_token,
            )
        ):
            raise AssertionError("identity persistence exposed credential material")
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                AuthenticationSessionRecord.__table__.delete().where(
                    AuthenticationSessionRecord.account_id == account_id
                )
            )
            await connection.execute(
                AuditEventRecord.__table__.delete().where(
                    AuditEventRecord.request_id == password_request_id
                )
            )
            await connection.execute(
                AccountRecord.__table__.delete().where(
                    AccountRecord.account_id == account_id
                )
            )
            if new_attempt_digests:
                await connection.execute(
                    LoginAttemptRecord.__table__.delete().where(
                        LoginAttemptRecord.client_identity_digest.in_(
                            new_attempt_digests
                        )
                    )
                )
            await connection.execute(
                update(ConsoleGuardRecord)
                .where(ConsoleGuardRecord.singleton_id == 1)
                .values(initialized=False, revision=0, initialized_at=None)
            )


async def assert_sql_login_cooldown_shared_across_app_instances(
    engine: AsyncEngine,
    database_url: str,
) -> None:
    """Prove two SQL-composed ASGI app instances share login cooldown state."""
    suffix = uuid4().hex
    account_id = str(uuid4())
    username = f"shared-limit-admin-{suffix}"
    password = "synthetic-shared-limit-password-42"
    request_prefix = f"shared-login-limit-{suffix}"
    browser_origin = _CONSOLE_ORIGIN
    client_identity_key = hashlib.sha256(
        f"synthetic-client-identity-key-{suffix}".encode("ascii")
    ).digest()
    command_key = hashlib.sha256(
        f"synthetic-account-command-key-{suffix}".encode("ascii")
    ).digest()
    limited_client_host = "198.51.100.27"
    separate_client_host = "192.0.2.41"
    limited_client_digest = hmac.new(
        client_identity_key,
        limited_client_host.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    separate_client_digest = hmac.new(
        client_identity_key,
        separate_client_host.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    second_engine = create_async_engine(database_url, pool_size=2)
    password_hasher = PasswordHashService()
    policy = login_attempt_configuration.LoginAttemptLimitConfiguration(2, 300, 120)
    csrf_values = (
        f"synthetic-{suffix}-csrf-for-limited-client-0001",
        f"synthetic-{suffix}-csrf-for-separated-client-0001",
    )

    def build_app(app_engine: AsyncEngine):
        return identity_composition.build_sql_identity_app(
            app_engine,
            attempt_limit=policy,
            account_command_keys=AccountCommandKeyConfiguration(
                "acceptance-v1", {"acceptance-v1": command_key}
            ),
            client_identity_key=ClientIdentityKeyConfiguration(client_identity_key),
            session_ttl=timedelta(hours=1),
            setup_window_reader=_ClosedSetupWindow(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            bootstrap_initialization_reader=_InitializedReader(),
            allowed_browser_origins=frozenset({browser_origin}),
        )

    async def login(client: AsyncClient, *, request_id: str, supplied_password: str):
        return await client.post(
            "/api/v1/auth/login",
            headers={
                "origin": browser_origin,
                "x-sentinel-csrf": client.cookies.get("__Host-sentinel_csrf"),
                "x-request-id": request_id,
            },
            json={"username": username, "password": supplied_password},
        )

    try:
        async with engine.begin() as connection:
            initialized = await connection.scalar(
                select(ConsoleGuardRecord.initialized).where(
                    ConsoleGuardRecord.singleton_id == 1
                )
            )
            if initialized is not False:
                raise AssertionError("the dedicated database must be uninitialized")
            await connection.execute(
                update(ConsoleGuardRecord)
                .where(ConsoleGuardRecord.singleton_id == 1)
                .values(initialized=True, revision=1, initialized_at=datetime.now(UTC))
            )
            await connection.execute(
                insert(AccountRecord).values(
                    account_id=account_id,
                    username=username,
                    username_key=AccountUsername(username).lookup_key,
                    password_hash=password_hasher.hash_password(password),
                    role_id=AccountRole.ADMIN.value,
                    status="active",
                    built_in=False,
                    last_login_at=None,
                    revision=1,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )

        first_app = build_app(engine)
        second_app = build_app(second_engine)
        async with (
            AsyncClient(
                transport=ASGITransport(
                    app=first_app, client=(limited_client_host, 49001)
                ),
                base_url=browser_origin,
            ) as first_worker,
            AsyncClient(
                transport=ASGITransport(
                    app=second_app, client=(limited_client_host, 49002)
                ),
                base_url=browser_origin,
            ) as second_worker,
            AsyncClient(
                transport=ASGITransport(
                    app=second_app, client=(separate_client_host, 49003)
                ),
                base_url=browser_origin,
            ) as independent_client,
        ):
            for client, csrf in zip(
                (first_worker, second_worker, independent_client),
                (csrf_values[0], csrf_values[0], csrf_values[1]),
                strict=True,
            ):
                client.cookies.set("__Host-sentinel_csrf", csrf)

            rejected_responses = await asyncio.gather(
                login(
                    first_worker,
                    request_id=f"{request_prefix}-failure-0",
                    supplied_password="synthetic-wrong-password-42",
                ),
                login(
                    second_worker,
                    request_id=f"{request_prefix}-failure-1",
                    supplied_password="synthetic-wrong-password-42",
                ),
            )
            for rejected in rejected_responses:
                if rejected.status_code != 401:
                    raise AssertionError(
                        "concurrent failures reaching the threshold must retain generic 401"
                    )
                if any(
                    secret in rejected.text
                    for secret in (username, password, "synthetic-wrong-password-42")
                ):
                    raise AssertionError("login failure exposed credential material")

            blocked = await login(
                second_worker,
                request_id=f"{request_prefix}-valid-but-limited",
                supplied_password=password,
            )
            if blocked.status_code != 429:
                raise AssertionError(
                    "a second SQL app instance did not observe the shared cooldown"
                )
            blocked_body = blocked.json()
            blocked_error = blocked_body.get("error", {})
            retry_after_ms = blocked_error.get("retryAfterMs")
            if (
                blocked_error.get("code") != "rate_limited"
                or isinstance(retry_after_ms, bool)
                or not isinstance(retry_after_ms, int)
                or not 1 <= retry_after_ms <= 120_000
            ):
                raise AssertionError("shared cooldown returned an invalid retry hint")
            if password in blocked.text or username in blocked.text:
                raise AssertionError("rate-limit response exposed identity material")

            independent_login = await login(
                independent_client,
                request_id=f"{request_prefix}-separate-client",
                supplied_password=password,
            )
            if independent_login.status_code != 200:
                raise AssertionError(
                    "one client's cooldown incorrectly blocked another client"
                )

        async with engine.begin() as connection:
            row_result = await connection.execute(
                select(
                    LoginAttemptRecord.client_identity_digest,
                    LoginAttemptRecord.failure_count,
                    LoginAttemptRecord.blocked_until_ms,
                ).where(
                    LoginAttemptRecord.client_identity_digest == limited_client_digest
                )
            )
            row = row_result.mappings().one_or_none()
            if (
                row is None
                or row["failure_count"] != 2
                or row["blocked_until_ms"] is None
                or row["client_identity_digest"] != limited_client_digest
            ):
                raise AssertionError("shared cooldown state was not persisted safely")
            if username in str(dict(row)) or limited_client_host in str(dict(row)):
                raise AssertionError("raw login identity was persisted")

            now_ms = int(datetime.now(UTC).timestamp() * 1000)
            await connection.execute(
                update(LoginAttemptRecord)
                .where(
                    LoginAttemptRecord.client_identity_digest == limited_client_digest
                )
                .values(blocked_until_ms=now_ms - 1)
            )

        async with AsyncClient(
            transport=ASGITransport(
                app=second_app, client=(limited_client_host, 49004)
            ),
            base_url=browser_origin,
        ) as recovered_client:
            recovered_client.cookies.set("__Host-sentinel_csrf", csrf_values[0])
            recovered = await login(
                recovered_client,
                request_id=f"{request_prefix}-cooldown-expired",
                supplied_password=password,
            )
        if recovered.status_code != 200:
            raise AssertionError("shared SQL cooldown did not recover after expiry")

        async with engine.connect() as connection:
            remaining = await connection.scalar(
                select(func.count())
                .select_from(LoginAttemptRecord)
                .where(
                    LoginAttemptRecord.client_identity_digest.in_(
                        (limited_client_digest, separate_client_digest)
                    )
                )
            )
        if remaining != 0:
            raise AssertionError("a successful login did not clear its shared digest")
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                AuthenticationSessionRecord.__table__.delete().where(
                    AuthenticationSessionRecord.account_id == account_id
                )
            )
            await connection.execute(
                LoginAttemptRecord.__table__.delete().where(
                    LoginAttemptRecord.client_identity_digest.in_(
                        (limited_client_digest, separate_client_digest)
                    )
                )
            )
            await connection.execute(
                AccountRecord.__table__.delete().where(
                    AccountRecord.account_id == account_id
                )
            )
            await connection.execute(
                update(ConsoleGuardRecord)
                .where(ConsoleGuardRecord.singleton_id == 1)
                .values(initialized=False, revision=0, initialized_at=None)
            )
        await second_engine.dispose()


def _record_login_failures_in_process(
    database_url: str,
    digest: str,
    start_gate,
) -> None:
    """Use an independent spawned process and engine to mutate one test digest."""
    if not start_gate.wait(timeout=30):
        raise SystemExit(2)

    async def record_failures() -> None:
        process_engine = create_async_engine(database_url, pool_size=1)
        try:
            limiter = login_attempt_limiter.SqlAlchemyLoginAttemptLimiter(
                process_engine,
                policy=login_attempt_limiter.LoginAttemptLimitPolicy(
                    failure_threshold=4,
                    window=timedelta(minutes=5),
                    block_duration=timedelta(minutes=2),
                ),
            )
            await limiter.record_failure(digest)
            await limiter.record_failure(digest)
        finally:
            await process_engine.dispose()

    try:
        asyncio.run(record_failures())
    except (LoginAuthorityUnavailable, SQLAlchemyError, OSError, ValueError):
        raise SystemExit(1) from None


async def assert_sql_login_cooldown_serializes_across_processes(
    engine: AsyncEngine,
    database_url: str,
) -> None:
    """Prove two OS processes serialize first failures in disposable SQL."""
    digest = hashlib.sha256(f"process-login-limit-{uuid4().hex}".encode()).hexdigest()
    context = multiprocessing.get_context("spawn")
    start_gate = context.Event()
    workers = [
        context.Process(
            target=_record_login_failures_in_process,
            args=(database_url, digest, start_gate),
        )
        for _ in range(2)
    ]

    async with engine.begin() as connection:
        await connection.execute(
            LoginAttemptRecord.__table__.delete().where(
                LoginAttemptRecord.client_identity_digest == digest
            )
        )

    try:
        for worker in workers:
            worker.start()
        start_gate.set()
        for worker in workers:
            worker.join(timeout=35)
        if any(worker.is_alive() for worker in workers):
            raise AssertionError("a spawned login limiter worker did not finish")
        if any(worker.exitcode != 0 for worker in workers):
            raise AssertionError("a spawned login limiter worker failed")

        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(
                            LoginAttemptRecord.failure_count,
                            LoginAttemptRecord.blocked_until_ms,
                        ).where(LoginAttemptRecord.client_identity_digest == digest)
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None or row["failure_count"] != 4 or row["blocked_until_ms"] is None:
            raise AssertionError("concurrent OS workers lost a persisted login failure")
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
            if worker.pid is not None and not worker.is_alive():
                worker.close()
        async with engine.begin() as connection:
            await connection.execute(
                LoginAttemptRecord.__table__.delete().where(
                    LoginAttemptRecord.client_identity_digest == digest
                )
            )


async def assert_first_run_http_persists_on_real_database(
    engine: AsyncEngine, dialect: str
) -> None:
    """Exercise authorized setup HTTP orchestration on a real SQL dialect."""
    if dialect not in _DATABASE_KIND:
        raise ValueError("database acceptance dialect is unsupported")

    test_database_url = engine.url
    if not test_database_url.database or not test_database_url.username:
        raise AssertionError("the disposable database URL needs database credentials")

    suffix = uuid4().hex
    operator_code = f"synthetic-operator-{suffix}-000000000001"
    admin_username = f"first-run-admin-{suffix}"
    admin_password = f"synthetic-admin-password-{suffix}-42"
    database_password = f"synthetic-database-password-{suffix}-42"
    source_token = f"synthetic-consul-token-{suffix}-42"
    request_key = f"first-run-http-{suffix}"
    initialize_request_id = f"{request_key}-initialize"
    source_endpoint = f"https://consul-{suffix}.acceptance.invalid:8501"
    origin = _CONSOLE_ORIGIN
    candidate_port = 5432 if dialect == "postgresql" else 3306
    postgresql_check_host = os.environ.get("SENTINEL_E2E_POSTGRES_HOST")
    postgresql_check_port_value = os.environ.get("SENTINEL_E2E_POSTGRES_PORT")
    postgresql_root_certificate = os.environ.get(
        "SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE"
    )
    postgresql_check_port = (
        int(postgresql_check_port_value)
        if postgresql_check_port_value is not None
        else None
    )
    if (
        dialect == "postgresql"
        and postgresql_check_host == "127.0.0.1"
        and postgresql_check_port is not None
        and postgresql_root_certificate is not None
    ):
        candidate_port = postgresql_check_port
    mysql_check_host = os.environ.get("SENTINEL_E2E_MYSQL_HOST")
    mysql_check_port_value = os.environ.get("SENTINEL_E2E_MYSQL_PORT")
    mysql_root_certificate = os.environ.get("SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE")
    mysql_check_port = (
        int(mysql_check_port_value) if mysql_check_port_value is not None else None
    )
    database_target_rules = [
        BootstrapDatabaseTargetRule.create(
            _DATABASE_KIND[dialect],
            "10.0.0.0/8",
            frozenset({candidate_port}),
        )
    ]
    if (
        dialect == "postgresql"
        and postgresql_check_host == "127.0.0.1"
        and postgresql_check_port is not None
        and postgresql_root_certificate is not None
    ):
        database_target_rules.append(
            BootstrapDatabaseTargetRule.create(
                BootstrapDatabaseKind.POSTGRESQL,
                "127.0.0.1/32",
                frozenset({postgresql_check_port}),
            )
        )
    mysql_ssl_context = None
    if (
        dialect == "mysql"
        and mysql_check_host == "127.0.0.1"
        and mysql_check_port is not None
        and mysql_root_certificate is not None
    ):
        database_target_rules.append(
            BootstrapDatabaseTargetRule.create(
                BootstrapDatabaseKind.MYSQL,
                "127.0.0.1/32",
                frozenset({mysql_check_port}),
            )
        )
        mysql_ssl_context = ssl.create_default_context(cafile=mysql_root_certificate)
    initialization_body = {
        "requestKey": request_key,
        "input": {
            "database": {
                "kind": dialect,
                "host": (
                    postgresql_check_host
                    if dialect == "postgresql" and postgresql_check_host is not None
                    else mysql_check_host
                    if dialect == "mysql" and mysql_check_host is not None
                    else "database.acceptance.invalid"
                ),
                "port": candidate_port,
                "database": test_database_url.database,
                "username": test_database_url.username,
                "password": database_password,
            },
            "admin": {
                "username": admin_username,
                "password": admin_password,
            },
            "source": {
                "provider": "consul",
                "endpoint": source_endpoint,
                "datacenter": "dc-test",
                "authentication": {
                    "mode": "direct",
                    "aclToken": source_token,
                },
            },
        },
    }

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(message)

    with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
        directory = Path(temporary)
        configuration = _FirstRunSqlIdentityConfiguration(
            setup_window=_SetupWindowConfiguration(directory / "setup.json"),
            runtime_locator=(
                _RuntimeDatabaseLocatorConfiguration(
                    directory / "runtime.json",
                    "runtime-active",
                    {"runtime-active": b"r" * 32},
                )
            ),
            bootstrap_authorization=(
                _BootstrapAuthorizationConfiguration(
                    directory / "operator.json", operator_code, b"o" * 32
                )
            ),
            initialization_lock_path=directory / "initialize.lock",
            database_target_policy=BootstrapDatabaseTargetPolicy(database_target_rules),
            bootstrap_idempotency_key=b"i" * 32,
            login_attempt_limit=(
                login_attempt_configuration.LoginAttemptLimitConfiguration(5, 300, 300)
            ),
            account_command_keys=AccountCommandKeyConfiguration(
                "acceptance-v1", {"acceptance-v1": b"a" * 32}
            ),
            client_identity_key=ClientIdentityKeyConfiguration(b"c" * 32),
            registered_source_keys=_RegisteredSourceKeyConfiguration(
                "source-active",
                {"source-active": b"s" * 32},
                "fingerprint-active",
                {"fingerprint-active": b"f" * 32},
            ),
            allowed_browser_origins=frozenset({origin}),
            mysql_ssl_context=mysql_ssl_context,
            postgresql_root_certificate=(
                postgresql_root_certificate if dialect == "postgresql" else None
            ),
        )
        setup_window = configuration.setup_window.create_store()
        await setup_window.set_setup_window_open(True, expected_revision=None)

        async def create_test_target(_factory, candidate):
            locator_url = ConsoleDatabaseConfiguration.from_bootstrap_candidate(
                candidate
            ).secret_url_for_storage()
            target_host = candidate.host or "database.acceptance.invalid"
            target_addresses = (
                ("127.0.0.1",) if target_host == "127.0.0.1" else ("192.0.2.42",)
            )
            return PreparedBootstrapDatabase(
                engine=create_async_engine(test_database_url),
                locator_database_url=locator_url,
                locator_target=RuntimeDatabaseTarget(
                    target_host,
                    target_addresses,
                ),
            )

        def open_test_target(_locator, **_options):
            return create_async_engine(test_database_url)

        with patch.object(
            first_run_composition,
            "create_database_engine_from_locator",
            open_test_target,
        ):
            app = first_run_composition.build_first_run_sql_identity_app(configuration)
        with (
            patch.object(
                first_run_composition.BootstrapDatabaseEngineFactory,
                "create",
                create_test_target,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url=origin
            ) as client:
                before = await client.get(
                    "/api/v1/system/bootstrap",
                    headers={"x-request-id": f"{request_key}-before"},
                )
                require(
                    before.status_code == 200
                    and before.json().get("initialized") is False,
                    "first-run app did not expose the uninitialized state",
                )
                authorized = await client.post(
                    "/api/v1/system/bootstrap/authorize",
                    json={"operatorCode": operator_code},
                    headers={
                        "origin": origin,
                        "x-request-id": f"{request_key}-authorize",
                        "x-sentinel-csrf": before.headers["x-sentinel-csrf"],
                    },
                )
                require(
                    authorized.status_code == 200,
                    "first-run operator authorization failed",
                )
                require(
                    operator_code not in authorized.text,
                    "authorization response exposed the operator code",
                )

                if (
                    dialect == "postgresql"
                    and postgresql_check_host == "127.0.0.1"
                    and postgresql_check_port is not None
                    and postgresql_root_certificate is not None
                ):
                    check_database = {
                        "kind": "postgresql",
                        "host": postgresql_check_host,
                        "port": postgresql_check_port,
                        "database": test_database_url.database,
                        "username": test_database_url.username,
                        "password": test_database_url.password,
                    }
                    invalid_check = await client.post(
                        "/api/v1/system/bootstrap/database-check",
                        json={
                            **check_database,
                            "password": "synthetic-invalid-postgresql-password",
                        },
                        headers={
                            "origin": origin,
                            "x-request-id": f"{request_key}-postgresql-auth-failure",
                            "x-sentinel-csrf": authorized.headers["x-sentinel-csrf"],
                        },
                    )
                    require(
                        invalid_check.status_code == 200
                        and invalid_check.json()
                        == {
                            "status": "unreachable",
                            "reason": "authentication",
                        },
                        "real PostgreSQL credential failure was not safely classified: "
                        f"{invalid_check.status_code} {invalid_check.text}",
                    )
                    require(
                        "synthetic-invalid-postgresql-password"
                        not in invalid_check.text,
                        "database-check response exposed submitted password",
                    )
                    reachable_check = await client.post(
                        "/api/v1/system/bootstrap/database-check",
                        json=check_database,
                        headers={
                            "origin": origin,
                            "x-request-id": f"{request_key}-postgresql-reachable",
                            "x-sentinel-csrf": authorized.headers["x-sentinel-csrf"],
                        },
                    )
                    require(
                        reachable_check.status_code == 200
                        and reachable_check.json() == {"status": "reachable"},
                        "real PostgreSQL TLS connectivity check did not succeed",
                    )
                    require(
                        (test_database_url.password or "") not in reachable_check.text,
                        "database-check response exposed database password",
                    )

                if (
                    dialect == "mysql"
                    and mysql_check_host == "127.0.0.1"
                    and mysql_check_port is not None
                    and mysql_root_certificate is not None
                ):
                    check_database = {
                        "kind": "mysql",
                        "host": mysql_check_host,
                        "port": mysql_check_port,
                        "database": test_database_url.database,
                        "username": test_database_url.username,
                        "password": test_database_url.password,
                    }
                    invalid_check = await client.post(
                        "/api/v1/system/bootstrap/database-check",
                        json={
                            **check_database,
                            "password": "synthetic-invalid-mysql-password",
                        },
                        headers={
                            "origin": origin,
                            "x-request-id": f"{request_key}-mysql-auth-failure",
                            "x-sentinel-csrf": authorized.headers["x-sentinel-csrf"],
                        },
                    )
                    require(
                        invalid_check.status_code == 200
                        and invalid_check.json()
                        == {
                            "status": "unreachable",
                            "reason": "authentication",
                        },
                        "real MySQL credential failure was not safely classified",
                    )
                    require(
                        "synthetic-invalid-mysql-password" not in invalid_check.text,
                        "database-check response exposed submitted password",
                    )

                    reachable_check = await client.post(
                        "/api/v1/system/bootstrap/database-check",
                        json=check_database,
                        headers={
                            "origin": origin,
                            "x-request-id": f"{request_key}-mysql-reachable",
                            "x-sentinel-csrf": authorized.headers["x-sentinel-csrf"],
                        },
                    )
                    require(
                        reachable_check.status_code == 200
                        and reachable_check.json() == {"status": "reachable"},
                        "real MySQL TLS connectivity check did not succeed",
                    )
                    require(
                        (test_database_url.password or "") not in reachable_check.text,
                        "database-check response exposed database password",
                    )

                initialized = await client.post(
                    "/api/v1/system/bootstrap/initialize",
                    json=initialization_body,
                    headers={
                        "origin": origin,
                        "x-request-id": initialize_request_id,
                        "x-sentinel-csrf": authorized.headers["x-sentinel-csrf"],
                        "idempotency-key": request_key,
                    },
                )
                require(
                    initialized.status_code == 200
                    and initialized.json().get("status") == "completed",
                    "real-dialect first-run initialization did not complete",
                )
                require(
                    all(
                        secret not in initialized.text
                        for secret in (
                            operator_code,
                            admin_password,
                            database_password,
                            source_token,
                        )
                    ),
                    "initialization response exposed submitted secret material",
                )
                gate = await client.get(
                    "/api/v1/system/bootstrap",
                    headers={"x-request-id": f"{request_key}-after"},
                )
                session = await client.get(
                    "/api/v1/auth/me",
                    headers={"x-request-id": f"{request_key}-session-after"},
                )
                receipt = await client.get(
                    f"/api/v1/system/bootstrap/operations/{request_key}",
                    headers={"x-request-id": f"{request_key}-receipt"},
                )
                repeated = await client.post(
                    "/api/v1/system/bootstrap/initialize",
                    json=initialization_body,
                    headers={
                        "origin": origin,
                        "x-request-id": f"{request_key}-repeat",
                        "x-sentinel-csrf": authorized.headers["x-sentinel-csrf"],
                        "idempotency-key": request_key,
                    },
                )
                async with engine.connect() as connection:
                    gate_database_value = await connection.scalar(
                        select(ConsoleGuardRecord.initialized).where(
                            ConsoleGuardRecord.singleton_id == 1
                        )
                    )
                require(
                    gate.status_code == 200 and gate.json().get("initialized") is True,
                    "bootstrap gate did not close after first-run setup: "
                    f"HTTP {gate.status_code}, initialized="
                    f"{gate.json().get('initialized')!r}, "
                    f"database_guard={gate_database_value!r}",
                )
                require(
                    session.status_code == 200 and session.json() is None,
                    "first-run initialization established a business login session",
                )
                require(
                    receipt.status_code == 200 and receipt.json() == initialized.json(),
                    "first-run operation receipt was not durably recoverable",
                )
                require(
                    repeated.status_code == 403,
                    "closed setup accepted a repeated initialization request",
                )

        locator_bytes = (directory / "runtime.json").read_bytes()
        authority_bytes = (directory / "operator.json").read_bytes()
        require(
            database_password.encode() not in locator_bytes,
            "runtime locator file exposed the database password",
        )
        require(
            operator_code.encode() not in authority_bytes,
            "operator authority file exposed the plaintext operator code",
        )

        runtime_engines: list[AsyncEngine] = []

        def create_runtime_engine(
            locator: RuntimeDatabaseLocator,
        ) -> AsyncEngine:
            loopback_target_was_approved = (
                dialect == "postgresql" and postgresql_check_host == "127.0.0.1"
            ) or (dialect == "mysql" and mysql_check_host == "127.0.0.1")
            expected_target = (
                ("127.0.0.1", ("127.0.0.1",))
                if loopback_target_was_approved
                else ("database.acceptance.invalid", ("192.0.2.42",))
            )
            require(
                locator.target is not None
                and locator.target.hostname == expected_target[0]
                and locator.target.addresses == expected_target[1],
                "runtime locator did not preserve the approved database target",
            )
            runtime_engine = create_async_engine(test_database_url)
            runtime_engines.append(runtime_engine)
            return runtime_engine

        original_provider_init = (
            runtime_database_engine_provider.RuntimeDatabaseEngineProvider.__init__
        )

        def initialize_runtime_provider(provider, locator_store, **kwargs) -> None:
            kwargs["engine_factory"] = create_runtime_engine
            kwargs["migration"] = upgrade_database
            original_provider_init(provider, locator_store, **kwargs)

        with (
            patch.object(
                runtime_database_engine_provider.RuntimeDatabaseEngineProvider,
                "__init__",
                new=initialize_runtime_provider,
            ),
            patch.object(
                first_run_composition,
                "create_database_engine_from_locator",
                open_test_target,
            ),
        ):
            restarted_app = first_run_composition.build_first_run_sql_identity_app(
                configuration
            )
        disposed_engines: list[AsyncEngine] = []
        original_dispose = AsyncEngine.dispose

        async def dispose_and_track(
            target: AsyncEngine, *, close: bool = False
        ) -> None:
            disposed_engines.append(target)
            await original_dispose(target, close=close)

        with patch.object(AsyncEngine, "dispose", dispose_and_track):
            async with restarted_app.router.lifespan_context(restarted_app):
                async with AsyncClient(
                    transport=ASGITransport(app=restarted_app), base_url=origin
                ) as restarted_client:
                    runtime_bootstrap = await restarted_client.get(
                        "/api/v1/system/bootstrap",
                        headers={"x-request-id": f"{request_key}-restart"},
                    )
                require(
                    runtime_bootstrap.status_code == 200
                    and runtime_bootstrap.json().get("initialized") is True,
                    "restarted first-run app did not read initialized runtime state",
                )
                require(
                    len(runtime_engines) == 1,
                    "runtime startup did not activate exactly one engine",
                )
                runtime_engine = runtime_engines[0]
                require(
                    runtime_engine.url.database == test_database_url.database,
                    "runtime engine did not target the disposable SQL database",
                )
                async with runtime_engine.connect() as connection:
                    runtime_initialized = await connection.scalar(
                        select(ConsoleGuardRecord.initialized).where(
                            ConsoleGuardRecord.singleton_id == 1
                        )
                    )
                require(
                    runtime_initialized is True,
                    "restarted runtime engine did not read initialized state",
                )

        require(
            disposed_engines.count(runtime_engines[0]) == 1,
            "ASGI shutdown did not dispose the runtime engine exactly once",
        )

    async with engine.connect() as connection:
        initialized_flag = await connection.scalar(
            select(ConsoleGuardRecord.initialized).where(
                ConsoleGuardRecord.singleton_id == 1
            )
        )
        admin = (
            (
                await connection.execute(
                    select(AccountRecord.__table__).where(
                        AccountRecord.username == admin_username,
                        AccountRecord.built_in.is_(True),
                    )
                )
            )
            .mappings()
            .one()
        )
        operation = (
            (
                await connection.execute(
                    select(InitializationOperationRecord.__table__).where(
                        InitializationOperationRecord.request_key == request_key
                    )
                )
            )
            .mappings()
            .one()
        )
        source = (
            (
                await connection.execute(
                    select(RegisteredConfigurationSourceRecord.__table__).where(
                        RegisteredConfigurationSourceRecord.endpoint == source_endpoint
                    )
                )
            )
            .mappings()
            .one()
        )

    password_hasher = PasswordHashService()
    persisted_projection = repr((dict(admin), dict(operation), dict(source)))
    require(initialized_flag is True, "database guard did not persist initialization")
    require(
        password_hasher.verify_password(admin["password_hash"], admin_password),
        "first admin password was not stored as a verifiable password hash",
    )
    require(
        source["credential_payload"] is not None
        and source_token not in persisted_projection
        and database_password not in persisted_projection
        and admin_password not in persisted_projection,
        "first-run persistence exposed a submitted secret",
    )
