import asyncio
import json

from aiohttp import web

from atlas_richie.sentinel_console.application.monitoring_probe import (
    MonitoringProbeConnection,
    MonitoringProbeCredentials,
    MonitoringProbeFailure,
    MonitoringProbeProfile,
    MonitoringProbeQueryApi,
)
from atlas_richie.sentinel_console.domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
    MonitoringSource,
)
from atlas_richie.sentinel_console.infrastructure.monitoring_probe_composition import (
    compose_prometheus_http_adapter,
)
from atlas_richie.sentinel_console.infrastructure.monitoring_target_policy import (
    MonitoringTargetPolicy,
    MonitoringTargetRule,
    PinnedMonitoringTarget,
)
from atlas_richie.sentinel_console.infrastructure.prometheus_http_adapter import (
    PrometheusHttpAdapter,
)


def _source(**changes: object) -> MonitoringSource:
    values: dict[str, object] = {
        "source_id": "monitoring-local",
        "revision": "rev-1",
        "display_name": "Local Prometheus",
        "environment_id": "development",
        "endpoint": "http://127.0.0.1:9090/prometheus",
        "provider": MonitoringProvider.PROMETHEUS_COMPATIBLE,
        "profile": MonitoringProfile.NODE_EXPORTER_V1,
        "authentication_mode": MonitoringAuthenticationMode.NONE,
        "credential_configured": False,
        "enabled": True,
        "identity_labels": ("host",),
        "selector_labels": (MonitoringLabel("job", "node-exporter"),),
        "scrape_interval_seconds": 15,
        "stale_after_seconds": 90,
    }
    values.update(changes)
    return MonitoringSource(**values)  # type: ignore[arg-type]


def _response(metric_results: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {
            "status": "success",
            "data": {"resultType": "vector", "result": metric_results},
        }
    ).encode()


def _sample(metric: dict[str, str], value: str) -> dict[str, object]:
    return {"metric": metric, "value": ["1792261200", value]}


class _FakeTransport:
    def __init__(self, results: list[list[dict[str, object]]] | None = None) -> None:
        self.responses = results or [
            [],
            [
                _sample({"__name__": "node_cpu_seconds_total"}, "4"),
                _sample({"__name__": "node_memory_MemAvailable_bytes"}, "1"),
                _sample({"__name__": "node_memory_MemTotal_bytes"}, "1"),
                _sample({"__name__": "node_load1"}, "1"),
            ],
            [
                _sample({"host": "node-a"}, "1"),
                _sample({"host": "node-b"}, "2"),
                _sample({}, "1"),
            ],
        ]
        self.requests: list[dict[str, object]] = []

    async def request_raw(self, **request: object) -> tuple[int, bytes, dict[str, str]]:
        self.requests.append(request)
        index = len(self.requests) - 1
        return 200, _response(self.responses[index]), {}


def _adapter(
    transport: _FakeTransport, *, secure_policy: bool = False
) -> PrometheusHttpAdapter:
    if secure_policy:

        class HttpsTestPolicy:
            async def resolve(self, _endpoint: str, *, authenticated: bool):
                assert authenticated is True
                return PinnedMonitoringTarget(
                    "prometheus.internal",
                    9090,
                    ("10.0.0.2",),
                    True,  # type: ignore[arg-type]
                )

        return PrometheusHttpAdapter(HttpsTestPolicy(), transport)  # type: ignore[arg-type]
    rule = MonitoringTargetRule.create(
        "127.0.0.1",
        ("127.0.0.0/8",),
        frozenset({9090}),
        allow_loopback_http=True,
    )
    return PrometheusHttpAdapter(MonitoringTargetPolicy((rule,)), transport)


