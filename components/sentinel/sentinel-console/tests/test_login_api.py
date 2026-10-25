"""Login HTTP and persistence contract tests against isolated SQLite."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import threading
import unittest
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.api.client_address import ClientAddressResolver
from atlas_richie.sentinel_console.api.login import login_route
from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.login import Login
from atlas_richie.sentinel_console.domain.account_username import AccountUsername
from atlas_richie.sentinel_console.infrastructure.persistence.account_directory_reader import (
    SqlAlchemyAccountDirectoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.current_session_reader import (
    SqlAlchemyCurrentSessionReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.current_session_revoker import (
    SqlAlchemyCurrentSessionRevoker,
)
from atlas_richie.sentinel_console.infrastructure.persistence.login_credential_reader import (
    SqlAlchemyLoginCredentialReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.login_session_writer import (
    SqlAlchemyLoginSessionWriter,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuthenticationSessionRecord,
)
from atlas_richie.sentinel_console.infrastructure.security.password_hash import (
    PasswordHashService,
)

_ORIGIN = "https://console.test"
_CSRF = "csrf-token-for-login-flow-test-00000000001"
_USERNAME = "ops-admin"
_PASSWORD = "synthetic-login-password-012345"
_PREVIOUS_SESSION_TOKEN = "previous-session-token-for-login-flow-00001"
_SESSION_TOKEN = "session-token-for-login-flow-test-00000001"
_ROTATED_CSRF = "csrf-token-for-login-flow-test-00000000002"
_CLIENT_IDENTITY_KEY = b"synthetic-client-identity-hmac-key-32"
_CLIENT_KEY = hmac.new(_CLIENT_IDENTITY_KEY, b"127.0.0.1", hashlib.sha256).hexdigest()
_NOW = datetime.now(UTC)


class _AttemptLimiter:
    def __init__(self, retry_after_ms: int | None = None) -> None:
        self.retry = retry_after_ms
        self.fail_checks = False
        self.checked: list[str] = []
        self.failures: list[str] = []
        self.successes: list[str] = []

    async def retry_after_ms(self, client_identity_digest: str) -> int | None:
        self.checked.append(client_identity_digest)
        if self.fail_checks:
            raise RuntimeError("synthetic limiter outage")
        return self.retry

    async def record_failure(self, client_identity_digest: str) -> None:
        self.failures.append(client_identity_digest)

    async def record_success(self, client_identity_digest: str) -> None:
        self.successes.append(client_identity_digest)


class _CredentialReaderSpy:
    def __init__(self, reader) -> None:
        self.reader = reader
        self.calls: list[str] = []

    async def read_login_credential(self, username_key: str):
        self.calls.append(username_key)
        return await self.reader.read_login_credential(username_key)


class _BlockingPasswordVerifier:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def verify_unknown_account(self, candidate: str) -> None:
        raise AssertionError("known login should verify the account hash")

    def verify_account_password(self, encoded_hash: str | None, candidate: str) -> bool:
        self.started.set()
        self.release.wait(timeout=2)
        return True


class LoginApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        self.password_hasher = PasswordHashService()
        self.username = AccountUsername(_USERNAME)
        self.credential_reader = _CredentialReaderSpy(
            SqlAlchemyLoginCredentialReader(self.engine)
        )
        self.limiter = _AttemptLimiter()
        self.tokens = iter((_SESSION_TOKEN, _ROTATED_CSRF))
        self.login = Login(
            credential_reader=self.credential_reader,
            session_writer=SqlAlchemyLoginSessionWriter(self.engine),
            attempt_limiter=self.limiter,
            password_hasher=self.password_hasher,
            session_ttl=timedelta(hours=8),
            clock=lambda: _NOW,
            token_factory=lambda _length: next(self.tokens),
        )
        self.app = build_app(
            bootstrap_initialization_reader=_Initialized(),
            setup_window_reader=_ClosedSetupWindow(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=SqlAlchemyCurrentSessionReader(self.engine),
            current_session_revoker=SqlAlchemyCurrentSessionRevoker(self.engine),
            account_directory_reader=SqlAlchemyAccountDirectoryReader(self.engine),
            allowed_browser_origins=frozenset({_ORIGIN}),
            login_service=self.login,
            client_identity_hmac_key=_CLIENT_IDENTITY_KEY,
            client_address_resolver=ClientAddressResolver.from_cidrs(("10.20.0.0/16",)),
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="login-account-1",
                    username=_USERNAME,
                    username_key=self.username.lookup_key,
                    password_hash=self.password_hasher.hash_password(_PASSWORD),
                    role_id="admin",
                    status="active",
                    built_in=False,
                    last_login_at=None,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=hashlib.sha256(
                        _PREVIOUS_SESSION_TOKEN.encode()
                    ).hexdigest(),
                    account_id="login-account-1",
                    session_epoch="old-session-epoch",
                    csrf_hash="b" * 64,
                    created_at=_NOW - timedelta(hours=1),
                    expires_at=_NOW + timedelta(hours=1),
                    revoked_at=None,
                )
            )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_login_route_requires_a_strong_deployment_hmac_key(self) -> None:
        with self.assertRaises(ValueError):
            login_route(self.login, frozenset({_ORIGIN}), b"short")

    async def test_login_issues_only_digests_and_me_reads_the_rotated_session(
        self,
    ) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url=_ORIGIN
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            client.cookies.set("sentinel_session", _PREVIOUS_SESSION_TOKEN)
            response = await client.post(
                "/api/v1/auth/login",
                headers=_proof_headers(_CSRF),
                json={"username": f"  {_USERNAME.upper()}  ", "password": _PASSWORD},
            )
            identity = response.json()
            me = await client.get("/api/v1/auth/me", headers={"x-request-id": "me-1"})

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("login", response)
        self.assertEqual(response.headers["x-request-id"], "login-request-1")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-sentinel-csrf"], _ROTATED_CSRF)
        self.assertEqual(identity["accountId"], "login-account-1")
        self.assertEqual(identity["roleId"], "admin")
        self.assertEqual(identity["capabilities"], ["metrics:view", "rules:write"])
        self.assertNotIn(_SESSION_TOKEN, response.text)
        self.assertNotIn(_ROTATED_CSRF, response.text)
        set_cookies = response.headers.get_list("set-cookie")
        self.assertEqual(len(set_cookies), 2)
        self.assertIn("httponly", set_cookies[0].lower())
        self.assertIn("secure", set_cookies[0].lower())
        self.assertIn("samesite=lax", set_cookies[0].lower())
        self.assertIn("httponly", set_cookies[1].lower())
        self.assertIn("samesite=strict", set_cookies[1].lower())
        self.assertEqual(me.status_code, 200)
        assert_openapi_response("readSession", me)
        self.assertEqual(me.json(), identity)

        session_digest = hashlib.sha256(_SESSION_TOKEN.encode()).hexdigest()
        csrf_digest = hashlib.sha256(_ROTATED_CSRF.encode()).hexdigest()
        previous_digest = hashlib.sha256(_PREVIOUS_SESSION_TOKEN.encode()).hexdigest()
        async with self.engine.connect() as connection:
            session = (
                await connection.execute(
                    select(
                        AuthenticationSessionRecord.csrf_hash,
                        AuthenticationSessionRecord.session_epoch,
                        AuthenticationSessionRecord.expires_at,
                    ).where(AuthenticationSessionRecord.session_hash == session_digest)
                )
            ).one()
            account = (
                await connection.execute(
                    select(AccountRecord.last_login_at).where(
                        AccountRecord.account_id == "login-account-1"
                    )
                )
            ).scalar_one()
            previous_revocation = (
                await connection.execute(
                    select(AuthenticationSessionRecord.revoked_at).where(
                        AuthenticationSessionRecord.session_hash == previous_digest
                    )
                )
            ).scalar_one()
        self.assertEqual(session.csrf_hash, csrf_digest)
        self.assertEqual(session.session_epoch, identity["sessionEpoch"])
        expires_at = session.expires_at.replace(tzinfo=UTC)
        self.assertEqual(expires_at, _NOW + timedelta(hours=8))
        self.assertEqual(account.replace(tzinfo=UTC), _NOW)
        self.assertEqual(previous_revocation.replace(tzinfo=UTC), _NOW)
        self.assertEqual(self.limiter.successes, [_CLIENT_KEY])

    async def test_password_verification_does_not_block_the_event_loop(self) -> None:
        verifier = _BlockingPasswordVerifier()
        self.login._password_hasher = verifier
        client = AsyncClient(transport=ASGITransport(app=self.app), base_url=_ORIGIN)
        client.cookies.set("__Host-sentinel_csrf", _CSRF)
        client.cookies.set("sentinel_session", _PREVIOUS_SESSION_TOKEN)
        request = asyncio.create_task(
            client.post(
                "/api/v1/auth/login",
                headers=_proof_headers(_CSRF),
                json={"username": _USERNAME, "password": _PASSWORD},
            )
        )
        self.assertTrue(await asyncio.to_thread(verifier.started.wait, 1))

        heartbeat_count = 0

        async def heartbeat() -> None:
            nonlocal heartbeat_count
            while not verifier.release.is_set():
                heartbeat_count += 1
                await asyncio.sleep(0)

        heartbeat_task = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.01)
        verifier.release.set()
        response = await request
        await heartbeat_task
        await client.aclose()

        self.assertGreater(heartbeat_count, 0)
        self.assertEqual(response.status_code, 200)

    async def test_login_preserves_ecmascript_non_whitespace_username_suffixes(
        self,
    ) -> None:
        usernames = (f"{_USERNAME}\u0085", f"{_USERNAME}\u001c")
        async with self.engine.begin() as connection:
            for index, username in enumerate(usernames, start=1):
                identity = AccountUsername(username)
                await connection.execute(
                    insert(AccountRecord).values(
                        account_id=f"login-unicode-account-{index}",
                        username=identity.value,
                        username_key=identity.lookup_key,
                        password_hash=self.password_hasher.hash_password(_PASSWORD),
                        role_id="admin",
                        status="active",
                        built_in=False,
                        last_login_at=None,
                        revision=1,
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )

        self.tokens = iter(
            (
                "session-token-unicode-login-one-00000001",
                "csrf-token-unicode-login-one-00000001",
                "session-token-unicode-login-two-00000002",
                "csrf-token-unicode-login-two-00000002",
            )
        )
        for index, username in enumerate(usernames, start=1):
            csrf = f"csrf-token-for-login-unicode-{index}-00000001"
            async with AsyncClient(
                transport=ASGITransport(app=self.app), base_url=_ORIGIN
            ) as client:
                client.cookies.set("__Host-sentinel_csrf", csrf)
                response = await client.post(
                    "/api/v1/auth/login",
                    headers=_proof_headers(csrf, f"unicode-login-{index}"),
                    json={"username": username, "password": _PASSWORD},
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(
                    response.json()["username"], AccountUsername(username).value
                )

        self.assertEqual(len(self.credential_reader.calls), 2)

    async def test_wrong_unknown_and_disabled_credentials_share_one_public_result(
        self,
    ) -> None:
        results = []
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url=_ORIGIN
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            results.append(
                await client.post(
                    "/api/v1/auth/login",
                    headers=_proof_headers(_CSRF, "login-wrong-1"),
                    json={"username": _USERNAME, "password": "wrong-password"},
                )
            )
            async with self.engine.begin() as connection:
                await connection.execute(
                    update(AccountRecord)
                    .where(AccountRecord.account_id == "login-account-1")
                    .values(status="active", password_hash="malformed-password-hash")
                )
            results.append(
                await client.post(
                    "/api/v1/auth/login",
                    headers=_proof_headers(_CSRF, "login-corrupt-hash-1"),
                    json={"username": _USERNAME, "password": _PASSWORD},
                )
            )
            results.append(
                await client.post(
                    "/api/v1/auth/login",
                    headers=_proof_headers(_CSRF, "login-unknown-1"),
                    json={"username": "unknown-user", "password": _PASSWORD},
                )
            )
            async with self.engine.begin() as connection:
                await connection.execute(
                    update(AccountRecord)
                    .where(AccountRecord.account_id == "login-account-1")
                    .values(status="disabled")
                )
            results.append(
                await client.post(
                    "/api/v1/auth/login",
                    headers=_proof_headers(_CSRF, "login-disabled-1"),
                    json={"username": _USERNAME, "password": _PASSWORD},
                )
            )

        public_results = [
            (item.status_code, item.json()["error"]["code"]) for item in results
        ]
        self.assertEqual(public_results, [(401, "unauthenticated")] * 4)
        self.assertTrue(
            all(not result.headers.get_list("set-cookie") for result in results)
        )
        for result in results:
            assert_openapi_response("login", result)
        self.assertEqual(len(self.limiter.failures), 4)
        self.assertNotIn(_PASSWORD, " ".join(result.text for result in results))

    async def test_invalid_origin_or_csrf_is_rejected_before_limiter_or_lookup(
        self,
    ) -> None:
        cases = (
            ({"origin": "https://attacker.test"}, 403),
            ({"x-sentinel-csrf": "other-valid-csrf-token-value-0000001"}, 403),
        )
        for extra_headers, status in cases:
            headers = _proof_headers(_CSRF, "login-invalid-proof-1")
            headers.update(extra_headers)
            async with AsyncClient(
                transport=ASGITransport(app=self.app), base_url=_ORIGIN
            ) as client:
                client.cookies.set("__Host-sentinel_csrf", _CSRF)
                response = await client.post(
                    "/api/v1/auth/login",
                    headers=headers,
                    json={"username": _USERNAME, "password": _PASSWORD},
                )
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["error"]["code"], "csrf_failed")
        self.assertEqual(self.limiter.checked, [])
        self.assertEqual(self.credential_reader.calls, [])

    async def test_duplicate_proof_and_malformed_body_never_reach_credentials(
        self,
    ) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url=_ORIGIN
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            duplicate = await client.post(
                "/api/v1/auth/login",
                headers=[
                    ("origin", _ORIGIN),
                    ("origin", _ORIGIN),
                    ("x-request-id", "login-duplicate-origin-1"),
                    ("x-sentinel-csrf", _CSRF),
                ],
                content=json.dumps({"username": _USERNAME, "password": _PASSWORD}),
            )
            malformed = await client.post(
                "/api/v1/auth/login",
                headers=_proof_headers(_CSRF, "login-extra-field-1"),
                json={"username": _USERNAME, "password": _PASSWORD, "extra": True},
            )
            duplicate_json_key = await client.post(
                "/api/v1/auth/login",
                headers={
                    **_proof_headers(_CSRF, "login-duplicate-json-key-1"),
                    "content-type": "application/json",
                },
                content=(
                    b'{"username":"ops-admin","username":"unknown-user",'
                    b'"password":"synthetic-login-password-012345"}'
                ),
            )
            malformed_unicode = await client.post(
                "/api/v1/auth/login",
                headers={
                    **_proof_headers(_CSRF, "login-invalid-unicode-1"),
                    "content-type": "application/json",
                },
                content=b'{"username":"ops-admin","password":"\\ud800"}',
            )

        self.assertEqual(duplicate.status_code, 403)
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(duplicate_json_key.status_code, 400)
        self.assertEqual(malformed_unicode.status_code, 400)
        self.assertEqual(self.limiter.checked, [])
        self.assertEqual(self.credential_reader.calls, [])

    async def test_rate_limit_is_bounded_and_skips_credential_lookup(self) -> None:
        self.limiter.retry = 999_999
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url=_ORIGIN
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            response = await client.post(
                "/api/v1/auth/login",
                headers=_proof_headers(_CSRF, "login-rate-limit-1"),
                json={"username": _USERNAME, "password": _PASSWORD},
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "rate_limited")
        self.assertEqual(response.json()["error"]["retryAfterMs"], 300_000)
        self.assertEqual(self.credential_reader.calls, [])

    async def test_untrusted_peer_cannot_choose_its_login_limit_identity(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=self.app, client=("127.0.0.1", 1234)),
            base_url=_ORIGIN,
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            response = await client.post(
                "/api/v1/auth/login",
                headers={
                    **_proof_headers(_CSRF, "login-untrusted-forwarded-1"),
                    "x-forwarded-for": "198.51.100.9",
                },
                json={"username": _USERNAME, "password": "wrong-password"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.limiter.checked[-1], _CLIENT_KEY)

    async def test_trusted_proxy_chain_uses_nearest_untrusted_address(self) -> None:
        forwarded_client = "198.51.100.24"
        expected_identity = hmac.new(
            _CLIENT_IDENTITY_KEY,
            forwarded_client.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        async with AsyncClient(
            transport=ASGITransport(app=self.app, client=("10.20.1.8", 443)),
            base_url=_ORIGIN,
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            response = await client.post(
                "/api/v1/auth/login",
                headers={
                    **_proof_headers(_CSRF, "login-trusted-forwarded-1"),
                    "x-forwarded-for": f"{forwarded_client}, 10.20.2.7",
                },
                json={"username": _USERNAME, "password": "wrong-password"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.limiter.checked[-1], expected_identity)

    async def test_malformed_forwarding_chain_falls_back_to_proxy_peer(self) -> None:
        proxy_peer = "10.20.3.5"
        expected_identity = hmac.new(
            _CLIENT_IDENTITY_KEY, proxy_peer.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        async with AsyncClient(
            transport=ASGITransport(app=self.app, client=(proxy_peer, 443)),
            base_url=_ORIGIN,
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            response = await client.post(
                "/api/v1/auth/login",
                headers={
                    **_proof_headers(_CSRF, "login-malformed-forwarded-1"),
                    "x-forwarded-for": "198.51.100.24, unknown",
                },
                json={"username": _USERNAME, "password": "wrong-password"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.limiter.checked[-1], expected_identity)

    def test_trusted_proxy_policy_rejects_global_or_noncanonical_networks(
        self,
    ) -> None:
        for cidr in (
            "0.0.0.0/0",
            "0.0.0.0/1",
            "128.0.0.0/1",
            "10.20.1.0/16",
        ):
            with self.subTest(cidr=cidr), self.assertRaises(ValueError):
                ClientAddressResolver.from_cidrs((cidr,))

    async def test_limiter_failure_fails_closed_without_credentials_or_cookies(
        self,
    ) -> None:
        self.limiter.fail_checks = True
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url=_ORIGIN
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            response = await client.post(
                "/api/v1/auth/login",
                headers=_proof_headers(_CSRF, "login-limiter-outage-1"),
                json={"username": _USERNAME, "password": _PASSWORD},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertFalse(response.headers.get_list("set-cookie"))
        self.assertEqual(self.credential_reader.calls, [])

    async def test_login_does_not_revoke_a_previous_cookie_from_another_account(
        self,
    ) -> None:
        foreign_token = "foreign-session-token-for-login-test-0001"
        foreign_digest = hashlib.sha256(foreign_token.encode()).hexdigest()
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="foreign-account",
                    username="other-operator",
                    username_key=AccountUsername("other-operator").lookup_key,
                    password_hash=self.password_hasher.hash_password(
                        "synthetic-foreign-password-012345"
                    ),
                    role_id="view",
                    status="active",
                    built_in=False,
                    last_login_at=None,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=foreign_digest,
                    account_id="foreign-account",
                    session_epoch="foreign-epoch",
                    csrf_hash="c" * 64,
                    created_at=_NOW - timedelta(minutes=1),
                    expires_at=_NOW + timedelta(hours=1),
                    revoked_at=None,
                )
            )

        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url=_ORIGIN
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            client.cookies.set("sentinel_session", foreign_token)
            response = await client.post(
                "/api/v1/auth/login",
                headers=_proof_headers(_CSRF, "login-cross-account-cookie-1"),
                json={"username": _USERNAME, "password": _PASSWORD},
            )

        self.assertEqual(response.status_code, 200)
        async with self.engine.connect() as connection:
            revoked_at = (
                await connection.execute(
                    select(AuthenticationSessionRecord.revoked_at).where(
                        AuthenticationSessionRecord.session_hash == foreign_digest
                    )
                )
            ).scalar_one()
        self.assertIsNone(revoked_at)

    async def test_invalid_request_id_and_invalid_json_do_not_touch_authorities(
        self,
    ) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url=_ORIGIN
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            bad_request_id = await client.post(
                "/api/v1/auth/login",
                headers=_proof_headers(_CSRF, "bad\nrequest"),
                json={"username": _USERNAME, "password": _PASSWORD},
            )
            invalid_json = await client.post(
                "/api/v1/auth/login",
                headers={
                    **_proof_headers(_CSRF, "login-invalid-json-1"),
                    "content-type": "application/json",
                },
                content=b"{",
            )

        self.assertEqual(bad_request_id.status_code, 400)
        self.assertEqual(invalid_json.status_code, 400)
        self.assertEqual(self.limiter.checked, [])
        self.assertEqual(self.credential_reader.calls, [])


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _ClosedSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


def _proof_headers(csrf: str, request_id: str = "login-request-1") -> dict[str, str]:
    return {
        "origin": _ORIGIN,
        "x-request-id": request_id,
        "x-sentinel-csrf": csrf,
    }
