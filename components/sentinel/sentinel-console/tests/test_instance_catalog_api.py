"""Paged instance catalog API against isolated identity and telemetry readers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
import unittest

from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.instance_catalog_ports import (
    InstanceCatalogAuthorityUnavailable,
    InstanceCatalogRateLimited,
    InstanceCatalogTargetNotFound,
    InstanceIncarnationRetired,
)
from atlas_richie.sentinel_console.domain.instance_catalog import (
    METRIC_UNITS,
    OPERATIONAL_METRIC_DEFINITIONS,
    InstanceCatalogQuery,
    InstanceCatalogSnapshot,
    InstanceHealth,
    InstanceLayer,
    InstanceRuleReceipt,
    MetricQuality,
    MetricReading,
    ObservationCoverage,
    ObservationScope,
    ObservationWindow,
    ObservedInstance,
    RuleReceiptState,
)
from atlas_richie.sentinel_console.domain.instance_observation import (
    InstanceDetailQuery,
    InstanceObservation,
    MetricSample,
    MetricBundle,
    MetricQuery,
    MetricSeries,
    ObservationContext,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.api.metrics import _parse_query as parse_metrics_query
from session_test_doubles import UnusedSessionRevoker

_REQUEST_HEADERS = {"x-request-id": "instance-catalog-read-1"}
_OPAQUE_COOKIE = "synthetic-session-token-for-console-read-0001"
_FROM = datetime(2026, 10, 9, 0, 45, tzinfo=UTC)
_TO = datetime(2026, 10, 9, 1, 0, tzinfo=UTC)
_AS_OF = datetime(2026, 10, 9, 1, 0, 1, 123000, tzinfo=UTC)
_OPERATIONAL_METRIC_FACTS = OPERATIONAL_METRIC_DEFINITIONS


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


class _InstanceCatalogReader:
    def __init__(self, snapshot: InstanceCatalogSnapshot | None = None) -> None:
        self.snapshot = snapshot or _snapshot()
        self.calls = 0
        self.query: InstanceCatalogQuery | None = None

    async def read_instance_catalog(
        self, query: InstanceCatalogQuery
    ) -> InstanceCatalogSnapshot:
        self.calls += 1
        self.query = query
        return self.snapshot


class _UnavailableInstanceCatalogReader:
    async def read_instance_catalog(
        self, query: InstanceCatalogQuery
    ) -> InstanceCatalogSnapshot:
        raise InstanceCatalogAuthorityUnavailable("private telemetry detail")


class _RejectedInstanceCatalogReader:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def read_instance_catalog(
        self, query: InstanceCatalogQuery
    ) -> InstanceCatalogSnapshot:
        raise self.error


class _InstanceObservationReader:
    def __init__(self, observation: InstanceObservation) -> None:
        self.observation = observation
        self.query: InstanceDetailQuery | None = None
        self.calls = 0

    async def read_instance_observation(
        self, query: InstanceDetailQuery
    ) -> InstanceObservation:
        self.calls += 1
        self.query = query
        return self.observation


class _RejectedInstanceObservationReader:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def read_instance_observation(self, query: InstanceDetailQuery):
        raise self.error


class _MetricsReader:
    def __init__(self, bundle: MetricBundle) -> None:
        self.bundle = bundle
        self.query: MetricQuery | None = None
        self.calls = 0

    async def read_metrics(self, query: MetricQuery) -> MetricBundle:
        self.query = query
        self.calls += 1
        return self.bundle


class _RejectedMetricsReader:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def read_metrics(self, query: MetricQuery):
        raise self.error


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("instance catalog must not access account data")

    async def read_account(self, account_id: str):
        raise AssertionError("instance catalog must not access account data")


def _query(search: str = "", environment_id: str = "prod") -> InstanceCatalogQuery:
    return InstanceCatalogQuery(
        environment_id=environment_id,
        app_id=None,
        instance_id=None,
        resource=None,
        scope=ObservationScope.FLEET,
        window=ObservationWindow(_FROM, _TO),
        page=1,
        page_size=20,
        search=search,
        attention_only=False,
    )


def _instance() -> ObservedInstance:
    coverage = ObservationCoverage(None, None, 0)
    metrics = tuple(
        MetricReading(
            source="reporter-v1",
            denominator=denominator,
            coverage=coverage,
            quality=MetricQuality.NO_SAMPLES,
            metric=metric,
            unit=unit,
            value=None,
            sampled_at=None,
        )
        for metric, unit, denominator in _OPERATIONAL_METRIC_FACTS
    )
    return ObservedInstance(
        instance_id="instance-1",
        app_id="checkout",
        environment_id="prod",
        host_id="host-1",
        container_id=None,
        process_id="process-1",
        process_epoch="process-epoch-1",
        health=InstanceHealth.UNKNOWN,
        last_report_at=_FROM + timedelta(minutes=5),
        supported_scopes=(InstanceLayer.HOST, InstanceLayer.PROCESS),
        rule_receipt=InstanceRuleReceipt(
            state=RuleReceiptState.UNKNOWN,
            desired_version_id=None,
            applied_version_id=None,
            process_epoch="process-epoch-1",
            received_at=None,
        ),
        process_metrics=metrics,
    )


def _snapshot(query: InstanceCatalogQuery | None = None) -> InstanceCatalogSnapshot:
    requested = query or _query()
    return InstanceCatalogSnapshot(
        query=requested,
        as_of=_AS_OF,
        coverage=ObservationCoverage(None, None, 1),
        total_instances=1,
        attention_instances=0,
        filtered_total=1,
        items=(_instance(),),
    )


def _app(
    role: str | None,
    *,
    reader=None,
    observation_reader=None,
    metrics_reader=None,
    session_reader=None,
):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_UnusedAccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        instance_catalog_reader=reader,
        instance_observation_reader=observation_reader,
        metrics_reader=metrics_reader,
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
        "attentionOnly": "false",
    }


def _detail_query(scope: InstanceLayer = InstanceLayer.PROCESS) -> InstanceDetailQuery:
    return InstanceDetailQuery(
        environment_id="prod",
        app_id="checkout",
        instance_id="instance-1",
        resource=None,
        scope=scope,
        window=ObservationWindow(_FROM, _TO),
        process_epoch="process-epoch-1",
        step_ms=60_000,
    )


def _instance_observation(
    query: InstanceDetailQuery | None = None,
) -> InstanceObservation:
    detail_query = query or _detail_query()
    instance = _instance()
    metric_query = MetricQuery(
        context=detail_query.context,
        metrics=tuple(
            metric for metric, _unit, _denominator in _OPERATIONAL_METRIC_FACTS
        ),
        step_ms=detail_query.step_ms,
    )
    bundle = MetricBundle(
        query=metric_query,
        as_of=_AS_OF,
        summary=instance.process_metrics,
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
            for reading in instance.process_metrics
        ),
        annotations=(),
    )
    return InstanceObservation(
        query=detail_query,
        as_of=_AS_OF,
        instance=instance,
        metrics=bundle if detail_query.scope in instance.supported_scopes else None,
    )


def _detail_params(query: InstanceDetailQuery) -> dict[str, str]:
    return {
        "environmentId": query.environment_id,
        "appId": query.app_id,
        "scope": query.scope.value,
        "from": _params()["from"],
        "to": _params()["to"],
        "processEpoch": query.process_epoch,
        "stepMs": str(query.step_ms),
    }


def _metrics_query() -> MetricQuery:
    return MetricQuery(
        context=ObservationContext(
            environment_id="prod",
            app_id=None,
            instance_id=None,
            resource=None,
            scope=ObservationScope.FLEET,
            window=ObservationWindow(_FROM, _TO),
        ),
        metrics=tuple(
            metric for metric, _unit, _denominator in _OPERATIONAL_METRIC_FACTS
        ),
        step_ms=60_000,
    )


def _metrics_bundle(query: MetricQuery | None = None) -> MetricBundle:
    requested = query or _metrics_query()
    summary = tuple(
        MetricReading(
            source="reporter-v1",
            denominator=denominator,
            coverage=ObservationCoverage(None, None, 0),
            quality=MetricQuality.NO_SAMPLES,
            metric=metric,
            unit=unit,
            value=None,
            sampled_at=None,
        )
        for metric, unit, denominator in _OPERATIONAL_METRIC_FACTS
    )
    series = tuple(
        MetricSeries(
            source=reading.source,
            denominator=reading.denominator,
            coverage=reading.coverage,
            quality=reading.quality,
            metric=reading.metric,
            unit=reading.unit,
            samples=(),
        )
        for reading in summary
    )
    return MetricBundle(
        query=requested,
        as_of=_AS_OF,
        summary=summary,
        series=series,
        annotations=(),
    )


def _metrics_params(query: MetricQuery) -> dict[str, str]:
    return {
        "environmentId": query.context.environment_id,
        "scope": query.context.scope.value,
        "from": _params()["from"],
        "to": _params()["to"],
        "metrics": ",".join(query.metrics),
        "stepMs": str(query.step_ms),
    }


class InstanceCatalogApiTest(unittest.IsolatedAsyncioTestCase):
    def test_metrics_query_bound_is_derived_from_all_registered_metric_ids(self) -> None:
        def request_for(metrics: str) -> Request:
            params = {
                "environmentId": "prod",
                "scope": "fleet",
                "from": "2026-10-09T00:45:00.000Z",
                "to": "2026-10-09T01:00:00.000Z",
                "metrics": metrics,
                "stepMs": "60000",
            }
            return Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api/v1/metrics/query",
                    "query_string": urlencode(params).encode("ascii"),
                    "headers": [],
                }
            )

        registered_metrics = ",".join(METRIC_UNITS)
        query = parse_metrics_query(request_for(registered_metrics))
        self.assertEqual(query.metrics, tuple(METRIC_UNITS))
        with self.assertRaisesRegex(ValueError, "selection length is out of range"):
            parse_metrics_query(request_for(f"{registered_metrics}x"))

    def test_metrics_reject_python_integers_outside_json_finite_number_range(self) -> None:
        metric, unit, denominator = _OPERATIONAL_METRIC_FACTS[0]
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            MetricReading(
                source="reporter-v1",
                denominator=denominator,
                coverage=ObservationCoverage(1, "inventory-v1", 1),
                quality=MetricQuality.AVAILABLE,
                metric=metric,
                unit=unit,
                value=10**1000,
                sampled_at=_FROM,
            )
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            MetricSample(at=_FROM, value=10**1000)

    def test_catalog_search_limit_matches_utf16_wire_units(self) -> None:
        self.assertEqual(_query(search="😀" * 100).search, "😀" * 100)
        with self.assertRaisesRegex(ValueError, "search is out of range"):
            _query(search="😀" * 101)

    def test_observation_identifier_limit_matches_utf16_wire_units(self) -> None:
        self.assertEqual(_query(environment_id="😀" * 100).environment_id, "😀" * 100)
        with self.assertRaisesRegex(ValueError, "query identity is invalid"):
            _query(environment_id="😀" * 101)
        for blank in ("\x1c", "\x85", "\ufeff", "\u3000", "\ud800"):
            with self.subTest(blank=hex(ord(blank))):
                with self.assertRaisesRegex(ValueError, "query identity is invalid"):
                    _query(environment_id=blank)
        self.assertEqual(_query(environment_id="id\ufeff").environment_id, "id\ufeff")

    async def test_admin_and_view_receive_query_bound_authoritative_page(self) -> None:
        for role in ("admin", "view"):
            reader = _InstanceCatalogReader()
            async with AsyncClient(
                transport=ASGITransport(app=_app(role, reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/instances",
                    headers=_REQUEST_HEADERS,
                    params=_params(),
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.headers["x-request-id"], _REQUEST_HEADERS["x-request-id"]
            )
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["vary"], "Cookie")
            body = response.json()
            self.assertEqual(body["query"]["context"]["environmentId"], "prod")
            self.assertEqual(body["query"]["context"]["appId"], None)
            self.assertEqual(
                body["query"]["context"]["window"]["from"], _params()["from"]
            )
            self.assertEqual(body["asOf"], "2026-10-09T01:00:01.123Z")
            self.assertEqual(
                body["coverage"],
                {"expected": None, "inventorySource": None, "reporting": 1},
            )
            self.assertEqual(body["totalInstances"], 1)
            self.assertEqual(body["attentionInstances"], 0)
            self.assertEqual(body["filteredTotal"], 1)
            self.assertEqual(body["items"][0]["processEpoch"], "process-epoch-1")
            self.assertEqual(
                body["items"][0]["ruleReceipt"]["processEpoch"],
                "process-epoch-1",
            )
            self.assertEqual(
                {metric["metric"] for metric in body["items"][0]["processMetrics"]},
                {metric for metric, _unit, _denominator in _OPERATIONAL_METRIC_FACTS},
            )
            self.assertEqual(reader.query, _query())
            self.assertEqual(reader.calls, 1)

    async def test_detail_returns_exact_incarnation_and_scoped_metrics(self) -> None:
        for role in ("admin", "view"):
            query = _detail_query()
            reader = _InstanceObservationReader(_instance_observation(query))
            async with AsyncClient(
                transport=ASGITransport(
                    app=_app(role, observation_reader=reader)
                ),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/instances/instance-1",
                    headers=_REQUEST_HEADERS,
                    params=_detail_params(query),
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            body = response.json()
            self.assertEqual(body["query"]["processEpoch"], "process-epoch-1")
            self.assertEqual(body["instance"]["instanceId"], "instance-1")
            self.assertEqual(
                body["instance"]["ruleReceipt"]["processEpoch"],
                "process-epoch-1",
            )
            self.assertEqual(body["metrics"]["query"]["stepMs"], 60_000)
            self.assertEqual(len(body["metrics"]["summary"]), 6)
            self.assertEqual(reader.query, query)
            self.assertEqual(reader.calls, 1)

    async def test_detail_marks_unsupported_scope_without_borrowing_metrics(
        self,
    ) -> None:
        query = _detail_query(InstanceLayer.CONTAINER)
        reader = _InstanceObservationReader(_instance_observation(query))
        async with AsyncClient(
            transport=ASGITransport(
                app=_app("view", observation_reader=reader)
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/instances/instance-1",
                headers=_REQUEST_HEADERS,
                params=_detail_params(query),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["metrics"])

    async def test_detail_invalid_query_fails_before_authority_read(self) -> None:
        reader = _InstanceObservationReader(_instance_observation())
        params = _detail_params(_detail_query())
        params["scope"] = "fleet"
        async with AsyncClient(
            transport=ASGITransport(
                app=_app("view", observation_reader=reader)
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/instances/instance-1",
                headers=_REQUEST_HEADERS,
                params=params,
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertEqual(reader.calls, 0)

    async def test_detail_authority_errors_match_protocol(self) -> None:
        cases = (
            (InstanceCatalogTargetNotFound(), 404, "not_found"),
            (InstanceIncarnationRetired(), 410, "target_retired"),
            (InstanceCatalogRateLimited(900), 429, "rate_limited"),
            (
                InstanceCatalogAuthorityUnavailable("private detail"),
                503,
                "service_unavailable",
            ),
        )
        query = _detail_query()
        for error, status, code in cases:
            async with AsyncClient(
                transport=ASGITransport(
                    app=_app(
                        "view",
                        observation_reader=_RejectedInstanceObservationReader(error),
                    )
                ),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/instances/instance-1",
                    headers=_REQUEST_HEADERS,
                    params=_detail_params(query),
                )
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["error"]["code"], code)
            self.assertNotIn("private detail", response.text)

    async def test_metrics_query_returns_exact_selection_and_window(self) -> None:
        query = _metrics_query()
        reader = _MetricsReader(_metrics_bundle(query))
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", metrics_reader=reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/metrics/query",
                headers=_REQUEST_HEADERS,
                params=_metrics_params(query),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(
            response.json()["query"]["metrics"],
            list(query.metrics),
        )
        self.assertEqual(len(response.json()["summary"]), 6)
        self.assertEqual(len(response.json()["series"]), 6)
        self.assertEqual(reader.query, query)
        self.assertEqual(reader.calls, 1)

    async def test_metrics_query_rejects_invalid_selection_before_authority(
        self,
    ) -> None:
        reader = _MetricsReader(_metrics_bundle())
        params = _metrics_params(_metrics_query())
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", metrics_reader=reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            for invalid_selection in (
                "http_qps,http_qps",
                "",
                "unknown_metric",
                "http_qps,",
            ):
                response = await client.get(
                    "/api/v1/metrics/query",
                    headers=_REQUEST_HEADERS,
                    params={**params, "metrics": invalid_selection},
                )
                self.assertEqual(response.status_code, 400, invalid_selection)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "invalid_request",
                    invalid_selection,
                )
        self.assertEqual(reader.calls, 0)

    async def test_metrics_query_authority_errors_match_protocol(self) -> None:
        cases = (
            (InstanceCatalogTargetNotFound(), 404, "not_found"),
            (InstanceIncarnationRetired(), 410, "target_retired"),
            (InstanceCatalogRateLimited(500), 429, "rate_limited"),
            (
                InstanceCatalogAuthorityUnavailable("private metrics"),
                503,
                "service_unavailable",
            ),
        )
        query = _metrics_query()
        for error, status, code in cases:
            async with AsyncClient(
                transport=ASGITransport(
                    app=_app(
                        "view",
                        metrics_reader=_RejectedMetricsReader(error),
                    )
                ),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/metrics/query",
                    headers=_REQUEST_HEADERS,
                    params=_metrics_params(query),
                )
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["error"]["code"], code)
            self.assertNotIn("private metrics", response.text)

    async def test_invalid_filters_reject_before_authority_read(self) -> None:
        cases = (
            ({"page": None}, "missing required parameter"),
            ({"page": "0"}, "out of range"),
            ({"pageSize": "101"}, "page-size bound"),
            ({"attentionOnly": "yes"}, "boolean encoding"),
            ({"search": "😀" * 101}, "UTF-16 search bound"),
            ({"environmentId": "😀" * 101}, "UTF-16 identifier bound"),
            ({"environmentId": "\x1c"}, "Python/JavaScript blank identifier parity"),
            ({"environmentId": "\x85"}, "Python/JavaScript blank identifier parity"),
            ({"environmentId": "\ufeff"}, "Python/JavaScript blank identifier parity"),
            ({"from": "2026-10-09T00:45:00Z"}, "UTC millisecond precision"),
            ({"scope": "unbounded"}, "scope enum"),
            ({"scope": "application"}, "fleet/application scope binding"),
            ({"instanceId": "instance-1"}, "directory excludes detail identity"),
            ({"resource": "cpu"}, "directory excludes resource identity"),
            ({"unexpected": "1"}, "unknown parameter"),
            ({"page": ["1", "2"]}, "duplicate parameter"),
            ({"to": "2026-10-09T00:30:00.000Z"}, "reversed window"),
        )
        for replacement, _reason in cases:
            reader = _InstanceCatalogReader()
            params = _params()
            for field, value in replacement.items():
                if value is None:
                    params.pop(field)
                elif isinstance(value, list):
                    params[field] = value
                else:
                    params[field] = value
            async with AsyncClient(
                transport=ASGITransport(app=_app("view", reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/instances", headers=_REQUEST_HEADERS, params=params
                )
            self.assertEqual(response.status_code, 400, _reason)
            self.assertEqual(response.json()["error"]["code"], "invalid_request")
            self.assertEqual(reader.calls, 0)

    async def test_invalid_request_id_uses_openapi_error_code(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", reader=_InstanceCatalogReader())),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/instances",
                headers={"x-request-id": "invalid request id"},
                params=_params(),
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    async def test_anonymous_and_unavailable_session_reject_before_catalog_read(
        self,
    ) -> None:
        reader = _InstanceCatalogReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app(None, reader=reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/instances", headers=_REQUEST_HEADERS, params=_params()
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthenticated")
        self.assertEqual(reader.calls, 0)

        async with AsyncClient(
            transport=ASGITransport(
                app=_app(
                    "view",
                    reader=reader,
                    session_reader=_SessionReader("unavailable"),
                )
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/instances", headers=_REQUEST_HEADERS, params=_params()
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("private session store detail", response.text)
        self.assertEqual(reader.calls, 0)

    async def test_missing_or_unavailable_catalog_authority_fails_closed(self) -> None:
        for reader in (None, _UnavailableInstanceCatalogReader()):
            async with AsyncClient(
                transport=ASGITransport(app=_app("view", reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/instances", headers=_REQUEST_HEADERS, params=_params()
                )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "service_unavailable")
            self.assertNotIn("private telemetry detail", response.text)

    async def test_target_and_rate_limit_errors_match_openapi(self) -> None:
        cases = (
            (InstanceCatalogTargetNotFound(), 404, "not_found", None),
            (InstanceCatalogRateLimited(1250), 429, "rate_limited", 1250),
        )
        for error, status, code, retry_after_ms in cases:
            async with AsyncClient(
                transport=ASGITransport(
                    app=_app("view", reader=_RejectedInstanceCatalogReader(error))
                ),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/instances", headers=_REQUEST_HEADERS, params=_params()
                )
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["error"]["code"], code)
            self.assertEqual(
                response.json()["error"].get("retryAfterMs"), retry_after_ms
            )
            self.assertNotIn("instance catalog query rate limited", response.text)

    async def test_domain_rejects_mixed_incarnations_and_bad_counts(self) -> None:
        instance = _instance()
        with self.assertRaises(ValueError):
            ObservedInstance(
                **(
                    {
                        field: getattr(instance, field)
                        for field in instance.__dataclass_fields__
                    }
                    | {
                        "rule_receipt": InstanceRuleReceipt(
                            RuleReceiptState.UNKNOWN,
                            None,
                            None,
                            "older-epoch",
                            None,
                        )
                    }
                )
            )
        with self.assertRaises(ValueError):
            InstanceCatalogSnapshot(
                query=_query(),
                as_of=_AS_OF,
                coverage=ObservationCoverage(None, None, 1),
                total_instances=1,
                attention_instances=2,
                filtered_total=1,
                items=(instance,),
            )
        with self.assertRaises(ValueError):
            InstanceCatalogSnapshot(
                query=InstanceCatalogQuery(
                    environment_id="prod",
                    app_id=None,
                    instance_id=None,
                    resource=None,
                    scope=ObservationScope.FLEET,
                    window=ObservationWindow(_FROM, _TO),
                    page=2,
                    page_size=20,
                    search="",
                    attention_only=False,
                ),
                as_of=_AS_OF,
                coverage=ObservationCoverage(None, None, 1),
                total_instances=1,
                attention_instances=0,
                filtered_total=1,
                items=(_instance(),),
            )


if __name__ == "__main__":
    unittest.main()