def test_probe_builds_only_fixed_queries_and_maps_profile_and_identity_counts() -> None:
    transport = _FakeTransport()
    result = asyncio.run(_adapter(transport).probe(_source()))

    assert result.connection is MonitoringProbeConnection.REACHABLE
    assert result.query_api is MonitoringProbeQueryApi.AVAILABLE
    assert result.profile is MonitoringProbeProfile.SUPPORTED
    assert (result.identity.observed, result.identity.unique) == (3, 1)
    assert (result.identity.missing, result.identity.conflicting) == (1, 1)
    assert len(transport.requests) == 3
    assert all(request["method"] == "GET" for request in transport.requests)
    assert all(
        request["headers"]["Accept-Encoding"] == "identity"
        for request in transport.requests
    )
    assert all(request["path"] == "/api/v1/query" for request in transport.requests)
    assert all(
        request["endpoint"] == _source().endpoint for request in transport.requests
    )
    queries = [request["params"]["query"] for request in transport.requests]
    assert queries[0] == "count(up)"
    assert all('job="node-exporter"' in query for query in queries[1:])
    assert all("node_cpu_seconds_total" not in query for query in (queries[0],))


def test_probe_runs_independent_prometheus_queries_concurrently() -> None:
    class ConcurrentTransport:
        active = 0
        max_active = 0

        async def request_raw(self, **request: object) -> tuple[int, bytes, dict[str, str]]:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.02)
                expression = request["params"]["query"]  # type: ignore[index]
                if expression == "count(up)":
                    samples: list[dict[str, object]] = []
                elif "node_uname_info" in expression:
                    samples = [_sample({"host": "node-a"}, "1")]
                else:
                    samples = [
                        _sample({"__name__": name}, "1")
                        for name in (
                            "node_cpu_seconds_total",
                            "node_memory_MemAvailable_bytes",
                            "node_memory_MemTotal_bytes",
                            "node_load1",
                        )
                    ]
                return 200, _response(samples), {}
            finally:
                self.active -= 1

    transport = ConcurrentTransport()
    result = asyncio.run(_adapter(transport).probe(_source()))  # type: ignore[arg-type]

    assert result.profile is MonitoringProbeProfile.SUPPORTED
    assert transport.max_active == 3


def test_probe_marks_missing_profile_families_without_failing_connection() -> None:
    transport = _FakeTransport([[], [_sample({"__name__": "node_load1"}, "1")], []])

    result = asyncio.run(_adapter(transport).probe(_source()))

    assert result.connection is MonitoringProbeConnection.REACHABLE
    assert result.query_api is MonitoringProbeQueryApi.AVAILABLE
    assert result.profile is MonitoringProbeProfile.MISSING_SAMPLES


def test_probe_reports_permission_denied_and_never_uses_raw_provider_error() -> None:
    class DeniedTransport:
        async def request_raw(self, **_request: object):
            return 403, b"user secret details", {}

    adapter = _adapter(DeniedTransport())  # type: ignore[arg-type]
    result = asyncio.run(adapter.probe(_source()))

    assert result.connection is MonitoringProbeConnection.REACHABLE
    assert result.query_api is MonitoringProbeQueryApi.DENIED
    assert result.failure is MonitoringProbeFailure.AUTHENTICATION
    assert "secret" not in repr(result)


def test_probe_rejects_malformed_prometheus_json_as_finite_unknown() -> None:
    class MalformedTransport:
        async def request_raw(self, **_request: object):
            return 200, b"not-json", {}

    result = asyncio.run(_adapter(MalformedTransport()).probe(_source()))  # type: ignore[arg-type]

    assert result.connection is MonitoringProbeConnection.REACHABLE
    assert result.query_api is MonitoringProbeQueryApi.UNKNOWN
    assert result.failure is MonitoringProbeFailure.INVALID_RESPONSE


def test_probe_authentication_requires_tls_and_never_exposes_credentials() -> None:
    transport = _FakeTransport()
    source = _source(
        endpoint="https://prometheus.internal:9090/prometheus",
        authentication_mode=MonitoringAuthenticationMode.DIRECT_BEARER,
        credential_configured=True,
    )
    credentials = MonitoringProbeCredentials(bearer_token="private-token")
    result = asyncio.run(
        _adapter(transport, secure_policy=True).probe(source, credentials)
    )
    assert result.profile is MonitoringProbeProfile.SUPPORTED
    assert all(
        request["headers"]["Authorization"] == "Bearer private-token"
        for request in transport.requests
    )
    assert "private-token" not in repr(credentials)

    rejected_transport = _FakeTransport()
    rejected = asyncio.run(_adapter(rejected_transport).probe(source, credentials))
    assert rejected.failure is MonitoringProbeFailure.TARGET_REJECTED
    assert rejected_transport.requests == []


