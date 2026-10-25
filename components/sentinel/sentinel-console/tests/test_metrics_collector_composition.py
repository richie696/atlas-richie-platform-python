"""Composition contract for the isolated durable Metrics V2 Collector."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_collector_composition import (
    build_metrics_collector_app,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_locator_configuration import (
    RuntimeDatabaseLocatorConfiguration,
)


class MetricsCollectorCompositionTests(unittest.TestCase):
    def test_collector_mounts_only_reporter_ingress_routes(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            configuration = RuntimeDatabaseLocatorConfiguration(
                Path(temporary) / "runtime-locator.json",
                "metrics-test",
                {"metrics-test": b"m" * 32},
            )

            app = build_metrics_collector_app(configuration)

        self.assertEqual(
            [(route.path, route.methods) for route in app.routes],
            [
                (
                    "/api/reporting/v2/snapshots",
                    {"POST"},
                ),
                (
                    "/api/reporting/v1/incidents",
                    {"POST"},
                ),
                (
                    "/api/reporting/v1/protocol-negotiations/agent",
                    {"POST"},
                ),
                (
                    "/api/reporting/v1/protocol-negotiations/incident-events",
                    {"POST"},
                ),
                (
                    "/api/reporting/v1/protocol-negotiations/rule-load-observation",
                    {"POST"},
                ),
                (
                    "/api/reporting/v1/rule-publication-receipts",
                    {"POST"},
                ),
                (
                    "/api/reporting/v1/rule-load-observations",
                    {"POST"},
                ),
            ],
        )

    def test_browser_console_does_not_mount_reporter_ingress(self) -> None:
        app = build_app(
            bootstrap_initialization_reader=object(),
            setup_window_reader=object(),
            bootstrap_operator_verifier=object(),
            current_session_reader=object(),
            current_session_revoker=object(),
            account_directory_reader=object(),
            allowed_browser_origins=frozenset({"https://console.test"}),
        )

        paths = {route.path for route in app.routes if hasattr(route, "path")}
        self.assertNotIn("/api/reporting/v2/snapshots", paths)
        self.assertNotIn("/api/reporting/v1/rule-publication-receipts", paths)

    def test_missing_runtime_locator_keeps_collector_fail_closed(self) -> None:
        async def exercise() -> None:
            with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
                configuration = RuntimeDatabaseLocatorConfiguration(
                    Path(temporary) / "runtime-locator.json",
                    "metrics-test",
                    {"metrics-test": b"m" * 32},
                )
                app = build_metrics_collector_app(configuration)
                async with app.router.lifespan_context(app):
                    self.assertEqual(len(app.routes), 7)

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
