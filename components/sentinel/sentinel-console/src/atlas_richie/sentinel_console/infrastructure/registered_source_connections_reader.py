"""Project registered source facts into truthful system connection observations."""

from __future__ import annotations

from ..application.registered_source_ports import (
    RegisteredSourceProbe,
    RegisteredSourceProbeAuthorityUnavailable,
    RegisteredSourceProbeReader,
    RegisteredSourcesAuthorityUnavailable,
    RegisteredSourcesReader,
)
from ..application.system_connections_ports import (
    SystemConnectionsAuthorityUnavailable,
    SystemConnectionsReader,
)
from ..domain.system_connections import (
    ConnectionFailureReason,
    ConnectionKind,
    ConnectionCapability,
    ConnectionObservation,
    ConnectionState,
    SystemConnectionsSnapshot,
)


class RegisteredSourceSystemConnectionsReader(SystemConnectionsReader):
    """Expose registered config centers without claiming an unperformed probe.

    Persisted registration is configuration evidence only. Health, latency and
    capabilities remain unknown until a separate trusted probe authority
    supplies those facts. Probe facts are joined only on the exact source revision.
    """

    def __init__(
        self,
        sources: RegisteredSourcesReader,
        probes: RegisteredSourceProbeReader | None = None,
    ) -> None:
        self._sources = sources
        self._probes = probes

    async def read_system_connections(self) -> SystemConnectionsSnapshot:
        """Return config-center registration status with no fabricated health."""
        try:
            snapshot = await self._sources.read_registered_sources()
        except RegisteredSourcesAuthorityUnavailable:
            raise SystemConnectionsAuthorityUnavailable(
                "registered configuration source authority is unavailable"
            ) from None

        if snapshot.items:
            probe_by_source_revision = {}
            if self._probes is not None:
                try:
                    probes = await self._probes.read_registered_source_probes(
                        tuple((source.id, source.revision) for source in snapshot.items)
                    )
                except RegisteredSourceProbeAuthorityUnavailable:
                    raise SystemConnectionsAuthorityUnavailable(
                        "registered source probe authority is unavailable"
                    ) from None
                current_source_revisions = {
                    (source.id, source.revision) for source in snapshot.items
                }
                for probe in probes:
                    if not isinstance(probe, RegisteredSourceProbe):
                        raise SystemConnectionsAuthorityUnavailable(
                            "registered source probe authority returned invalid facts"
                        )
                    identity = (probe.source_id, probe.revision)
                    if identity not in current_source_revisions:
                        continue
                    if identity in probe_by_source_revision:
                        raise SystemConnectionsAuthorityUnavailable(
                            "registered source probe authority returned duplicate facts"
                        )
                    probe_by_source_revision[identity] = probe
            observations = tuple(
                _observation(
                    source,
                    probe_by_source_revision.get((source.id, source.revision)),
                )
                for source in snapshot.items
            )
        else:
            observations = (
                ConnectionObservation(
                    id="config-center",
                    kind=ConnectionKind.CONFIG_CENTER,
                    source_id=None,
                    provider=None,
                    state=ConnectionState.UNCONFIGURED,
                    checked_at=None,
                    expires_at=None,
                    latency_ms=None,
                    capabilities=(),
                    reason=ConnectionFailureReason.NOT_CONFIGURED,
                ),
            )
        return SystemConnectionsSnapshot(as_of=snapshot.as_of, items=observations)


def _observation(source, probe):
    if probe is None:
        state = ConnectionState.UNKNOWN
        checked_at = expires_at = latency_ms = None
        capabilities = ()
        reason = ConnectionFailureReason.NO_PROBE
    else:
        result = probe.result
        state = (
            ConnectionState.AVAILABLE
            if result.reachable
            else ConnectionState.UNAVAILABLE
        )
        checked_at = result.checked_at
        expires_at = result.expires_at
        latency_ms = result.latency_ms
        capabilities = tuple(
            ConnectionCapability(capability.value)
            for capability in result.capabilities
        )
        reason = (
            ConnectionFailureReason(result.reason.value)
            if result.reason is not None
            else None
        )
    return ConnectionObservation(
        id=source.id,
        kind=ConnectionKind.CONFIG_CENTER,
        source_id=source.id,
        provider=source.provider,
        state=state,
        checked_at=checked_at,
        expires_at=expires_at,
        latency_ms=latency_ms,
        capabilities=capabilities,
        reason=reason,
    )


__all__ = ["RegisteredSourceSystemConnectionsReader"]
