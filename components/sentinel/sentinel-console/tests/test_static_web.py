"""Focused tests for packaged Dashboard static delivery and SPA routing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console import app as console_app
from atlas_richie.sentinel_console.app import build_app
from session_test_doubles import UnusedSessionRevoker


class _InitializationReader:
    async def is_initialized(self) -> bool:
        return True


class _SetupWindowReader:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    async def read_active_session(self, session_digest: str):
        return None


class _AccountDirectoryReader:
    async def list_accounts(self, query):
        return ()

    async def read_account(self, account_id: str):
        return None


class StaticWebTest(unittest.IsolatedAsyncioTestCase):
    def _build_app(
        self,
        dashboard_web_directory: Path | None = None,
        dashboard_base_path: str = "/",
    ):
        return build_app(
            bootstrap_initialization_reader=_InitializationReader(),
            setup_window_reader=_SetupWindowReader(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=_SessionReader(),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_AccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            dashboard_web_directory=dashboard_web_directory,
            dashboard_base_path=dashboard_base_path,
        )

    async def test_spa_assets_and_api_not_found_have_distinct_cache_and_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            web_root = Path(temporary)
            assets = web_root / "assets"
            assets.mkdir()
            (web_root / "index.html").write_text(
                '<!doctype html><title>Console UI</title>', encoding="utf-8"
            )
            (assets / "index-0123456789abcdef.js").write_text(
                "console.log('console')", encoding="utf-8"
            )
            app = self._build_app(web_root)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://console.test"
            ) as client:
                root = await client.get("/")
                deep_link = await client.get("/overview")
                asset = await client.get("/assets/index-0123456789abcdef.js")
                api_miss = await client.get("/api/v1/not-implemented")
                api_hit = await client.get(
                    "/api/v1/system/bootstrap", headers={"x-request-id": "web-api-1"}
                )

        self.assertEqual(root.status_code, 200)
        self.assertEqual(deep_link.text, root.text)
        self.assertEqual(root.headers["cache-control"], "no-cache")
        self.assertIn("max-age=31536000", asset.headers["cache-control"])
        self.assertEqual(asset.text, "console.log('console')")
        self.assertEqual(api_miss.status_code, 404)
        self.assertEqual(api_miss.json()["error"]["code"], "not_found")
        self.assertNotIn("<title>Console UI</title>", api_miss.text)
        self.assertEqual(api_miss.headers["cache-control"], "no-store")
        self.assertEqual(api_hit.json(), {"initialized": True})
        self.assertEqual(api_hit.headers["x-request-id"], "web-api-1")

    @unittest.skipUnless(
        Path(console_app.__file__).with_name("web").is_dir(),
        "production Dashboard assets have not been packaged",
    )
    async def test_packaged_wheel_assets_are_discovered_without_node(self) -> None:
        app = self._build_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        ) as client:
            page = await client.get("/")
            route = await client.get("/rules")
            api_miss = await client.get("/api/not-registered")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Atlas Richie Sentinel Console", page.text)
        self.assertEqual(route.text, page.text)
        self.assertEqual(api_miss.status_code, 404)
        self.assertEqual(api_miss.json()["error"]["code"], "not_found")

    async def test_prefixed_dashboard_routes_keep_api_at_origin_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            web_root = Path(temporary)
            assets = web_root / "assets"
            assets.mkdir()
            (web_root / "index.html").write_text(
                '<!doctype html><title>Prefixed Console</title>'
                '<script src="/ops/sentinel/assets/app.js"></script>',
                encoding="utf-8",
            )
            (assets / "app.js").write_text("console.log('prefixed')", encoding="utf-8")
            app = self._build_app(web_root, "/ops/sentinel/")

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://console.test"
            ) as client:
                page = await client.get("/ops/sentinel/")
                deep_link = await client.get("/ops/sentinel/rules")
                asset = await client.get("/ops/sentinel/assets/app.js")
                normalized = await client.get("/ops/sentinel", follow_redirects=False)
                outside_prefix = await client.get("/rules")
                api_miss = await client.get("/api/not-registered")
                prefixed_api = await client.get("/ops/sentinel/api/not-registered")
                prefixed_api_root = await client.get("/ops/sentinel/api")

        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.text, deep_link.text)
        self.assertEqual(page.headers["cache-control"], "no-cache")
        self.assertEqual(asset.text, "console.log('prefixed')")
        self.assertIn("max-age=31536000", asset.headers["cache-control"])
        self.assertEqual(normalized.status_code, 308)
        self.assertEqual(normalized.headers["location"], "/ops/sentinel/")
        self.assertEqual(outside_prefix.status_code, 404)
        self.assertEqual(api_miss.status_code, 404)
        self.assertEqual(api_miss.json()["error"]["code"], "not_found")
        self.assertNotIn("Prefixed Console", api_miss.text)
        self.assertEqual(prefixed_api.status_code, 404)
        self.assertEqual(prefixed_api.json()["error"]["code"], "not_found")
        self.assertNotIn("Prefixed Console", prefixed_api.text)
        self.assertEqual(prefixed_api.headers["cache-control"], "no-store")
        self.assertEqual(prefixed_api_root.status_code, 404)
        self.assertEqual(prefixed_api_root.json()["error"]["code"], "not_found")

    async def test_prefixed_dashboard_rejects_noncanonical_base_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            web_root = Path(temporary)
            (web_root / "assets").mkdir()
            (web_root / "index.html").write_text("<html></html>", encoding="utf-8")

            for base_path in [
                "",
                "ops/",
                "/ops",
                "/ops//",
                "/ops/../",
                "/ops/?x=1",
                "/api/",
                "/api/dashboard/",
            ]:
                with self.subTest(base_path=base_path):
                    with self.assertRaises(ValueError):
                        self._build_app(web_root, base_path)
