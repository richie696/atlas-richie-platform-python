import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from atlas_richie.sentinel_console.application.check_monitoring_source import (
    MONITORING_CHECK_RECEIPT_TTL,
    CheckMonitoringSource,
    CheckMonitoringSourceInput,
)
from atlas_richie.sentinel_console.application.monitoring_probe import (
    MonitoringIdentityPreview,
    MonitoringProbeConnection,
    MonitoringProbeCredentials,
    MonitoringProbeProfile,
    MonitoringProbeQueryApi,
    MonitoringProbeResult,
)
from atlas_richie.sentinel_console.domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
    MonitoringSource,
)

_NOW = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)


def _source() -> MonitoringSource:
    return MonitoringSource(
        source_id="monitoring-local",
        revision="revision-4",
        display_name="Local metrics",
        environment_id="development",
        endpoint="https://prometheus.internal:9090",
        provider=MonitoringProvider.PROMETHEUS_COMPATIBLE,
        profile=MonitoringProfile.NODE_EXPORTER_V1,
        authentication_mode=MonitoringAuthenticationMode.DIRECT_BEARER,
        credential_configured=True,
        enabled=True,
        identity_labels=("host",),
        selector_labels=(MonitoringLabel("job", "node-exporter"),),
        scrape_interval_seconds=15,
        stale_after_seconds=90,
    )


class _Probe:
    def __init__(self) -> None:
        self.calls = []

    async def probe(self, source, credentials):
        self.calls.append((source, credentials))
        return MonitoringProbeResult(
            connection=MonitoringProbeConnection.REACHABLE,
            query_api=MonitoringProbeQueryApi.AVAILABLE,
            profile=MonitoringProbeProfile.SUPPORTED,
            identity=MonitoringIdentityPreview(1, 1, 0, 0),
        )


class _Recorder:
    def __init__(self) -> None:
        self.receipts = []

    async def record_monitoring_probe_receipt(self, receipt) -> None:
        self.receipts.append(receipt)


def _check(probe: _Probe, recorder: _Recorder) -> CheckMonitoringSource:
    return CheckMonitoringSource(
        probe,
        recorder,
        fingerprint_key=b"f" * 32,
        now=lambda: _NOW,
    )


def test_check_records_session_owned_sanitized_receipt_with_ten_minute_ttl() -> None:
    probe, recorder = _Probe(), _Recorder()
    source = _source()
    credentials = MonitoringProbeCredentials(bearer_token="ephemeral-token")

    receipt = asyncio.run(
        _check(probe, recorder).execute(
            CheckMonitoringSourceInput(source, credentials),
            actor_id="admin-id",
            session_digest="a" * 64,
        )
    )

    assert recorder.receipts == [receipt]
    assert receipt.actor_id == "admin-id"
    assert receipt.session_digest == "a" * 64
    assert receipt.source_id == source.source_id
    assert receipt.source_revision == source.revision
    assert receipt.expires_at - receipt.checked_at == MONITORING_CHECK_RECEIPT_TTL
    assert len(receipt.candidate_fingerprint) == 64
    assert "ephemeral-token" not in repr(receipt)
    assert "ephemeral-token" not in repr(probe.calls)


def test_check_candidate_fingerprint_changes_when_direct_secret_changes() -> None:
    probe, recorder = _Probe(), _Recorder()
    workflow = _check(probe, recorder)

    first = asyncio.run(
        workflow.execute(
            CheckMonitoringSourceInput(
                _source(), MonitoringProbeCredentials(bearer_token="token-one")
            ),
            actor_id="admin-id",
            session_digest="a" * 64,
        )
    )
    second = asyncio.run(
        workflow.execute(
            CheckMonitoringSourceInput(
                _source(), MonitoringProbeCredentials(bearer_token="token-two")
            ),
            actor_id="admin-id",
            session_digest="a" * 64,
        )
    )

    assert first.candidate_fingerprint != second.candidate_fingerprint
    assert first.check_id != second.check_id
    assert len(recorder.receipts) == 2


def test_check_candidate_fingerprint_is_stable_for_same_inputs_and_owner_bound() -> (
    None
):
    probe, recorder = _Probe(), _Recorder()
    workflow = _check(probe, recorder)
    command = CheckMonitoringSourceInput(
        _source(), MonitoringProbeCredentials(bearer_token="stable-token")
    )

    first = asyncio.run(
        workflow.execute(command, actor_id="admin-id", session_digest="a" * 64)
    )
    second = asyncio.run(
        workflow.execute(command, actor_id="admin-id", session_digest="b" * 64)
    )

    assert first.candidate_fingerprint == second.candidate_fingerprint
    assert first.session_digest != second.session_digest
    assert first.checked_at == _NOW
    assert first.expires_at == _NOW + timedelta(minutes=10)


def test_check_rejects_credential_mode_mismatch_before_probe_or_receipt() -> None:
    probe, recorder = _Probe(), _Recorder()
    source = _source()
    with pytest.raises(ValueError):
        asyncio.run(
            _check(probe, recorder).execute(
                CheckMonitoringSourceInput(
                    source,
                    MonitoringProbeCredentials(username="user", password="secret"),
                ),
                actor_id="admin-id",
                session_digest="a" * 64,
            )
        )
    assert probe.calls == []
    assert recorder.receipts == []


def test_reference_identity_is_hmac_bound_but_never_persisted_as_plaintext() -> None:
    probe, recorder = _Probe(), _Recorder()
    workflow = _check(probe, recorder)
    source = replace(
        _source(),
        authentication_mode=MonitoringAuthenticationMode.CREDENTIAL_REFERENCE,
    )
    credentials = MonitoringProbeCredentials(bearer_token="resolved-token")
    first = asyncio.run(
        workflow.execute(
            CheckMonitoringSourceInput(source, credentials, "vault://prod/prom-a"),
            actor_id="admin-id",
            session_digest="a" * 64,
        )
    )
    second = asyncio.run(
        workflow.execute(
            CheckMonitoringSourceInput(source, credentials, "vault://prod/prom-b"),
            actor_id="admin-id",
            session_digest="a" * 64,
        )
    )
    assert first.candidate_fingerprint != second.candidate_fingerprint
    assert "vault://prod/prom-a" not in repr(first)
