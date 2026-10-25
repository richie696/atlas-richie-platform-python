"""Opt-in real-MySQL acceptance for registration receipt readback semantics."""

from __future__ import annotations

import hashlib
import os
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleKind
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.persistence.current_session_reader import (
    SqlAlchemyCurrentSessionReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuthenticationSessionRecord,
    RegisteredConfigurationSourceRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_registration_store import (
    SqlAlchemyRuleBindingRegistrationStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_directory_reader import (
    SqlAlchemyRuleBindingDirectoryReader,
)

_DATABASE_URL_ENV = "SENTINEL_CONSOLE_TEST_MYSQL_URL"
_DATABASE_URL = os.environ.get(_DATABASE_URL_ENV)
if _DATABASE_URL is not None:
    _parsed_url = make_url(_DATABASE_URL)
    if (
        _parsed_url.drivername != "mysql+asyncmy"
        or not _parsed_url.database
        or not _parsed_url.database.startswith("sentinel_console_test_")
        or _parsed_url.host not in {"127.0.0.1", "localhost", "mysql"}
    ):
        raise ValueError(
            f"{_DATABASE_URL_ENV} must target the owner-labeled disposable MySQL database"
        )


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _ClosedSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


@unittest.skipUnless(_DATABASE_URL, f"set {_DATABASE_URL_ENV} to run MySQL acceptance")
class MySQLRuleBindingRegistrationReceiptAcceptanceTest(
    unittest.IsolatedAsyncioTestCase
):
    """Exercise the actual SQL store and authenticated Console routes on MySQL."""

    async def asyncSetUp(self) -> None:
        assert _DATABASE_URL is not None
        self.engine = create_async_engine(_DATABASE_URL, pool_size=5)
        await upgrade_database(self.engine)
        self._cleanup_scope = None
        self._cleaned = False

    async def asyncTearDown(self) -> None:
        if self._cleanup_scope is not None and not self._cleaned:
            await self._cleanup(**self._cleanup_scope)
        await self.engine.dispose()

    async def test_mysql_receipt_read_survives_cookie_rotation_and_rechecks_scope(
        self,
    ) -> None:
        suffix = uuid4().hex
        now = datetime.now(UTC).replace(microsecond=0)
        actor_id = str(uuid4())
        other_actor_id = str(uuid4())
        original_cookie = f"receipt-original-{suffix}"
        rotated_cookie = f"receipt-rotated-{suffix}"
        other_cookie = f"receipt-other-{suffix}"
        original_csrf = f"receipt-csrf-{suffix}"
        original_digest = hashlib.sha256(original_cookie.encode("ascii")).hexdigest()
        rotated_digest = hashlib.sha256(rotated_cookie.encode("ascii")).hexdigest()
        other_digest = hashlib.sha256(other_cookie.encode("ascii")).hexdigest()
        csrf_digest = hashlib.sha256(original_csrf.encode("ascii")).hexdigest()
        source_id = f"nacos-{suffix}"
        source_revision = f"source-{suffix}"
        binding_id = f"binding-{suffix}"
        request_key = f"receipt-{suffix}"
        request_ids = (
            f"register-{suffix}",
            f"read-{suffix}",
            f"missing-{suffix}",
            f"cross-actor-{suffix}",
            f"demoted-{suffix}",
        )
        username = f"receipt-admin-{suffix}"
        other_username = f"receipt-other-admin-{suffix}"
        self._cleanup_scope = {
            "actor_id": actor_id,
            "other_actor_id": other_actor_id,
            "source_id": source_id,
            "binding_id": binding_id,
            "request_key": request_key,
            "request_ids": request_ids,
        }

        async with self.engine.begin() as connection:
            for identity, name, session_digests in (
                (actor_id, username, (original_digest, rotated_digest)),
                (other_actor_id, other_username, (other_digest,)),
            ):
                await connection.execute(
                    insert(AccountRecord).values(
                        account_id=identity,
                        username=name,
                        username_key=hashlib.sha256(name.encode("ascii")).hexdigest(),
                        password_hash="$argon2id$synthetic-mysql-receipt-test",
                        role_id="admin",
                        status="active",
                        built_in=False,
                        last_login_at=None,
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
                for session_digest in session_digests:
                    await connection.execute(
                        insert(AuthenticationSessionRecord).values(
                            session_hash=session_digest,
                            account_id=identity,
                            session_epoch=str(uuid4()),
                            csrf_hash=csrf_digest,
                            created_at=now,
                            expires_at=now + timedelta(hours=1),
                            revoked_at=None,
                        )
                    )
            await connection.execute(
                insert(RegisteredConfigurationSourceRecord).values(
                    source_id=source_id,
                    revision=source_revision,
                    name="Disposable receipt source",
                    endpoint="https://nacos.acceptance.invalid",
                    provider=ConfigurationSourceProvider.NACOS.value,
                    location="acceptance",
                    authentication_mode="none",
                    credential_configured=False,
                    credential_cipher_format=None,
                    credential_key_id=None,
                    credential_payload=None,
                    created_at=now,
                    updated_at=now,
                    updated_by_account_id=actor_id,
                )
            )

        store = SqlAlchemyRuleBindingRegistrationStore(self.engine)
        app = build_app(
            bootstrap_initialization_reader=_Initialized(),
            setup_window_reader=_ClosedSetupWindow(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=SqlAlchemyCurrentSessionReader(self.engine),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_UnusedAccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.acceptance.invalid"}),
            rule_binding_registration_authority=store,
            rule_binding_registration_receipt_reader=store,
            rule_binding_scope_reader=SqlAlchemyRuleBindingDirectoryReader(self.engine),
        )

        body = {
            "requestKey": request_key,
            "bindingId": binding_id,
            "environmentId": f"env-{suffix}",
            "appId": f"app-{suffix}",
            "kind": "flow",
            "profile": "sentinel-flow-v1",
            "sourceId": source_id,
            "sourceRevision": source_revision,
            "target": {
                "provider": "nacos",
                "namespace": "acceptance-namespace",
                "group": "DEFAULT_GROUP",
                "dataId": "flow-rules.json",
            },
        }
        origin = "https://console.acceptance.invalid"
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url=origin,
            cookies={
                "sentinel_session": original_cookie,
                "__Host-sentinel_csrf": original_csrf,
            },
        ) as client:
            headers = {
                "origin": origin,
                "x-request-id": f"register-{suffix}",
                "x-sentinel-csrf": original_csrf,
                "idempotency-key": request_key,
            }
            created = await client.post("/api/v1/rulesets", json=body, headers=headers)
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(created.json()["id"], binding_id)

            scope_catalog = await client.get(
                "/api/v2/rules/binding-scopes",
                headers={"x-request-id": f"scope-read-{suffix}"},
            )
            self.assertEqual(scope_catalog.status_code, 200, scope_catalog.text)
            self.assertEqual(
                scope_catalog.json()["environments"],
                [{"id": body["environmentId"], "name": body["environmentId"]}],
            )
            self.assertEqual(
                scope_catalog.json()["applications"],
                [
                    {
                        "id": body["appId"],
                        "environmentId": body["environmentId"],
                        "name": body["appId"],
                    }
                ],
            )

            # The POST replay is intentionally still bound to the creating
            # session and payload fingerprint; only receipt GET survives rotation.
            client.cookies.set("sentinel_session", rotated_cookie)
            replay = await client.post("/api/v1/rulesets", json=body, headers=headers)
            self.assertEqual(replay.status_code, 403, replay.text)
            changed_body = {**body, "profile": "sentinel-flow-v2"}
            client.cookies.set("sentinel_session", original_cookie)
            changed_replay = await client.post(
                "/api/v1/rulesets", json=changed_body, headers=headers
            )
            self.assertEqual(changed_replay.status_code, 409, changed_replay.text)

            client.cookies.set("sentinel_session", rotated_cookie)
            receipt_path = (
                f"/api/v1/rulesets/{binding_id}/registration-operations/{request_key}"
            )
            receipt = await client.get(
                receipt_path, headers={"x-request-id": f"read-{suffix}"}
            )
            self.assertEqual(receipt.status_code, 200, receipt.text)
            self.assertEqual(receipt.json()["status"], "completed")
            self.assertEqual(receipt.json()["binding"]["id"], binding_id)

            for wrong_path in (
                f"/api/v1/rulesets/{binding_id}-wrong/registration-operations/{request_key}",
                f"/api/v1/rulesets/{binding_id}/registration-operations/{request_key}-wrong",
            ):
                missing = await client.get(
                    wrong_path, headers={"x-request-id": f"missing-{suffix}"}
                )
                self.assertEqual(missing.status_code, 200, missing.text)
                self.assertEqual(missing.json()["status"], "not_found")
                self.assertIsNone(missing.json()["binding"])

            client.cookies.set("sentinel_session", other_cookie)
            cross_actor = await client.get(
                receipt_path, headers={"x-request-id": f"cross-actor-{suffix}"}
            )
            self.assertEqual(cross_actor.status_code, 200, cross_actor.text)
            self.assertEqual(cross_actor.json()["status"], "not_found")

        try:
            async with self.engine.begin() as connection:
                await connection.execute(
                    update(AccountRecord)
                    .where(AccountRecord.account_id == actor_id)
                    .values(role_id="view")
                )
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url=origin,
                cookies={"sentinel_session": rotated_cookie},
            ) as viewer:
                forbidden = await viewer.get(
                    receipt_path, headers={"x-request-id": f"demoted-{suffix}"}
                )
            self.assertEqual(forbidden.status_code, 403, forbidden.text)
        finally:
            await self._cleanup(**self._cleanup_scope)
            self._cleaned = True

    async def _cleanup(
        self,
        *,
        actor_id: str,
        other_actor_id: str,
        source_id: str,
        binding_id: str,
        request_key: str,
        request_ids: tuple[str, ...],
    ) -> None:
        from sqlalchemy import delete

        from atlas_richie.sentinel_console.infrastructure.persistence.models import (
            AuditEventRecord,
            RuleBindingRecord,
            RuleBindingRegistrationOperationRecord,
            RulePublicationTargetRecord,
        )

        async with self.engine.begin() as connection:
            await connection.execute(
                delete(AuditEventRecord).where(
                    AuditEventRecord.request_id.in_(request_ids)
                )
            )
            await connection.execute(
                delete(RuleBindingRegistrationOperationRecord).where(
                    RuleBindingRegistrationOperationRecord.request_key == request_key
                )
            )
            await connection.execute(
                delete(RulePublicationTargetRecord).where(
                    RulePublicationTargetRecord.binding_id == binding_id
                )
            )
            await connection.execute(
                delete(RuleBindingRecord).where(
                    RuleBindingRecord.binding_id == binding_id
                )
            )
            await connection.execute(
                delete(RegisteredConfigurationSourceRecord).where(
                    RegisteredConfigurationSourceRecord.source_id == source_id
                )
            )
            await connection.execute(
                delete(AuthenticationSessionRecord).where(
                    AuthenticationSessionRecord.account_id.in_(
                        (actor_id, other_actor_id)
                    )
                )
            )
            await connection.execute(
                delete(AccountRecord).where(
                    AccountRecord.account_id.in_((actor_id, other_actor_id))
                )
            )


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("receipt acceptance must not read the account directory")

    async def read_account(self, account_id: str):
        raise AssertionError("receipt acceptance must not read the account directory")
