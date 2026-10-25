"""Read-only Prometheus HTTP Adapter for finite monitoring probes."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import re
from typing import Protocol

import aiohttp

from ..application.monitoring_probe import (
    MonitoringIdentityPreview,
    MonitoringProbeConnection,
    MonitoringProbeCredentials,
    MonitoringProbeFailure,
    MonitoringProbePort,
    MonitoringProbeProfile,
    MonitoringProbeQueryApi,
    MonitoringProbeResult,
)
from ..domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringSource,
)
from .monitoring_target_policy import (
    MonitoringTargetPolicy,
    MonitoringTargetRejected,
    PinnedMonitoringTarget,
)

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_SERIES = 10_000
_MAX_QUERY_DEADLINE_SECONDS = 10.0
_PROFILE_METRICS = (
    "node_cpu_seconds_total",
    "node_memory_MemAvailable_bytes",
    "node_memory_MemTotal_bytes",
    "node_load1",
)
_SAFE_TOKEN = re.compile(r"^[^\r\n\x00]+$")


class MonitoringJsonTransport(Protocol):
    """Minimal pinned raw-HTTP capability used by the Prometheus adapter."""

    async def request_raw(
        self,
        *,
        target: PinnedMonitoringTarget,
        endpoint: str,
        method: str,
        path: str,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> tuple[int, bytes, dict[str, str]]: ...


class PrometheusHttpAdapter(MonitoringProbePort):
    """Translate Prometheus query responses into Console-owned probe facts."""

    def __init__(
        self, policy: MonitoringTargetPolicy, transport: MonitoringJsonTransport
    ):
        self._policy = policy
        self._transport = transport

    async def probe(
        self,
        source: MonitoringSource,
        credentials: MonitoringProbeCredentials | None = None,
    ) -> MonitoringProbeResult:
        """Check query access, profile families, and bounded host identity facts."""
        try:
            authenticated = (
                source.authentication_mode is not MonitoringAuthenticationMode.NONE
            )
            target = await self._policy.resolve(
                source.endpoint, authenticated=authenticated
            )
        except MonitoringTargetRejected:
            return _unknown(MonitoringProbeFailure.TARGET_REJECTED)

        headers = _authorization_headers(source, credentials)
        if headers is None:
            return _denied()
        selectors = _selectors(source)
        identity_group = ",".join(
            _quote_identifier(item) for item in source.identity_labels
        )
        identity_expression = (
            f"count by ({identity_group}) (node_uname_info{{{selectors}}})"
        )
        profile_expression = _profile_expression(source)

        try:
            async with asyncio.timeout(_MAX_QUERY_DEADLINE_SECONDS):
                api_response, profile_response, identity_response = await asyncio.gather(
                    self._query(target, source.endpoint, "count(up)", headers),
                    self._query(target, source.endpoint, profile_expression, headers),
                    self._query(target, source.endpoint, identity_expression, headers),
                )
                # Preserve the documented error precedence while allowing the
                # independent, read-only Prometheus queries to share one bounded
                # round-trip window instead of serially consuming the deadline.
                if isinstance(api_response, _QueryFailure):
                    return _failure_result(api_response)
                if isinstance(profile_response, _QueryFailure):
                    return _failure_result(profile_response)
                if isinstance(identity_response, _QueryFailure):
                    return _failure_result(identity_response)
                if isinstance(identity_response, _QueryFailure):
                    return _failure_result(identity_response)
        except TimeoutError:
            return _unknown(MonitoringProbeFailure.TIMEOUT)
        except (aiohttp.ClientError, OSError, ConnectionError, RuntimeError):
            return _unknown(MonitoringProbeFailure.TRANSPORT)

        profile_counts = _profile_counts(profile_response)
        if profile_counts is None:
            return _invalid_response()
        identity = _identity_counts(identity_response, source.identity_labels)
        if identity is None:
            return _invalid_response()
        missing_metrics = any(
            profile_counts.get(name, 0) <= 0 for name in _PROFILE_METRICS
        )
        return MonitoringProbeResult(
            connection=MonitoringProbeConnection.REACHABLE,
            query_api=MonitoringProbeQueryApi.AVAILABLE,
            profile=(
                MonitoringProbeProfile.MISSING_SAMPLES
                if missing_metrics
                else MonitoringProbeProfile.SUPPORTED
            ),
            identity=identity,
        )

    async def _query(
        self,
        target: PinnedMonitoringTarget,
        endpoint: str,
        expression: str,
        headers: dict[str, str],
    ) -> dict[str, object] | _QueryFailure:
        status, body, _response_headers = await self._transport.request_raw(
            target=target,
            endpoint=endpoint,
            method="GET",
            path="/api/v1/query",
            params={"query": expression},
            # The shared pinned transport intentionally disables automatic
            # decompression so its byte limit applies to the response body.
            # Prometheus commonly negotiates gzip by default; request identity
            # explicitly so the bounded JSON parser receives the wire format it
            # expects without changing the transport's decompression policy.
            headers={**headers, "Accept-Encoding": "identity"},
        )
        if status in {401, 403}:
            return _QueryFailure(
                MonitoringProbeQueryApi.DENIED,
                failure=MonitoringProbeFailure.AUTHENTICATION,
            )
        if status in {404, 405, 501}:
            return _QueryFailure(MonitoringProbeQueryApi.UNSUPPORTED)
        if not 200 <= status < 300 or len(body) > _MAX_RESPONSE_BYTES:
            return _QueryFailure(MonitoringProbeQueryApi.UNKNOWN)
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _QueryFailure(MonitoringProbeQueryApi.UNKNOWN, invalid=True)
        if not isinstance(decoded, dict) or decoded.get("status") != "success":
            return _QueryFailure(MonitoringProbeQueryApi.UNKNOWN)
        data = decoded.get("data")
        if not isinstance(data, dict) or data.get("resultType") != "vector":
            return _QueryFailure(MonitoringProbeQueryApi.UNKNOWN, invalid=True)
        result = data.get("result")
        if not isinstance(result, list) or len(result) > _MAX_SERIES:
            return _QueryFailure(MonitoringProbeQueryApi.UNKNOWN, invalid=True)
        if any(not isinstance(item, dict) for item in result):
            return _QueryFailure(MonitoringProbeQueryApi.UNKNOWN, invalid=True)
        return {"result": result}


class _QueryFailure:
    def __init__(
        self,
        query_api: MonitoringProbeQueryApi,
        invalid: bool = False,
        failure: MonitoringProbeFailure | None = None,
    ):
        self.query_api = query_api
        self.invalid = invalid
        self.failure = failure


def _authorization_headers(
    source: MonitoringSource,
    credentials: MonitoringProbeCredentials | None,
) -> dict[str, str] | None:
    if source.authentication_mode is MonitoringAuthenticationMode.NONE:
        return {} if credentials is None else None
    if credentials is None:
        return None
    if source.authentication_mode is MonitoringAuthenticationMode.DIRECT_BEARER:
        token = credentials.bearer_token
        return (
            {"Authorization": f"Bearer {token}"}
            if token and _SAFE_TOKEN.fullmatch(token)
            else None
        )
    if source.authentication_mode is MonitoringAuthenticationMode.DIRECT_BASIC:
        if (
            credentials.username is None
            or credentials.password is None
            or ":" in credentials.username
        ):
            return None
        raw = f"{credentials.username}:{credentials.password}".encode()
        encoded = base64.b64encode(raw).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}
    # Credential references are resolved by the owning secret adapter before
    # crossing this boundary; the probe never resolves arbitrary reference ids.
    if credentials.bearer_token is not None:
        return {"Authorization": f"Bearer {credentials.bearer_token}"}
    if (
        credentials.username is not None
        and credentials.password is not None
        and ":" not in credentials.username
    ):
        raw = f"{credentials.username}:{credentials.password}".encode()
        return {"Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}"}
    return None


def _selectors(source: MonitoringSource) -> str:
    return ",".join(
        f"{_quote_identifier(item.name)}={json.dumps(item.value, ensure_ascii=True)}"
        for item in source.selector_labels
    )


def _profile_expression(source: MonitoringSource) -> str:
    matchers = [f'__name__=~"{"|".join(_PROFILE_METRICS)}"']
    matchers.extend(
        f"{_quote_identifier(item.name)}={json.dumps(item.value, ensure_ascii=True)}"
        for item in source.selector_labels
    )
    return f"count by (__name__) ({{{','.join(matchers)}}})"


def _profile_counts(response: dict[str, object]) -> dict[str, int] | None:
    result = response.get("result")
    if not isinstance(result, list):
        return None
    counts: dict[str, int] = {}
    for item in result:
        metric = item.get("metric")
        value = item.get("value")
        if (
            not isinstance(metric, dict)
            or not isinstance(value, list)
            or len(value) != 2
        ):
            return None
        name = metric.get("__name__")
        parsed = _parse_sample(value[1])
        if name not in _PROFILE_METRICS or parsed is None or parsed < 0:
            return None
        if not parsed.is_integer() or name in counts:
            return None
        counts[name] = int(parsed)
    return counts


def _identity_counts(
    response: dict[str, object], identity_labels: tuple[str, ...]
) -> MonitoringIdentityPreview | None:
    result = response.get("result")
    if not isinstance(result, list):
        return None
    observed = len(result)
    missing = conflicting = unique = 0
    for item in result:
        labels = item.get("metric")
        value = item.get("value")
        if (
            not isinstance(labels, dict)
            or not isinstance(value, list)
            or len(value) != 2
        ):
            return None
        sample_count = _parse_sample(value[1])
        if sample_count is None or sample_count < 0 or not sample_count.is_integer():
            return None
        identities = tuple(labels.get(label) for label in identity_labels)
        if any(not isinstance(value, str) or not value.strip() for value in identities):
            missing += 1
        elif sample_count > 1:
            conflicting += 1
        else:
            unique += 1
    return MonitoringIdentityPreview(observed, unique, missing, conflicting)


def _parse_sample(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        sample = float(value)
    except ValueError:
        return None
    return sample if math.isfinite(sample) else None


def _quote_identifier(value: str) -> str:
    # Identifiers are domain-validated; this guard prevents accidental query
    # injection if a caller bypasses construction/deserialization boundaries.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("monitoring label identifier is invalid")
    return value


def _failure_result(failure: _QueryFailure) -> MonitoringProbeResult:
    return MonitoringProbeResult(
        connection=MonitoringProbeConnection.REACHABLE,
        query_api=failure.query_api,
        profile=MonitoringProbeProfile.UNKNOWN,
        identity=MonitoringIdentityPreview(0, 0, 0, 0),
        failure=(
            MonitoringProbeFailure.INVALID_RESPONSE
            if failure.invalid
            else failure.failure
        ),
    )


def _unknown(failure: MonitoringProbeFailure) -> MonitoringProbeResult:
    return MonitoringProbeResult(
        connection=MonitoringProbeConnection.UNREACHABLE,
        query_api=MonitoringProbeQueryApi.UNKNOWN,
        profile=MonitoringProbeProfile.UNKNOWN,
        identity=MonitoringIdentityPreview(0, 0, 0, 0),
        failure=failure,
    )


def _denied() -> MonitoringProbeResult:
    return MonitoringProbeResult(
        connection=MonitoringProbeConnection.UNREACHABLE,
        query_api=MonitoringProbeQueryApi.DENIED,
        profile=MonitoringProbeProfile.UNKNOWN,
        identity=MonitoringIdentityPreview(0, 0, 0, 0),
        failure=MonitoringProbeFailure.AUTHENTICATION,
    )


def _invalid_response() -> MonitoringProbeResult:
    return MonitoringProbeResult(
        connection=MonitoringProbeConnection.REACHABLE,
        query_api=MonitoringProbeQueryApi.UNKNOWN,
        profile=MonitoringProbeProfile.UNKNOWN,
        identity=MonitoringIdentityPreview(0, 0, 0, 0),
        failure=MonitoringProbeFailure.INVALID_RESPONSE,
    )


__all__ = ["PrometheusHttpAdapter"]
