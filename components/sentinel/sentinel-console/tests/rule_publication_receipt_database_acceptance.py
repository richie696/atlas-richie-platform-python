"""Disposable PostgreSQL/MySQL acceptance for durable runtime receipts."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncEngine

from atlas_richie.sentinel_console.application.rule_publication_ports import (
    RulePublicationConflict,
)
from atlas_richie.sentinel_console.domain.rule_publications import (
    PublicationReceiptState,
    RulePublicationReceipt,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    identity_composition,
)
from atlas_richie.sentinel_console.infrastructure.persistence.login_attempt_configuration import (
    LoginAttemptLimitConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuthenticationSessionRecord,
    RulePublicationReceiptRecord,
    RulePublicationRecord,
    RuleSetVersionRecord,
    RuleValidationReceiptRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_receipt_store import (
    SqlAlchemyRulePublicationReceiptStore,
)
from atlas_richie.sentinel_console.infrastructure.security.account_command_keys import (
    AccountCommandKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.client_identity_key import (
    ClientIdentityKeyConfiguration,
)

_CONSOLE_ORIGIN = "https://receipt.acceptance.invalid"
_SESSION_COOKIE_NAME = "sentinel_session"


class _ClosedSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


async def assert_runtime_publication_receipt_persistence(
    case, engine: AsyncEngine, dialect: str
) -> None:
    """Verify SQL receipt persistence and the composed authenticated HTTP read."""
    if dialect not in {"postgresql", "mysql"}:
        raise ValueError("acceptance requires PostgreSQL or MySQL")
    token = uuid4().hex
    now = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
    account_id = str(uuid4())
    validation_id = f"receipt-validation-{token}"
    binding_id = f"receipt-binding-{token}"
    version_id = f"receipt-version-{token}"
    publication_id = f"receipt-publication-{token}"
    instance_id = f"receipt-instance-{token}"
    checksum = f"sha256:{token}"
    store = SqlAlchemyRulePublicationReceiptStore(engine)

    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id=account_id,
                    username=f"receipt-view-{token[:12]}",
                    username_key=token[:64],
                    password_hash="$argon2id$acceptance-only",
                    role_id="view",
                    status="active",
                    built_in=False,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            await connection.execute(
                insert(RuleValidationReceiptRecord).values(
                    validation_id=validation_id,
                    binding_id=binding_id,
                    profile="sentinel-profile-v1",
                    base_checksum="sha256:base",
                    candidate_checksum=checksum,
                    is_publishable=True,
                    issues=[],
                    actor_account_id=account_id,
                    request_id=f"receipt-request-{token}",
                    created_at=now,
                )
            )
            await connection.execute(
                insert(RuleSetVersionRecord).values(
                    version_id=version_id,
                    binding_id=binding_id,
                    kind="flow",
                    profile="sentinel-profile-v1",
                    base_version_id=None,
                    checksum=checksum,
                    name="receipt acceptance",
                    note="",
                    validation_id=validation_id,
                    records=[],
                    created_at=now,
                    created_by_account_id=account_id,
                )
            )
            await connection.execute(
                insert(RulePublicationRecord).values(
                    publication_id=publication_id,
                    binding_id=binding_id,
                    target_version_id=version_id,
                    target_checksum=checksum,
                    publication_sequence=1,
                    base_version_id=None,
                    created_at=now,
                    validation_state="succeeded",
                    validation_observed_at=now,
                    validation_reason=None,
                    write_state="succeeded",
                    write_observed_at=now,
                    write_reason=None,
                    read_back_state="succeeded",
                    read_back_observed_at=now,
                    read_back_reason=None,
                )
            )

        pending = RulePublicationReceipt(
            instance_id=instance_id,
            process_epoch="process-1",
            loaded_process_epoch=None,
            target_version_id=version_id,
            loaded_version_id=None,
            loaded_checksum=None,
            applied_at=None,
            last_report_at=now,
            state=PublicationReceiptState.PENDING,
        )
        await asyncio.gather(
            store.record_rule_publication_receipt(binding_id, publication_id, pending),
            store.record_rule_publication_receipt(binding_id, publication_id, pending),
        )
        await store.record_rule_publication_receipt(binding_id, publication_id, pending)
        with case.assertRaises(RulePublicationConflict):
            await store.record_rule_publication_receipt(
                binding_id,
                publication_id,
                replace(
                    pending,
                    state=PublicationReceiptState.FAILED,
                    last_report_at=now - timedelta(milliseconds=1),
                ),
            )

        applied_at = now + timedelta(milliseconds=1)
        applied = replace(
            pending,
            loaded_process_epoch="process-1",
            loaded_version_id=version_id,
            loaded_checksum=checksum,
            applied_at=applied_at,
            last_report_at=applied_at,
            state=PublicationReceiptState.APPLIED,
        )
        await store.record_rule_publication_receipt(binding_id, publication_id, applied)
        page = await store.read_rule_publication_receipts(
            binding_id, publication_id, page=1, page_size=10
        )
        case.assertEqual(page.total, 1)
        case.assertEqual(page.applied, 1)
        case.assertEqual(page.pending, 0)
        case.assertEqual(page.items, (applied,))
        case.assertIsNone(page.expected)
        case.assertIsNone(page.inventory_source)

        session_token = f"receipt-session-{token}"
        async with engine.begin() as connection:
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=hashlib.sha256(
                        session_token.encode("ascii")
                    ).hexdigest(),
                    account_id=account_id,
                    session_epoch="receipt-process-epoch",
                    csrf_hash=hashlib.sha256(
                        f"receipt-csrf-{token}".encode("ascii")
                    ).hexdigest(),
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                    revoked_at=None,
                )
            )

        app = identity_composition.build_sql_identity_app(
            engine,
            attempt_limit=LoginAttemptLimitConfiguration(5, 300, 300),
            account_command_keys=AccountCommandKeyConfiguration(
                "receipt-acceptance-v1", {"receipt-acceptance-v1": b"a" * 32}
            ),
            client_identity_key=ClientIdentityKeyConfiguration(b"c" * 32),
            session_ttl=timedelta(hours=1),
            setup_window_reader=_ClosedSetupWindow(),
            allowed_browser_origins=frozenset({_CONSOLE_ORIGIN}),
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url=_CONSOLE_ORIGIN,
            cookies={_SESSION_COOKIE_NAME: session_token},
        ) as client:
            response = await client.get(
                f"/api/v1/rulesets/{binding_id}/publications/{publication_id}/receipts"
                "?page=1&pageSize=10",
                headers={"x-request-id": f"receipt-read-{token}"},
            )
            client.cookies.clear()
            unauthenticated = await client.get(
                f"/api/v1/rulesets/{binding_id}/publications/{publication_id}/receipts"
                "?page=1&pageSize=10",
                headers={"x-request-id": f"receipt-anon-{token}"},
            )

        case.assertEqual(response.status_code, 200)
        case.assertEqual(response.headers["cache-control"], "no-store")
        case.assertEqual(response.headers["vary"], "Cookie")
        body = response.json()
        case.assertEqual(body["bindingId"], binding_id)
        case.assertEqual(body["publicationId"], publication_id)
        case.assertEqual(body["total"], 1)
        case.assertEqual(body["applied"], 1)
        case.assertEqual(body["pending"], 0)
        case.assertEqual(body["items"][0]["instanceId"], instance_id)
        case.assertEqual(body["items"][0]["loadedVersionId"], version_id)
        case.assertEqual(body["items"][0]["loadedChecksum"], checksum)
        case.assertEqual(unauthenticated.status_code, 401)
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(AuthenticationSessionRecord).where(
                    AuthenticationSessionRecord.account_id == account_id
                )
            )
            await connection.execute(
                delete(RulePublicationReceiptRecord).where(
                    RulePublicationReceiptRecord.publication_id == publication_id
                )
            )
            await connection.execute(
                delete(RulePublicationRecord).where(
                    RulePublicationRecord.publication_id == publication_id
                )
            )
            await connection.execute(
                delete(RuleSetVersionRecord).where(
                    RuleSetVersionRecord.version_id == version_id
                )
            )
            await connection.execute(
                delete(RuleValidationReceiptRecord).where(
                    RuleValidationReceiptRecord.validation_id == validation_id
                )
            )
            await connection.execute(
                delete(AccountRecord).where(AccountRecord.account_id == account_id)
            )
