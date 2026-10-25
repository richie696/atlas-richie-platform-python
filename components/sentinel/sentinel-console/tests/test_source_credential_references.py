"""Credential-reference resolution is explicit, ephemeral, and fail-closed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from atlas_richie.sentinel_console.application.check_registered_source import (
    CheckRegisteredSource,
    RegisteredSourceCheckResult,
    RegisteredSourceCheckUnavailable,
    SourceCheckAuthenticationMode,
    SourceCheckCapability,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application.source_credential_references import (
    ResolvedSourceCredentials,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)


_NOW = datetime(2026, 10, 9, tzinfo=UTC)
_RESULT = RegisteredSourceCheckResult(
    checked_at=_NOW,
    expires_at=_NOW + timedelta(seconds=30),
    capabilities=(SourceCheckCapability.READ,),
)


class _Checker:
    def __init__(self) -> None:
        self.commands: list[SourceConnectionInput] = []

    async def check(self, command: SourceConnectionInput, actor_id: str):
        self.commands.append(command)
        return _RESULT


class _ReferenceResolver:
    def __init__(self, credentials=None, error: Exception | None = None) -> None:
        self.credentials = credentials
        self.error = error
        self.calls: list[tuple[ConfigurationSourceProvider, str]] = []

    async def resolve(self, provider, reference):
        self.calls.append((provider, reference))
        if self.error is not None:
            raise self.error
        return self.credentials


class SourceCredentialReferenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_nacos_reference_resolves_before_probe_without_leaking_secret(self):
        checker = _Checker()
        resolver = _ReferenceResolver(
            ResolvedSourceCredentials(
                ConfigurationSourceProvider.NACOS,
                username="operator",
                password="resolved-nacos-secret",
            )
        )
        command = _reference_command(ConfigurationSourceProvider.NACOS)

        await CheckRegisteredSource(checker, None, resolver).execute(command, "admin")

        checked = checker.commands[0]
        self.assertEqual(resolver.calls, [(ConfigurationSourceProvider.NACOS, "secret://nacos/prod")])
        self.assertIs(checked.authentication_mode, SourceCheckAuthenticationMode.DIRECT)
        self.assertEqual(checked.username, "operator")
        self.assertEqual(checked.password, "resolved-nacos-secret")
        self.assertEqual(checked.endpoint, command.endpoint)
        self.assertEqual(checked.location, command.location)
        self.assertNotIn("resolved-nacos-secret", repr(checked))

    async def test_consul_reference_resolves_acl_token(self):
        checker = _Checker()
        resolver = _ReferenceResolver(
            ResolvedSourceCredentials(
                ConfigurationSourceProvider.CONSUL,
                acl_token="resolved-consul-secret",
            )
        )
        command = _reference_command(ConfigurationSourceProvider.CONSUL)

        await CheckRegisteredSource(checker, None, resolver).execute(command, "admin")

        self.assertEqual(checker.commands[0].acl_token, "resolved-consul-secret")
        self.assertIs(
            checker.commands[0].authentication_mode,
            SourceCheckAuthenticationMode.DIRECT,
        )

    async def test_missing_resolver_or_missing_secret_fails_without_probe(self):
        for resolver in (None, _ReferenceResolver(None)):
            checker = _Checker()
            with self.subTest(resolver=resolver), self.assertRaises(
                RegisteredSourceCheckUnavailable
            ):
                await CheckRegisteredSource(checker, None, resolver).execute(
                    _reference_command(ConfigurationSourceProvider.NACOS), "admin"
                )
            self.assertEqual(checker.commands, [])

    async def test_resolution_error_is_redacted_and_fails_without_probe(self):
        checker = _Checker()
        resolver = _ReferenceResolver(error=RuntimeError("vault token leaked"))

        with self.assertRaises(RegisteredSourceCheckUnavailable) as raised:
            await CheckRegisteredSource(checker, None, resolver).execute(
                _reference_command(ConfigurationSourceProvider.NACOS), "admin"
            )

        self.assertNotIn("vault token leaked", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertEqual(checker.commands, [])

    async def test_provider_mismatch_fails_closed_without_probe(self):
        checker = _Checker()
        resolver = _ReferenceResolver(
            ResolvedSourceCredentials(
                ConfigurationSourceProvider.CONSUL,
                acl_token="private-token",
            )
        )

        with self.assertRaises(RegisteredSourceCheckUnavailable):
            await CheckRegisteredSource(checker, None, resolver).execute(
                _reference_command(ConfigurationSourceProvider.NACOS), "admin"
            )

        self.assertEqual(checker.commands, [])

    async def test_direct_credentials_bypass_reference_resolver(self):
        checker = _Checker()
        resolver = _ReferenceResolver(
            error=AssertionError("direct credentials must not resolve a reference")
        )
        command = SourceConnectionInput(
            source_id=None,
            expected_revision=None,
            provider=ConfigurationSourceProvider.NACOS,
            endpoint="https://nacos.internal:8848",
            location="namespace-a",
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            username="operator",
            password="private-password",
        )

        await CheckRegisteredSource(checker, None, resolver).execute(command, "admin")

        self.assertEqual(resolver.calls, [])
        self.assertEqual(checker.commands, [command])


def _reference_command(provider: ConfigurationSourceProvider) -> SourceConnectionInput:
    is_nacos = provider is ConfigurationSourceProvider.NACOS
    return SourceConnectionInput(
        source_id=None,
        expected_revision=None,
        provider=provider,
        endpoint=(
            "https://nacos.internal:8848"
            if is_nacos
            else "https://consul.internal:8500"
        ),
        location="namespace-a" if is_nacos else "dc-east",
        authentication_mode=SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE,
        credential_reference=(
            "secret://nacos/prod" if is_nacos else "secret://consul/prod"
        ),
    )
