"""Focused contract tests for the final live-E2E consumer driver."""

from __future__ import annotations

import asyncio
import importlib.util
import ssl
import sys
from pathlib import Path

import httpx
import pytest
from atlas_richie.sentinel.metrics.snapshot import MetricSnapshot
from atlas_richie.sentinel.ports.system_metric_sampler import SystemSnapshot
from atlas_richie.sentinel.reporting import (
    HttpMetricSnapshot,
    MetricCaptureSource,
)
from atlas_richie.sentinel_reporter_incidents import IncidentTlsCredential
from atlas_richie.sentinel_reporter_v2 import MetricsV2TlsCredential

_DRIVER_PATH = (
    Path(__file__).parents[1] / "tools" / "e2e" / "consumer_runtime_driver.py"
)
_DRIVER_SPEC = importlib.util.spec_from_file_location(
    "sentinel_console_e2e_consumer_runtime_driver", _DRIVER_PATH
)
assert _DRIVER_SPEC is not None and _DRIVER_SPEC.loader is not None
_DRIVER = importlib.util.module_from_spec(_DRIVER_SPEC)
sys.modules[_DRIVER_SPEC.name] = _DRIVER
_DRIVER_SPEC.loader.exec_module(_DRIVER)
_build_capture_batch = _DRIVER._build_capture_batch
_negotiate = _DRIVER._negotiate
_TlsCredentialSource = _DRIVER._TlsCredentialSource
_MetricsTlsCredentialProvider = _DRIVER._MetricsTlsCredentialProvider
_IncidentTlsCredentialProvider = _DRIVER._IncidentTlsCredentialProvider


def test_driver_adapts_shared_tls_context_to_each_reporter_provider_port() -> None:
    context = ssl.create_default_context()
    source = _TlsCredentialSource(context, "e2e-generation")
    metrics_provider = _MetricsTlsCredentialProvider(source)
    incident_provider = _IncidentTlsCredentialProvider(source)

    async def read_credentials() -> tuple[object, object]:
        return await metrics_provider.current(), await incident_provider.current()

    metrics_credential, incident_credential = asyncio.run(read_credentials())

    assert isinstance(metrics_credential, MetricsV2TlsCredential)
    assert isinstance(incident_credential, IncidentTlsCredential)
    assert metrics_credential.generation == incident_credential.generation
    assert metrics_credential.ssl_context is context
    assert incident_credential.ssl_context is context


def test_driver_builds_explicit_process_http_and_resource_captures() -> None:
    captures = _build_capture_batch(
        completed_requests=90,
        captured_at_ns=1_800_000_000_000_000_000,
    )

    assert tuple(capture.source for capture in captures) == (
        MetricCaptureSource.ENTRY,
        MetricCaptureSource.HTTP,
        MetricCaptureSource.SYSTEM,
    )
    resource, http, system = (capture.snapshot for capture in captures)
    assert isinstance(resource, MetricSnapshot)
    assert resource.admitted == 86
    assert resource.blocked == 4
    assert isinstance(http, HttpMetricSnapshot)
    assert http.completed_requests == 90
    assert http.latency_histogram.sample_count == 90
    assert isinstance(system, SystemSnapshot)
    assert system.cpu_usage == 0.42
    assert system.memory_ratio == 0.61


def test_driver_rejects_empty_or_negative_http_sample() -> None:
    with pytest.raises(ValueError, match="completed_requests must be positive"):
        _build_capture_batch(completed_requests=0, captured_at_ns=1)


def test_driver_uses_the_authenticated_peer_negotiation_response() -> None:
    observed_paths: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        observed_paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "boundary": "agent-reporting",
                "runtime_version": "atlas-richie.reporting/v1",
                "compatibility": "compatible",
            },
        )

    async def exercise() -> str:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
            base_url="https://collector.test",
        ) as client:
            return await _negotiate(
                client,
                path="/api/reporting/v1/protocol-negotiations/agent",
                protocol_version="atlas-richie.reporting/v1",
                expected_boundary="agent-reporting",
            )

    compatibility = asyncio.run(exercise())

    assert compatibility == "compatible"
    assert observed_paths == ["/api/reporting/v1/protocol-negotiations/agent"]
