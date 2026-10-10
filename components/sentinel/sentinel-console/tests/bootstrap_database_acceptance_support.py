"""Shared real-database acceptance for competing first-run transactions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import tempfile
from uuid import uuid4
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, insert, select, update
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
from atlas_richie.sentinel_console.application.runtime_database_locator import (
    RuntimeDatabaseLocator,
    RuntimeDatabaseTarget,
)
from atlas_richie.sentinel_console.domain.account_password import AccountPassword
from atlas_richie.sentinel_console.domain.account_username import AccountUsername
from atlas_richie.sentinel_console.domain.session import AccountRole
from atlas_richie.sentinel_console.infrastructure.persistence import (
    bootstrap_initialization_transaction as transaction_module,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    identity_composition,
    login_attempt_configuration,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_engine import (
    PreparedBootstrapDatabase,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_targets import (
    BootstrapDatabaseTargetPolicy,
    BootstrapDatabaseTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.persistence.database_runtime import (
    ConsoleDatabaseConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    bootstrap_authorization_file_authority,
    bootstrap_initialization_coordinator,
    first_run_composition,
    runtime_database_engine_provider,
    runtime_database_locator_configuration,
    setup_window_configuration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuthenticationSessionRecord,
    AuditEventRecord,
    ConsoleGuardRecord,
    InitializationOperationRecord,
    LoginAttemptRecord,
    RegisteredConfigurationSourceRecord,
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
from atlas_richie.sentinel_console.infrastructure.security import (
    registered_source_keys,
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
    transaction = (
        transaction_module.SqlAlchemyBootstrapInitializationTransaction(
            engine,
            operator_verifier=_OperatorVerifier(),
            source_secret_cipher=cipher,
            idempotency_key=b"i" * 32,
        )
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
            await connection.exec_driver_sql(
                _postgres_function_sql(function_name)
            )
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
                await connection.execute(
                    select(AccountRecord.__table__).where(
                        AccountRecord.username == admin_username,
                        AccountRecord.built_in.is_(True),
                    )
                )
            ).mappings().one()
            source = (
                await connection.execute(
                    select(RegisteredConfigurationSourceRecord.__table__).where(
                        RegisteredConfigurationSourceRecord.updated_by_account_id
                        == admin["account_id"]
                    )
                )
            ).mappings().one()
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
                await connection.execute(
                    select(InitializationOperationRecord.__table__).where(
                        InitializationOperationRecord.request_key.in_(request_keys)
                    )
                )
            ).mappings().all()
            audit_rows = (
                await connection.execute(
                    select(AuditEventRecord.__table__).where(
                        AuditEventRecord.request_id.in_(request_keys)
                    )
                )
            ).mappings().all()

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
                    == select(AccountRecord.account_id).where(
                        AccountRecord.username == admin_username,
                        AccountRecord.built_in.is_(True),
                    ).scalar_subquery()
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
            await connection.exec_driver_sql(
                _postgres_function_sql(function_name)
            )
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
                await connection.execute(
                    select(AccountRecord.__table__).where(
                        AccountRecord.username == admin_username,
                        AccountRecord.built_in.is_(True),
                    )
                )
            ).mappings().one()
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
                    == select(AccountRecord.account_id).where(
                        AccountRecord.username == admin_username,
                        AccountRecord.built_in.is_(True),
                    ).scalar_subquery()
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
    return f'''CREATE TRIGGER `{trigger_name}` BEFORE UPDATE ON console_guard
        FOR EACH ROW
        BEGIN
            IF OLD.initialized = FALSE AND NEW.initialized = TRUE THEN
                DO SLEEP(0.15);
            END IF;
        END'''


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
            if identity.get("accountId") != account_id or identity.get(
                "roleId"
            ) != AccountRole.ADMIN.value:
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

        async with engine.begin() as connection:
            account = (
                await connection.execute(
                    select(AccountRecord.__table__).where(
                        AccountRecord.account_id == account_id
                    )
                )
            ).mappings().one()
            sessions = (
                await connection.execute(
                    select(AuthenticationSessionRecord.__table__).where(
                        AuthenticationSessionRecord.account_id == account_id
                    )
                )
            ).mappings().all()
            audit = (
                await connection.execute(
                    select(AuditEventRecord.__table__).where(
                        AuditEventRecord.request_id == password_request_id
                    )
                )
            ).mappings().one()
            new_attempt_digests = set(
                (
                    await connection.scalars(
                        select(LoginAttemptRecord.client_identity_digest)
                    )
                ).all()
            ) - preexisting_attempt_digests

        if (
            not password_hasher.verify_password(
                account["password_hash"], new_password
            )
            or password_hasher.verify_password(
                account["password_hash"], original_password
            )
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
        if (
            audit["action"] != "auth.password.change"
            or audit["outcome"] != "completed"
        ):
            raise AssertionError("password change did not persist its audit fact")
        persisted_projection = repr(
            (dict(account), [dict(row) for row in sessions], dict(audit))
        )
        if any(
            secret in persisted_projection
            for secret in (original_password, new_password, first_session, csrf_token)
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
    initialization_body = {
        "requestKey": request_key,
        "input": {
            "database": {
                "kind": dialect,
                "host": "database.acceptance.invalid",
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
            database_target_policy=BootstrapDatabaseTargetPolicy(
                [
                    BootstrapDatabaseTargetRule.create(
                        _DATABASE_KIND[dialect],
                        "10.0.0.0/8",
                        frozenset({candidate_port}),
                    )
                ]
            ),
            bootstrap_idempotency_key=b"i" * 32,
            login_attempt_limit=(
                login_attempt_configuration.LoginAttemptLimitConfiguration(
                    5, 300, 300
                )
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
        )
        setup_window = configuration.setup_window.create_store()
        await setup_window.set_setup_window_open(True, expected_revision=None)

        async def create_test_target(_factory, candidate):
            locator_url = ConsoleDatabaseConfiguration.from_bootstrap_candidate(
                candidate
            ).secret_url_for_storage()
            return PreparedBootstrapDatabase(
                engine=create_async_engine(test_database_url),
                locator_database_url=locator_url,
                locator_target=RuntimeDatabaseTarget(
                    candidate.host or "database.acceptance.invalid",
                    ("192.0.2.42",),
                ),
            )

        def open_test_target(_locator):
            return create_async_engine(test_database_url)

        app = first_run_composition.build_first_run_sql_identity_app(configuration)
        with (
            patch.object(
                first_run_composition.BootstrapDatabaseEngineFactory,
                "create",
                create_test_target,
            ),
            patch.object(
                bootstrap_initialization_coordinator,
                "create_database_engine_from_locator",
                open_test_target,
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
                require(
                    gate.status_code == 200
                    and gate.json().get("initialized") is True,
                    "bootstrap gate did not close after first-run setup",
                )
                require(
                    receipt.status_code == 200
                    and receipt.json() == initialized.json(),
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
            require(
                locator.target is not None
                and locator.target.hostname == "database.acceptance.invalid"
                and locator.target.addresses == ("192.0.2.42",),
                "runtime locator did not preserve the approved database target",
            )
            runtime_engine = create_async_engine(test_database_url)
            runtime_engines.append(runtime_engine)
            return runtime_engine

        original_provider_init = (
            runtime_database_engine_provider.RuntimeDatabaseEngineProvider.__init__
        )

        def initialize_runtime_provider(provider, locator_store, **kwargs) -> None:
            kwargs.setdefault("engine_factory", create_runtime_engine)
            kwargs.setdefault("migration", upgrade_database)
            original_provider_init(provider, locator_store, **kwargs)

        with patch.object(
            runtime_database_engine_provider.RuntimeDatabaseEngineProvider,
            "__init__",
            new=initialize_runtime_provider,
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

        with (
            patch.object(AsyncEngine, "dispose", dispose_and_track),
            patch.object(
                bootstrap_initialization_coordinator,
                "create_database_engine_from_locator",
                open_test_target,
            ),
        ):
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
            await connection.execute(
                select(AccountRecord.__table__).where(
                    AccountRecord.username == admin_username,
                    AccountRecord.built_in.is_(True),
                )
            )
        ).mappings().one()
        operation = (
            await connection.execute(
                select(InitializationOperationRecord.__table__).where(
                    InitializationOperationRecord.request_key == request_key
                )
            )
        ).mappings().one()
        source = (
            await connection.execute(
                select(RegisteredConfigurationSourceRecord.__table__).where(
                    RegisteredConfigurationSourceRecord.endpoint == source_endpoint
                )
            )
        ).mappings().one()

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
