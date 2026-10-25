"""Read-only deployment guide catalog permissions and absence semantics."""

from __future__ import annotations

import unittest

from httpx import ASGITransport, AsyncClient
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.deployment_guides import (
    DeploymentGuideId,
    DeploymentGuidePath,
    DeploymentGuideReadiness,
    DeploymentGuidesAuthorityUnavailable,
    DeploymentGuidesSnapshot,
)
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.infrastructure.deployment_guide_catalog import (
    StaticDeploymentGuideCatalog,
)
from openapi_contract_support import assert_openapi_response

_COOKIE = "synthetic-session-token-for-deployment-guide-read-0001"


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
            raise SessionAuthorityUnavailable("private session detail")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("deployment guide reads do not access accounts")

    async def read_account(self, account_id: str):
        raise AssertionError("deployment guide reads do not access accounts")


class _UnavailableCatalog:
    async def read_deployment_guides(self):
        raise DeploymentGuidesAuthorityUnavailable("private deployment detail")


def _app(role: str | None, *, reader=None):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=_SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_UnusedAccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        deployment_guides_reader=(
            reader if reader is not None else StaticDeploymentGuideCatalog()
        ),
    )


class SystemDeploymentGuidesApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_admin_and_view_can_read_catalog_and_unset_collector_stays_null(self):
        for role in ("admin", "view"):
            async with AsyncClient(
                transport=ASGITransport(app=_app(role)), base_url="http://test"
            ) as client:
                client.cookies.set("sentinel_session", _COOKIE)
                response = await client.get(
                    "/api/v1/system/deployment-guides",
                    headers={
                        "x-request-id": f"guide-read-{role}",
                        "host": "spoofed.example",
                        "x-forwarded-host": "other.example",
                    },
                )
            self.assertEqual(response.status_code, 200)
            assert_openapi_response("readSystemDeploymentGuides", response)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["vary"], "Cookie")
            body = response.json()
            self.assertEqual(body["runtimeCollector"], {"state": "not_configured", "endpoint": None})
            self.assertEqual(
                [(item["id"], item["readiness"], item["profileRevision"]) for item in body["paths"]],
                [
                    ("existing", "configuration-required", None),
                    ("linux", "guide-only", None),
                    ("kubernetes", "guide-only", None),
                ],
            )
            self.assertNotIn("spoofed.example", response.text)
            self.assertNotIn("other.example", response.text)

    async def test_anonymous_is_rejected_before_catalog_access(self):
        async with AsyncClient(
            transport=ASGITransport(app=_app(None)), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/v1/system/deployment-guides",
                headers={"x-request-id": "guide-read-anon"},
            )
        self.assertEqual(response.status_code, 401)

    async def test_explicit_collector_endpoint_is_returned_without_request_inference(self):
        async with AsyncClient(
            transport=ASGITransport(
                app=_app(
                    "admin",
                    reader=StaticDeploymentGuideCatalog(
                        "https://collector.example.test/metrics"
                    ),
                )
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _COOKIE)
            response = await client.get(
                "/api/v1/system/deployment-guides",
                headers={
                    "x-request-id": "guide-explicit-endpoint",
                    "host": "spoofed.example",
                    "x-forwarded-host": "other.example",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["runtimeCollector"],
            {"state": "configured", "endpoint": "https://collector.example.test/metrics"},
        )
        self.assertNotIn("spoofed.example", response.text)
        self.assertNotIn("other.example", response.text)

    async def test_unavailable_catalog_returns_redacted_service_error(self):
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", reader=_UnavailableCatalog())),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _COOKIE)
            response = await client.get(
                "/api/v1/system/deployment-guides",
                headers={"x-request-id": "guide-read-unavailable"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private deployment detail", response.text)

    async def test_static_catalog_rejects_unknown_ids_and_duplicate_paths(self):
        with self.assertRaises(ValueError):
            DeploymentGuidePath("unexpected", DeploymentGuideReadiness.GUIDE_ONLY, None)  # type: ignore[arg-type]
        duplicate = DeploymentGuidePath(
            DeploymentGuideId.EXISTING,
            DeploymentGuideReadiness.GUIDE_ONLY,
            None,
        )
        with self.assertRaises(ValueError):
            DeploymentGuidesSnapshot("catalog-1", None, (duplicate, duplicate))

    async def test_snapshot_rejects_malformed_or_credential_bearing_collector_urls(self):
        path = DeploymentGuidePath(
            DeploymentGuideId.EXISTING,
            DeploymentGuideReadiness.CONFIGURATION_REQUIRED,
            None,
        )
        for endpoint in (
            "https://",
            "https://collector.example.test/path?token=secret",
            "https://user:password@collector.example.test/metrics",
            "https://collector.example.test:99999/metrics",
            "https://collector.example.test/metrics#fragment",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                DeploymentGuidesSnapshot("catalog-1", endpoint, (path,))


if __name__ == "__main__":
    unittest.main()