def test_probe_sends_basic_credentials_only_as_authorization_header() -> None:
    transport = _FakeTransport()
    source = _source(
        endpoint="https://prometheus.internal:9090/prometheus",
        authentication_mode=MonitoringAuthenticationMode.DIRECT_BASIC,
        credential_configured=True,
    )
    credentials = MonitoringProbeCredentials(username="operator", password="pw")
    result = asyncio.run(
        _adapter(transport, secure_policy=True).probe(source, credentials)
    )

    assert result.profile is MonitoringProbeProfile.SUPPORTED
    assert len(transport.requests) == 3
    assert all(
        "Basic " in request["headers"]["Authorization"]
        for request in transport.requests
    )
    assert all("pw" not in repr(request["params"]) for request in transport.requests)


def test_probe_with_unresolved_credential_fails_closed_without_network_call() -> None:
    transport = _FakeTransport()
    source = _source(
        endpoint="https://prometheus.internal:9090/prometheus",
        authentication_mode=MonitoringAuthenticationMode.DIRECT_BEARER,
        credential_configured=True,
    )

    result = asyncio.run(
        _adapter(transport, secure_policy=True).probe(source, credentials=None)
    )

    assert result.query_api is MonitoringProbeQueryApi.DENIED
    assert result.failure is MonitoringProbeFailure.AUTHENTICATION
    assert transport.requests == []


def test_probe_maps_transport_timeout_to_finite_failure() -> None:
    class TimeoutTransport:
        async def request_raw(self, **_request: object):
            raise TimeoutError

    result = asyncio.run(_adapter(TimeoutTransport()).probe(_source()))  # type: ignore[arg-type]

    assert result.connection is MonitoringProbeConnection.UNREACHABLE
    assert result.failure is MonitoringProbeFailure.TIMEOUT


def test_composed_adapter_uses_real_pinned_loopback_http_transport() -> None:
    async def run() -> None:
        queries: list[str] = []

        async def query(request: web.Request) -> web.Response:
            expression = request.query.get("query", "")
            queries.append(expression)
            if expression == "count(up)":
                samples: list[dict[str, object]] = []
            elif "node_uname_info" in expression:
                samples = [_sample({"host": "node-a"}, "1")]
            else:
                samples = [
                    _sample({"__name__": name}, "1")
                    for name in (
                        "node_cpu_seconds_total",
                        "node_memory_MemAvailable_bytes",
                        "node_memory_MemTotal_bytes",
                        "node_load1",
                    )
                ]
            return web.json_response(
                {
                    "status": "success",
                    "data": {"resultType": "vector", "result": samples},
                }
            )

        application = web.Application()
        application.router.add_get("/prometheus/api/v1/query", query)
        runner = web.AppRunner(application)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        try:
            assert site._server is not None
            port = site._server.sockets[0].getsockname()[1]
            rule = MonitoringTargetRule.create(
                "127.0.0.1",
                ("127.0.0.0/8",),
                frozenset({port}),
                allow_loopback_http=True,
            )
            adapter = compose_prometheus_http_adapter((rule,))
            result = await adapter.probe(
                _source(endpoint=f"http://127.0.0.1:{port}/prometheus")
            )
            assert result.connection is MonitoringProbeConnection.REACHABLE
            assert result.query_api is MonitoringProbeQueryApi.AVAILABLE
            assert result.profile is MonitoringProbeProfile.SUPPORTED
            assert result.identity.unique == 1
            assert len(queries) == 3
        finally:
            await runner.cleanup()

    asyncio.run(run())
