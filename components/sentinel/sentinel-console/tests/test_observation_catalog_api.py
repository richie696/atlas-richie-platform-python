"""Observation catalog reads against isolated identity and catalog authorities."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.observation_catalog_ports import (
    ObservationCatalogAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.observation_catalog import (
    ObservationApplication,
    ObservationCatalogSnapshot,
    ObservationEnvironment,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_REQUEST_HEADERS = {"x-request-id": "observation-catalog-read-1"}
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


class _CatalogReader:
    def __init__(self, snapshot: ObservationCatalogSnapshot | None = None) -> None:
        self.snapshot = snapshot or _snapshot()
        self.calls = 0

    async def read_observation_catalog(self) -> ObservationCatalogSnapshot:
        self.calls += 1
        return self.snapshot


class _UnavailableCatalogReader:
    async def read_observation_catalog(self) -> ObservationCatalogSnapshot:
        raise ObservationCatalogAuthorityUnavailable("private catalog detail")


class _InvalidCatalogReader:
    async def read_observation_catalog(self):
        return None


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("observation catalog must not read account data")

    async def read_account(self, account_id: str):
        raise AssertionError("observation catalog must not read account data")


def _snapshot() -> ObservationCatalogSnapshot:
    return ObservationCatalogSnapshot(
        as_of=_AS_OF,
        environments=(ObservationEnvironment("prod", "Production"),),
        applications=(ObservationApplication("checkout", "prod", "Checkout API"),),
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
        observation_catalog_reader=reader,
    )


class ObservationCatalogApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_admin_and_viewer_receive_the_authoritative_catalog(self) -> None:
        expected = {
            "asOf": "2026-10-09T01:02:03.456Z",
            "environments": [{"id": "prod", "name": "Production"}],
            "applications": [
                {"id": "checkout", "environmentId": "prod", "name": "Checkout API"}
            ],
        }
        for role in ("admin", "view"):
            reader = _CatalogReader()
            async with AsyncClient(
                transport=ASGITransport(app=_app(role, reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/observation/catalog", headers=_REQUEST_HEADERS
                )

            self.assertEqual(response.status_code, 200)
            assert_openapi_response("readObservationCatalog", response)
            self.assertEqual(
                response.headers["x-request-id"], _REQUEST_HEADERS["x-request-id"]
            )
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["vary"], "Cookie")
            self.assertEqual(response.json(), expected)
            self.assertEqual(reader.calls, 1)

    async def test_anonymous_request_is_rejected_before_catalog_read(self) -> None:
        reader = _CatalogReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app(None, reader=reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/observation/catalog", headers=_REQUEST_HEADERS
            )

        self.assertEqual(response.status_code, 401)
        assert_openapi_response("readObservationCatalog", response)
        self.assertEqual(response.json()["error"]["code"], "unauthenticated")
        self.assertEqual(reader.calls, 0)

    async def test_invalid_request_id_and_unavailable_session_fail_closed(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", reader=_CatalogReader())),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/observation/catalog",
                headers={"x-request-id": "bad\nrequest"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

        async with AsyncClient(
            transport=ASGITransport(
                app=_app(
                    "admin",
                    reader=_CatalogReader(),
                    session_reader=_SessionReader("unavailable"),
                )
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/observation/catalog", headers=_REQUEST_HEADERS
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("private session store detail", response.text)

    async def test_missing_or_unavailable_catalog_returns_safe_503(self) -> None:
        for reader in (None, _UnavailableCatalogReader()):
            async with AsyncClient(
                transport=ASGITransport(app=_app("view", reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/observation/catalog", headers=_REQUEST_HEADERS
                )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "service_unavailable")
            self.assertNotIn("private catalog detail", response.text)

        async with AsyncClient(
            transport=ASGITransport(app=_app("view", reader=_InvalidCatalogReader())),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/observation/catalog", headers=_REQUEST_HEADERS
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")

    async def test_domain_rejects_invalid_or_unbounded_catalog_values(self) -> None:
        with self.assertRaises(ValueError):
            ObservationEnvironment("  ", "Production")
        with self.assertRaises(ValueError):
            ObservationApplication("checkout", "prod", "")
        with self.assertRaises(ValueError):
            ObservationCatalogSnapshot(datetime(2026, 10, 9), (), ())
        with self.assertRaises(ValueError):
            ObservationCatalogSnapshot(
                _AS_OF,
                tuple(
                    ObservationEnvironment(f"env-{index}", "Production")
                    for index in range(1001)
                ),
                (),
            )

    def test_domain_rejects_blank_names_and_inconsistent_catalog_relationships(
        self,
    ) -> None:
        for blank_name in ("\x1c", "\x85", "\ufeff", "\u3000"):
            with (
                self.subTest(blank_name=repr(blank_name)),
                self.assertRaises(ValueError),
            ):
                ObservationEnvironment("prod", blank_name)
            with (
                self.subTest(blank_name=repr(blank_name)),
                self.assertRaises(ValueError),
            ):
                ObservationApplication("checkout", "prod", blank_name)

        environment = ObservationEnvironment("prod", "Production")
        duplicate_environment = ObservationEnvironment("prod", "Production copy")
        application = ObservationApplication("checkout", "prod", "Checkout")
        invalid_snapshots = (
            lambda: ObservationCatalogSnapshot(
                _AS_OF, (environment, duplicate_environment), ()
            ),
            lambda: ObservationCatalogSnapshot(
                _AS_OF, (environment,), (application, application)
            ),
            lambda: ObservationCatalogSnapshot(
                _AS_OF,
                (environment,),
                (ObservationApplication("checkout", "missing", "Checkout"),),
            ),
        )
        for create_snapshot in invalid_snapshots:
            with (
                self.subTest(create_snapshot=create_snapshot),
                self.assertRaises(ValueError),
            ):
                create_snapshot()

        same_identity_in_distinct_environments = ObservationCatalogSnapshot(
            _AS_OF,
            (environment, ObservationEnvironment("staging", "Staging")),
            (
                application,
                ObservationApplication("checkout", "staging", "Checkout preview"),
            ),
        )
        self.assertEqual(len(same_identity_in_distinct_environments.applications), 2)

    def test_domain_uses_utf16_bounds_and_rejects_non_scalar_catalog_text(self) -> None:
        invalid_values = (
            lambda: ObservationEnvironment("🌋" * 101, "Production"),
            lambda: ObservationEnvironment("prod", "🌋" * 101),
            lambda: ObservationApplication("checkout", "invalid-\ud800", "Checkout"),
            lambda: ObservationApplication("checkout", "prod", "invalid-\ud800"),
        )
        for create_invalid_value in invalid_values:
            with (
                self.subTest(create_invalid_value=create_invalid_value),
                self.assertRaises(ValueError),
            ):
                create_invalid_value()


if __name__ == "__main__":
    unittest.main()
