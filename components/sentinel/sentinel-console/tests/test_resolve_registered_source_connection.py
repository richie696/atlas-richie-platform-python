"""Exact-revision and secret-reference resolution for trusted source workers."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel_console.application.check_registered_source import (
    RegisteredSourceCredentialsUnavailable,
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application.resolve_registered_source_connection import (
    RegisteredSourceConnectionUnavailable,
    ResolveRegisteredSourceConnection,
)
from atlas_richie.sentinel_console.application.source_credential_references import (
    ResolvedSourceCredentials,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)


class _StoredSourceResolver:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str, ConfigurationSourceProvider]] = []

    async def resolve_credentials(self, source_id, expected_revision, provider):
        self.calls.append((source_id, expected_revision, provider))
        if self.error is not None:
            raise self.error
        return self.result


class _ReferenceResolver:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[ConfigurationSourceProvider, str]] = []

    async def resolve(self, provider, reference):
        self.calls.append((provider, reference))
        if self.error is not None:
            raise self.error
        return self.result


def _source(
    mode: SourceCheckAuthenticationMode = SourceCheckAuthenticationMode.DIRECT,
    *,
    provider: ConfigurationSourceProvider = ConfigurationSourceProvider.NACOS,
    source_id: str = "source-1",
    revision: str = "revision-7",
) -> SourceConnectionInput:
    if mode is SourceCheckAuthenticationMode.DIRECT:
        credentials = (
            {"username": "operator", "password": "secret"}
            if provider is ConfigurationSourceProvider.NACOS
            else {"acl_token": "secret"}
        )
    elif mode is SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE:
        credentials = {"credential_reference": "secret://source/config"}
    else:
        credentials = {}
    return SourceConnectionInput(
        source_id=source_id,
        expected_revision=revision,
        provider=provider,
        endpoint="https://config.internal",
        location="production",
        authentication_mode=mode,
        **credentials,
    )


class ResolveRegisteredSourceConnectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_only_the_frozen_source_revision(self) -> None:
        stored = _source()
        source_resolver = _StoredSourceResolver(stored)
        service = ResolveRegisteredSourceConnection(source_resolver)

        resolved = await service.execute(
            "source-1", "revision-7", ConfigurationSourceProvider.NACOS
        )

        self.assertIs(resolved, stored)
        self.assertEqual(
            source_resolver.calls,
            [("source-1", "revision-7", ConfigurationSourceProvider.NACOS)],
        )

    async def test_allows_an_exact_unauthenticated_registered_source(self) -> None:
        stored = _source(SourceCheckAuthenticationMode.NONE)
        resolved = await ResolveRegisteredSourceConnection(
            _StoredSourceResolver(stored)
        ).execute("source-1", "revision-7", ConfigurationSourceProvider.NACOS)

        self.assertIs(resolved, stored)
        self.assertEqual(
            resolved.authentication_mode, SourceCheckAuthenticationMode.NONE
        )

    async def test_resolves_opaque_reference_to_ephemeral_direct_credentials(self) -> None:
        source_resolver = _StoredSourceResolver(
            _source(SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE)
        )
        reference_resolver = _ReferenceResolver(
            ResolvedSourceCredentials(
                ConfigurationSourceProvider.NACOS,
                username="operator",
                password="resolved-secret",
            )
        )
        service = ResolveRegisteredSourceConnection(
            source_resolver, reference_resolver
        )

        resolved = await service.execute(
            "source-1", "revision-7", ConfigurationSourceProvider.NACOS
        )

        self.assertEqual(
            resolved.authentication_mode, SourceCheckAuthenticationMode.DIRECT
        )
        self.assertEqual(resolved.username, "operator")
        self.assertEqual(resolved.password, "resolved-secret")
        self.assertIsNone(resolved.credential_reference)
        self.assertEqual(
            reference_resolver.calls,
            [(ConfigurationSourceProvider.NACOS, "secret://source/config")],
        )
        self.assertNotIn("resolved-secret", repr(resolved))

    async def test_rejects_missing_stale_or_cross_provider_source(self) -> None:
        cases = (
            None,
            _source(source_id="source-other"),
            _source(revision="revision-old"),
            _source(provider=ConfigurationSourceProvider.CONSUL),
            _source(SourceCheckAuthenticationMode.KEEP),
        )
        for result in cases:
            with self.subTest(result=result):
                service = ResolveRegisteredSourceConnection(
                    _StoredSourceResolver(result)
                )
                with self.assertRaises(RegisteredSourceConnectionUnavailable):
                    await service.execute(
                        "source-1", "revision-7", ConfigurationSourceProvider.NACOS
                    )

    async def test_sanitizes_registry_and_secret_authority_errors(self) -> None:
        registry_service = ResolveRegisteredSourceConnection(
            _StoredSourceResolver(
                error=RegisteredSourceCredentialsUnavailable("database detail")
            )
        )
        with self.assertRaises(RegisteredSourceConnectionUnavailable) as caught:
            await registry_service.execute(
                "source-1", "revision-7", ConfigurationSourceProvider.NACOS
            )
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn("database detail", str(caught.exception))

        reference_service = ResolveRegisteredSourceConnection(
            _StoredSourceResolver(
                _source(SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE)
            ),
            _ReferenceResolver(error=RuntimeError("secret backend detail")),
        )
        with self.assertRaises(RegisteredSourceConnectionUnavailable) as caught:
            await reference_service.execute(
                "source-1", "revision-7", ConfigurationSourceProvider.NACOS
            )
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn("secret backend detail", str(caught.exception))

    async def test_rejects_wrong_provider_credentials(self) -> None:
        service = ResolveRegisteredSourceConnection(
            _StoredSourceResolver(
                _source(SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE)
            ),
            _ReferenceResolver(
                ResolvedSourceCredentials(
                    ConfigurationSourceProvider.CONSUL, acl_token="secret"
                )
            ),
        )
        with self.assertRaises(RegisteredSourceConnectionUnavailable):
            await service.execute(
                "source-1", "revision-7", ConfigurationSourceProvider.NACOS
            )


if __name__ == "__main__":
    unittest.main()
