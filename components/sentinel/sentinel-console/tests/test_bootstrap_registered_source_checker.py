"""Tests for sharing the configured provider checker with first-run setup."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from atlas_richie.sentinel_console.application.bootstrap_source_check import (
    BootstrapSourceCandidate,
    BootstrapSourceFailureReason,
    BootstrapSourceProvider,
    NacosDirectCredentials,
    NoSourceAuthentication,
)
from atlas_richie.sentinel_console.application.check_registered_source import (
    RegisteredSourceCheckResult,
    SourceCheckCapability,
    SourceCheckFailureReason,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_registered_source_checker import (
    RegisteredCheckerBootstrapAdapter,
)


class _Checker:
    def __init__(self, result: RegisteredSourceCheckResult) -> None:
        self.result = result
        self.command: SourceConnectionInput | None = None

    async def check(
        self, command: SourceConnectionInput, actor_id: str
    ) -> RegisteredSourceCheckResult:
        self.command = command
        return self.result


class BootstrapRegisteredSourceCheckerTests(unittest.IsolatedAsyncioTestCase):
    async def test_nacos_direct_credentials_map_without_persisting_them(self) -> None:
        now = datetime.now(UTC)
        checker = _Checker(
            RegisteredSourceCheckResult(
                now,
                now + timedelta(seconds=60),
                capabilities=(SourceCheckCapability.READ,),
            )
        )
        adapter = RegisteredCheckerBootstrapAdapter(checker)

        result = await adapter.check(
            BootstrapSourceCandidate(
                BootstrapSourceProvider.NACOS,
                "https://nacos.internal",
                "public",
                NacosDirectCredentials("setup-user", "write-only-password"),
            )
        )

        self.assertTrue(result.reachable)
        assert checker.command is not None
        self.assertEqual(checker.command.username, "setup-user")
        self.assertEqual(checker.command.password, "write-only-password")
        self.assertNotIn("write-only-password", repr(checker.command))

    async def test_unreachable_result_maps_to_stable_failure_reason(self) -> None:
        now = datetime.now(UTC)
        checker = _Checker(
            RegisteredSourceCheckResult(
                now,
                now + timedelta(seconds=60),
                reason=SourceCheckFailureReason.AUTHENTICATION,
            )
        )
        adapter = RegisteredCheckerBootstrapAdapter(checker)

        result = await adapter.check(
            BootstrapSourceCandidate(
                BootstrapSourceProvider.CONSUL,
                "https://consul.internal",
                "dc1",
                NoSourceAuthentication(),
            )
        )

        self.assertFalse(result.reachable)
        self.assertIs(result.reason, BootstrapSourceFailureReason.AUTHENTICATION)


if __name__ == "__main__":
    unittest.main()
