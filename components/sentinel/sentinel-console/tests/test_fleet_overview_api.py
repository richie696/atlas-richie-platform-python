"""Fleet overview API contract against isolated session and telemetry authorities."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.fleet_overview_ports import (
    FleetOverviewAuthorityUnavailable,
    FleetOverviewRateLimited,
    FleetOverviewTargetNotFound,
)
from atlas_richie.sentinel_console.domain.fleet_overview import (
    FleetApplication,
    FleetApplicationHealth,
    FleetApplicationPage,
    FleetConnection,
    FleetConnectionProvider,
    FleetConnectionState,
    FleetQuery,
    FleetSnapshot,
)
from atlas_richie.sentinel_console.domain.instance_catalog import (
    OPERATIONAL_METRIC_DEFINITIONS,
    OPERATIONAL_METRIC_NAMES,
    MetricQuality,
    MetricReading,
    ObservationCoverage,
    ObservationScope,
    ObservationWindow,
)
from atlas_richie.sentinel_console.domain.instance_observation import (
    MetricBundle,
    MetricQuery,
    MetricSeries,
    ObservationContext,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from session_test_doubles import UnusedSessionRevoker

_REQUEST_HEADERS = {"x-request-id": "fleet-overview-read-1"}
_OPAQUE_COOKIE = "synthetic-session-token-for-fleet-read-0001"
_FROM = datetime(2026, 10, 9, 0, 45, tzinfo=UTC)
_TO = datetime(2026, 10, 9, 1, 0, tzinfo=UTC)
_AS_OF = datetime(2026, 10, 9, 1, 0, 1, 123000, tzinfo=UTC)


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


class _FleetReader:
    def __init__(self, snapshot: FleetSnapshot | None = None, error=None) -> None:
        self.snapshot = snapshot or _snapshot()
        self.error = error
        self.query: FleetQuery | None = None
        self.calls = 0

    async def read_fleet_overview(self, query: FleetQuery) -> FleetSnapshot:
        self.query = query
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.snapshot


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("fleet overview must not access account data")

    async def read_account(self, account_id: str):
        raise AssertionError("fleet overview must not access account data")


def _query() -> FleetQuery:
    return FleetQuery(
        context=ObservationContext(
            environment_id="prod",
            app_id=None,
            instance_id=None,
            resource=None,
            scope=ObservationScope.FLEET,
            window=ObservationWindow(_FROM, _TO),
        ),
        page=1,
        page_size=20,
        search="",
        step_ms=60_000,
    )


def _metric_readings() -> tuple[MetricReading, ...]:
    return tuple(
        MetricReading(
            source="telemetry-v1",
            denominator=denominator,
            coverage=ObservationCoverage(None, None, 0),
            quality=MetricQuality.NOT_INTEGRATED,
            metric=metric,
            unit=unit,
            value=None,
            sampled_at=None,
        )
        for metric, unit, denominator in OPERATIONAL_METRIC_DEFINITIONS
    )


def _metric_bundle(query: FleetQuery) -> MetricBundle:
    metric_query = MetricQuery(
        context=query.context,
        metrics=OPERATIONAL_METRIC_NAMES,
        step_ms=query.step_ms,
    )
    readings = _metric_readings()
    return MetricBundle(
        query=metric_query,
        as_of=_AS_OF,
        summary=readings,
        series=tuple(
            MetricSeries(
                source=reading.source,
                denominator=reading.denominator,
                coverage=reading.coverage,
                quality=reading.quality,
                metric=reading.metric,
                unit=reading.unit,
                samples=(),
            )
            for reading in readings
        ),
        annotations=(),
    )


def _snapshot(query: FleetQuery | None = None) -> FleetSnapshot:
    selected = query or _query()
    readings = _metric_readings()
    return FleetSnapshot(
        query=selected,
        as_of=_AS_OF,
        coverage=ObservationCoverage(None, None, 0),
        total_applications=1,
        attention_applications=0,
        attention_targets=(),
        applications=FleetApplicationPage(
            items=(
                FleetApplication(
                    app_id="checkout",
                    name="Checkout API",
                    health=FleetApplicationHealth.UNKNOWN,
                    instance_coverage=ObservationCoverage(None, None, 0),
                    rule_coverage=ObservationCoverage(None, None, 0),
                    metrics=readings,
                ),
            ),
            total=1,
            page=selected.page,
            page_size=selected.page_size,
        ),
        metrics=_metric_bundle(selected),
        connections=(
            FleetConnection(
                id="collector-primary",
                provider=FleetConnectionProvider.COLLECTOR,
                state=FleetConnectionState.UNKNOWN,
                checked_at=_AS_OF,
                latency_ms=None,
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
        fleet_overview_reader=reader,
    )


def _params() -> dict[str, str]:
    return {
        "environmentId": "prod",
        "scope": "fleet",
        "from": "2026-10-09T00:45:00.000Z",
        "to": "2026-10-09T01:00:00.000Z",
        "page": "1",
        "pageSize": "20",
        "search": "",
        "stepMs": "60000",
    }


class FleetOverviewApiTest(unittest.IsolatedAsyncioTestCase):
    def test_connection_rejects_python_integer_outside_json_finite_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "fleet connection latency is invalid"):
            FleetConnection(
                id="collector-primary",
                provider=FleetConnectionProvider.COLLECTOR,
                state=FleetConnectionState.UNKNOWN,
                checked_at=_AS_OF,
                latency_ms=10**1000,
            )

    def test_fleet_query_search_uses_utf16_units_and_unicode_scalars(self) -> None:
        for invalid_search in ("🌋" * 101, "invalid-\ud800"):
            with self.subTest(search=repr(invalid_search)):
                with self.assertRaisesRegex(ValueError, "fleet search is out of range"):
                    FleetQuery(
                        context=_query().context,
                        page=1,
                        page_size=20,
                        search=invalid_search,
                        step_ms=60_000,
                    )

    async def test_admin_and_viewer_receive_exact_authority_snapshot(self) -> None:
        expected = _snapshot()
        for role in ("admin", "view"):
            reader = _FleetReader(expected)
            async with AsyncClient(
                transport=ASGITransport(app=_app(role, reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/fleet/overview", params=_params(), headers=_REQUEST_HEADERS
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.headers["x-request-id"], _REQUEST_HEADERS["x-request-id"]
            )
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["vary"], "Cookie")
            body = response.json()
            self.assertEqual(body["totalApplications"], 1)
            self.assertEqual(body["applications"]["items"][0]["appId"], "checkout")
            self.assertEqual(body["applications"]["items"][0]["health"], "unknown")
            self.assertEqual(
                body["metrics"]["query"]["metrics"],
                list(OPERATIONAL_METRIC_NAMES),
            )
            self.assertEqual(body["connections"][0]["state"], "unknown")
            self.assertEqual(reader.query, _query())
            self.assertEqual(reader.calls, 1)

    async def test_anonymous_request_is_rejected_before_authority_read(self) -> None:
        reader = _FleetReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app(None, reader=reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/fleet/overview", params=_params(), headers=_REQUEST_HEADERS
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthenticated")
        self.assertEqual(reader.calls, 0)

    async def test_application_scope_is_forwarded_without_borrowing_fleet_scope(
        self,
    ) -> None:
        query = FleetQuery(
            context=ObservationContext(
                environment_id="prod",
                app_id="checkout",
                instance_id=None,
                resource=None,
                scope=ObservationScope.APPLICATION,
                window=ObservationWindow(_FROM, _TO),
            ),
            page=1,
            page_size=20,
            search="",
            step_ms=60_000,
        )
        reader = _FleetReader(_snapshot(query))
        params = {**_params(), "appId": "checkout", "scope": "application"}
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", reader=reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/fleet/overview", params=params, headers=_REQUEST_HEADERS
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(reader.query, query)
        self.assertEqual(response.json()["query"]["context"]["scope"], "application")
        self.assertEqual(
            response.json()["applications"]["items"][0]["appId"], "checkout"
        )

    async def test_invalid_queries_do_not_reach_authority(self) -> None:
        invalid_queries = (
            {**_params(), "scope": "application"},
            {**_params(), "instanceId": "instance-1"},
            {**_params(), "resource": "POST /api/orders"},
            {**_params(), "pageSize": "101"},
            {**_params(), "from": "2026-10-09T01:00:00.000Z"},
            {**_params(), "search": "🌋" * 101},
        )
        reader = _FleetReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", reader=reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            for params in invalid_queries:
                response = await client.get(
                    "/api/v1/fleet/overview", params=params, headers=_REQUEST_HEADERS
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_request")
            duplicate = await client.get(
                "/api/v1/fleet/overview?" + "&".join(
                    f"{key}={value}" for key, value in _params().items()
                ) + "&page=2",
                headers=_REQUEST_HEADERS,
            )

        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(reader.calls, 0)

    async def test_missing_and_failed_authority_are_sanitized(self) -> None:
        unavailable_reader = _FleetReader(
            error=FleetOverviewAuthorityUnavailable("private")
        )
        for reader in (None, unavailable_reader):
            async with AsyncClient(
                transport=ASGITransport(app=_app("view", reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/fleet/overview", params=_params(), headers=_REQUEST_HEADERS
                )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "service_unavailable")
            self.assertNotIn("private", response.text)

    async def test_target_and_rate_limit_errors_use_stable_wire_codes(self) -> None:
        for error, status, code in (
            (FleetOverviewTargetNotFound("private"), 404, "not_found"),
            (FleetOverviewRateLimited(250), 429, "rate_limited"),
        ):
            async with AsyncClient(
                transport=ASGITransport(
                    app=_app("view", reader=_FleetReader(error=error))
                ),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/fleet/overview", params=_params(), headers=_REQUEST_HEADERS
                )
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["error"]["code"], code)
            if status == 429:
                self.assertEqual(response.json()["error"]["retryAfterMs"], 250)

    async def test_mismatched_authority_snapshot_fails_closed(self) -> None:
        requested = _query()
        foreign_query = FleetQuery(
            context=ObservationContext(
                environment_id="other",
                app_id=None,
                instance_id=None,
                resource=None,
                scope=ObservationScope.FLEET,
                window=ObservationWindow(_FROM, _TO),
            ),
            page=requested.page,
            page_size=requested.page_size,
            search=requested.search,
            step_ms=requested.step_ms,
        )
        reader = _FleetReader(_snapshot(foreign_query))
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", reader=reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/fleet/overview", params=_params(), headers=_REQUEST_HEADERS
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("other", response.text)


if __name__ == "__main__":
    unittest.main()
