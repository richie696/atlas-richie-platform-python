from __future__ import annotations

from datetime import UTC, datetime
import unittest

from atlas_richie.sentinel_console.application.registered_source_ports import (
    RegisteredSourceProbe,
    RegisteredSourcesAuthorityUnavailable,
)
from atlas_richie.sentinel_console.application.check_registered_source import (
    RegisteredSourceCheckResult,
    SourceCheckCapability,
)
from atlas_richie.sentinel_console.application.system_connections_ports import (
    SystemConnectionsAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.registered_sources import (
    RegisteredConfigurationSource,
    RegisteredSourcesSnapshot,
    SourceAuthenticationMode,
)
from atlas_richie.sentinel_console.domain.system_connections import (
    ConnectionFailureReason,
    ConnectionKind,
    ConnectionState,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_connections_reader import (
    RegisteredSourceSystemConnectionsReader,
)


_AS_OF = datetime(2026, 10, 9, 4, 0, tzinfo=UTC)


class _SourcesReader:
    def __init__(self, snapshot: RegisteredSourcesSnapshot | None = None) -> None:
        self.snapshot = snapshot or RegisteredSourcesSnapshot(_AS_OF, ())

    async def read_registered_sources(self) -> RegisteredSourcesSnapshot:
        return self.snapshot


class _UnavailableSourcesReader:
    async def read_registered_sources(self) -> RegisteredSourcesSnapshot:
        raise RegisteredSourcesAuthorityUnavailable("private SQL details")


class _ProbeReader:
    def __init__(self, probes: tuple[RegisteredSourceProbe, ...]) -> None:
        self.probes = probes
        self.requested_sources: tuple[tuple[str, str], ...] | None = None

    async def read_registered_source_probes(self, sources):
        self.requested_sources = sources
        return self.probes


def _source(source_id: str, provider: ConfigurationSourceProvider):
    return RegisteredConfigurationSource(
        id=source_id,
        revision="3",
        name=f"source-{source_id}",
        endpoint="https://config.example.test",
        provider=provider,
        location="public",
        authentication_mode=SourceAuthenticationMode.NONE,
        credential_configured=False,
    )


class RegisteredSourceSystemConnectionsReaderTest(unittest.IsolatedAsyncioTestCase):
    async def test_probe_is_joined_only_to_the_exact_source_revision(self) -> None:
        source = _source("nacos-main", ConfigurationSourceProvider.NACOS)
        checked = RegisteredSourceCheckResult(
            checked_at=datetime(2026, 10, 9, 3, 0, tzinfo=UTC),
            expires_at=datetime(2026, 10, 9, 5, 0, tzinfo=UTC),
            capabilities=(SourceCheckCapability.READ,),
            latency_ms=12.5,
        )
        stale_probe_reader = _ProbeReader(
            (RegisteredSourceProbe(source.id, "2", checked),)
        )
        stale_reader = RegisteredSourceSystemConnectionsReader(
            _SourcesReader(RegisteredSourcesSnapshot(_AS_OF, (source,))),
            stale_probe_reader,
        )

        stale_result = await stale_reader.read_system_connections()

        stale_connection = stale_result.items[0]
        self.assertEqual(stale_probe_reader.requested_sources, ((source.id, "3"),))
        self.assertIs(stale_connection.state, ConnectionState.UNKNOWN)
        self.assertIs(stale_connection.reason, ConnectionFailureReason.NO_PROBE)
        self.assertIsNone(stale_connection.checked_at)

        current_probe_reader = _ProbeReader(
            (RegisteredSourceProbe(source.id, source.revision, checked),)
        )
        current_reader = RegisteredSourceSystemConnectionsReader(
            _SourcesReader(RegisteredSourcesSnapshot(_AS_OF, (source,))),
            current_probe_reader,
        )
        current_result = await current_reader.read_system_connections()

        self.assertIs(current_result.items[0].state, ConnectionState.AVAILABLE)
        self.assertEqual(current_result.items[0].latency_ms, 12.5)

    async def test_duplicate_current_revision_probes_fail_closed(self) -> None:
        source = _source("nacos-main", ConfigurationSourceProvider.NACOS)
        checked = RegisteredSourceCheckResult(
            checked_at=datetime(2026, 10, 9, 3, 0, tzinfo=UTC),
            expires_at=datetime(2026, 10, 9, 5, 0, tzinfo=UTC),
            capabilities=(SourceCheckCapability.READ,),
            latency_ms=12.5,
        )
        reader = RegisteredSourceSystemConnectionsReader(
            _SourcesReader(RegisteredSourcesSnapshot(_AS_OF, (source,))),
            _ProbeReader(
                (
                    RegisteredSourceProbe(source.id, source.revision, checked),
                    RegisteredSourceProbe(source.id, source.revision, checked),
                )
            ),
        )

        with self.assertRaisesRegex(
            SystemConnectionsAuthorityUnavailable, "duplicate facts"
        ):
            await reader.read_system_connections()

    async def test_registered_sources_are_visible_but_never_claim_probe_success(self) -> None:
        reader = RegisteredSourceSystemConnectionsReader(
            _SourcesReader(
                RegisteredSourcesSnapshot(
                    _AS_OF,
                    (
                        _source("nacos-main", ConfigurationSourceProvider.NACOS),
                        _source("consul-main", ConfigurationSourceProvider.CONSUL),
                    ),
                )
            )
        )

        result = await reader.read_system_connections()

        self.assertEqual(result.as_of, _AS_OF)
        self.assertEqual(
            [item.id for item in result.items], ["nacos-main", "consul-main"]
        )
        self.assertEqual(
            [item.provider for item in result.items],
            [ConfigurationSourceProvider.NACOS, ConfigurationSourceProvider.CONSUL],
        )
        self.assertTrue(
            all(
                item.kind is ConnectionKind.CONFIG_CENTER
                and item.state is ConnectionState.UNKNOWN
                and item.reason is ConnectionFailureReason.NO_PROBE
                and item.checked_at is None
                and item.expires_at is None
                and item.latency_ms is None
                and item.capabilities == ()
                for item in result.items
            )
        )
        self.assertNotIn("https://config.example.test", repr(result))

    async def test_empty_registry_is_explicitly_unconfigured(self) -> None:
        reader = RegisteredSourceSystemConnectionsReader(_SourcesReader())

        result = await reader.read_system_connections()

        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.id, "config-center")
        self.assertIsNone(item.source_id)
        self.assertIsNone(item.provider)
        self.assertIs(item.state, ConnectionState.UNCONFIGURED)
        self.assertIs(item.reason, ConnectionFailureReason.NOT_CONFIGURED)
        self.assertEqual(result.as_of, _AS_OF)

    async def test_registry_failure_maps_to_safe_connection_authority_failure(self) -> None:
        reader = RegisteredSourceSystemConnectionsReader(_UnavailableSourcesReader())

        with self.assertRaisesRegex(
            SystemConnectionsAuthorityUnavailable,
            "registered configuration source authority is unavailable",
        ) as raised:
            await reader.read_system_connections()

        self.assertNotIn("private SQL details", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
