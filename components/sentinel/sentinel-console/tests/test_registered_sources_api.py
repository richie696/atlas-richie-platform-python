"""Administrator-only source registry reads against isolated authorities."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.registered_source_ports import (
    RegisteredSourcesAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.registered_sources import (
    RegisteredConfigurationSource,
    RegisteredSourcesSnapshot,
    SourceAuthenticationMode,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from session_test_doubles import UnusedSessionRevoker

_REQUEST_HEADERS = {"x-request-id": "registered-sources-read-1"}
_OPAQUE_COOKIE = "synthetic-session-token-for-console-read-0001"
_AS_OF = datetime(2026, 10, 9, 1, 2, 3, 456789, tzinfo=UTC)


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _OpenSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def read_active_session(self, session_digest: str):
        if self.role == "unavailable":
            raise SessionAuthorityUnavailable("private session store detail")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _RegisteredSourcesReader:
    def __init__(self, snapshot: RegisteredSourcesSnapshot | None = None) -> None:
        self.snapshot = snapshot or _snapshot()
        self.calls = 0

    async def read_registered_sources(self) -> RegisteredSourcesSnapshot:
        self.calls += 1
        return self.snapshot


class _UnavailableRegisteredSourcesReader:
    async def read_registered_sources(self) -> RegisteredSourcesSnapshot:
        raise RegisteredSourcesAuthorityUnavailable("private source registry detail")


class _InvalidRegisteredSourcesReader:
    async def read_registered_sources(self):
        return None


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("source registry read must not access accounts")

    async def read_account(self, account_id: str):
        raise AssertionError("source registry read must not access accounts")


def _snapshot() -> RegisteredSourcesSnapshot:
    return RegisteredSourcesSnapshot(
        as_of=_AS_OF,
        items=(
            RegisteredConfigurationSource(
                id="source-nacos",
                revision="revision-1",
                name="Primary Nacos",
                endpoint="https://nacos.example.test:8848",
                provider=ConfigurationSourceProvider.NACOS,
                location="sentinel-prod",
                authentication_mode=SourceAuthenticationMode.CREDENTIAL_REFERENCE,
                credential_configured=True,
            ),
            RegisteredConfigurationSource(
                id="source-consul",
                revision="revision-2",
                name="Primary Consul",
                endpoint="http://consul.example.test:8500/v1",
                provider=ConfigurationSourceProvider.CONSUL,
                location="dc-west",
                authentication_mode=SourceAuthenticationMode.NONE,
                credential_configured=False,
            ),
        ),
    )


def _app(role: str | None, *, reader=None, session_reader=None):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_UnusedAccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        registered_sources_reader=reader,
    )


class RegisteredSourcesApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_admin_receives_nacos_and_consul_safe_registry_facts(self) -> None:
        reader = _RegisteredSourcesReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", reader=reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/sources", headers=_REQUEST_HEADERS
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-request-id"], "registered-sources-read-1")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["vary"], "Cookie")
        self.assertEqual(
            response.json(),
            {
                "asOf": "2026-10-09T01:02:03.456Z",
                "items": [
                    {
                        "id": "source-nacos",
                        "revision": "revision-1",
                        "name": "Primary Nacos",
                        "endpoint": "https://nacos.example.test:8848",
                        "authenticationMode": "credential-reference",
                        "credentialConfigured": True,
                        "provider": "nacos",
                        "namespace": "sentinel-prod",
                    },
                    {
                        "id": "source-consul",
                        "revision": "revision-2",
                        "name": "Primary Consul",
                        "endpoint": "http://consul.example.test:8500/v1",
                        "authenticationMode": "none",
                        "credentialConfigured": False,
                        "provider": "consul",
                        "datacenter": "dc-west",
                    },
                ],
            },
        )
        self.assertNotIn("credential-reference-value", response.text)
        self.assertNotIn("credential", response.json()["items"][0])
        self.assertNotIn("reference", response.json()["items"][0])
        self.assertEqual(reader.calls, 1)

    async def test_viewer_and_anonymous_are_rejected_before_registry_read(self) -> None:
        for role, expected_status, expected_code in (
            ("view", 403, "forbidden"),
            (None, 401, "unauthenticated"),
        ):
            reader = _RegisteredSourcesReader()
            async with AsyncClient(
                transport=ASGITransport(app=_app(role, reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/system/sources", headers=_REQUEST_HEADERS
                )
            self.assertEqual(response.status_code, expected_status)
            self.assertEqual(response.json()["error"]["code"], expected_code)
            self.assertEqual(reader.calls, 0)

    async def test_invalid_request_id_and_unavailable_session_fail_closed(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(
                app=_app("admin", reader=_RegisteredSourcesReader())
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/sources", headers={"x-request-id": "bad\nrequest"}
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

        async with AsyncClient(
            transport=ASGITransport(
                app=_app(
                    "admin",
                    reader=_RegisteredSourcesReader(),
                    session_reader=_SessionReader("unavailable"),
                )
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/sources", headers=_REQUEST_HEADERS
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("private session store detail", response.text)

    async def test_missing_or_unavailable_registry_returns_safe_503(self) -> None:
        for reader in (None, _UnavailableRegisteredSourcesReader()):
            async with AsyncClient(
                transport=ASGITransport(app=_app("admin", reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/system/sources", headers=_REQUEST_HEADERS
                )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "service_unavailable")
            self.assertNotIn("private source registry detail", response.text)

        async with AsyncClient(
            transport=ASGITransport(
                app=_app("admin", reader=_InvalidRegisteredSourcesReader())
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/sources", headers=_REQUEST_HEADERS
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")

    async def test_domain_rejects_unsafe_or_contradictory_source_facts(self) -> None:
        valid = {
            "id": "source-1",
            "revision": "revision-1",
            "name": "Nacos",
            "endpoint": "https://nacos.example.test",
            "provider": ConfigurationSourceProvider.NACOS,
            "location": "namespace",
            "authentication_mode": SourceAuthenticationMode.CREDENTIAL_REFERENCE,
            "credential_configured": True,
        }
        for field, value in (
            ("id", "\x1c"),
            ("id", "\ufeff"),
            ("id", "\ud800"),
            ("revision", "\u0085"),
            ("name", "\u3000"),
            ("name", "\ud800"),
            ("location", "\ud800"),
            ("endpoint", "https://nacos.example.test/\ud800"),
            ("endpoint", "https://user:password@nacos.example.test"),
            ("endpoint", "https://nacos.example.test?token=secret"),
            ("endpoint", "https://nacos.example.test\ufeff"),
            ("endpoint", "https://nacos.example.test\u0085"),
            ("endpoint", "https://nacos.example.test/\x1c"),
            ("endpoint", "http://nacos.example.test\\private"),
            ("endpoint", "http://:80"),
            ("endpoint", "https://nacos.example.test:99999"),
            ("endpoint", "https://nacos.example.test:abc"),
            ("endpoint", "http://256.256.256.256"),
            ("endpoint", "http://1.2.3.999"),
            ("endpoint", "https://exa%mple.test"),
            ("endpoint", "http://[v1.invalid]"),
            ("endpoint", "https://example..test"),
            ("endpoint", "https://."),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                RegisteredConfigurationSource(**(valid | {field: value}))

        with self.assertRaises(ValueError):
            RegisteredConfigurationSource(
                **(
                    valid
                    | {
                        "authentication_mode": SourceAuthenticationMode.NONE,
                        "credential_configured": True,
                    }
                )
            )
        with self.assertRaises(ValueError):
            RegisteredSourcesSnapshot(datetime(2026, 10, 9), ())
        for endpoint in (
            "http://192.0.2.10:8080",
            "https://[2001:db8::10]:8443",
            "http://[::ffff:192.0.2.1]",
            "https://例子.测试/nacos",
        ):
            with self.subTest(endpoint=endpoint):
                RegisteredConfigurationSource(**(valid | {"endpoint": endpoint}))
        source = RegisteredConfigurationSource(**valid)
        with self.assertRaises(ValueError):
            RegisteredSourcesSnapshot(_AS_OF, (source, source))
        with self.assertRaises(ValueError):
            RegisteredSourcesSnapshot(
                _AS_OF,
                tuple(
                    RegisteredConfigurationSource(**(valid | {"id": f"source-{index}"}))
                    for index in range(501)
                ),
            )


if __name__ == "__main__":
    unittest.main()
