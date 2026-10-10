"""Opt-in acceptance against a private, disposable Consul dev server."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
import unittest
from urllib.request import urlopen
from uuid import uuid4

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceCheckCapability,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_reader import (
    ConsulRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_writer import (
    ConsulRuleSourceConflict,
    ConsulRuleSourceWrite,
    ConsulRuleSourceWriter,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    ConsulRegisteredSourceChecker,
    PinnedAioHttpJsonClient,
    PinnedSourceTarget,
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)

_RUN_ACCEPTANCE = os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE") == "1"
_CONSUL_IMAGE = "hashicorp/consul:1.21.1"


class _CreateCasBarrierClient(PinnedAioHttpJsonClient):
    """Release exactly two create-CAS requests together at the transport edge."""

    def __init__(self) -> None:
        super().__init__()
        self._arrivals = 0
        self._lock = asyncio.Lock()
        self._both_arrived = asyncio.Event()

    async def request_raw(
        self,
        *,
        target: PinnedSourceTarget,
        endpoint: str,
        method: str,
        path: str,
        params: dict[str, str],
        headers: dict[str, str],
        form: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        if method == "PUT" and params == {
            "dc": "dc1",
            "cas": "0",
        }:
            async with self._lock:
                self._arrivals += 1
                if self._arrivals == 2:
                    self._both_arrived.set()
            await self._both_arrived.wait()
        return await super().request_raw(
            target=target,
            endpoint=endpoint,
            method=method,
            path=path,
            params=params,
            headers=headers,
            form=form,
            body=body,
        )


@unittest.skipUnless(
    _RUN_ACCEPTANCE,
    "set SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 to start a disposable Consul",
)
class ConsulRuleSourceWriterAcceptanceTest(unittest.IsolatedAsyncioTestCase):
    """Verify real server CAS semantics without touching a configured Consul."""

    async def asyncSetUp(self) -> None:
        self.container_name = f"sentinel-consul-cas-{uuid4().hex[:12]}"
        self._started = False
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    self.container_name,
                    "--publish",
                    "127.0.0.1::8500/tcp",
                    _CONSUL_IMAGE,
                    "agent",
                    "-dev",
                    "-client=0.0.0.0",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self._started = True
            port_output = subprocess.run(
                ["docker", "port", self.container_name, "8500/tcp"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            self.port = int(port_output.rsplit(":", 1)[1])
            self.endpoint = f"http://127.0.0.1:{self.port}"
            self._wait_until_ready()
        except BaseException:
            self._remove_container()
            raise

    async def asyncTearDown(self) -> None:
        self._remove_container()

    async def test_create_update_and_stale_revision_use_real_consul_cas(self) -> None:
        test_key = f"sentinel/acceptance/{uuid4().hex}/rules.json"
        first_value = b'[{"rule":"first"}]'
        second_value = b'[{"rule":"second"}]'
        policy = RegisteredSourceTargetPolicy(
            [
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.CONSUL,
                    "127.0.0.1",
                    ["127.0.0.1/32"],
                    frozenset({self.port}),
                )
            ]
        )
        connection = SourceConnectionInput(
            source_id=None,
            expected_revision=None,
            provider=ConfigurationSourceProvider.CONSUL,
            endpoint=self.endpoint,
            location="dc1",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )
        writer = ConsulRuleSourceWriter(policy)
        reader = ConsulRuleSourceReader(policy)

        created = await writer.write(
            ConsulRuleSourceWrite(connection, test_key, None, first_value)
        )
        self.assertGreater(int(created.modify_index), 0)

        first_read = await reader.read(connection, test_key)
        self.assertEqual(first_read.value, first_value)
        self.assertEqual(first_read.modify_index, created.modify_index)

        updated = await writer.write(
            ConsulRuleSourceWrite(
                connection, test_key, created.modify_index, second_value
            )
        )
        self.assertGreater(int(updated.modify_index), int(created.modify_index))

        with self.assertRaises(ConsulRuleSourceConflict):
            await writer.write(
                ConsulRuleSourceWrite(
                    connection, test_key, created.modify_index, first_value
                )
            )

        final_read = await reader.read(connection, test_key)
        self.assertEqual(final_read.value, second_value)
        self.assertEqual(final_read.modify_index, updated.modify_index)

    async def test_two_create_writers_have_one_server_side_cas_winner(self) -> None:
        test_key = f"sentinel/acceptance/{uuid4().hex}/race.json"
        candidates = (
            b'[{"candidate":"alpha"}]',
            b'[{"candidate":"beta"}]',
        )
        policy = RegisteredSourceTargetPolicy(
            [
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.CONSUL,
                    "127.0.0.1",
                    ["127.0.0.1/32"],
                    frozenset({self.port}),
                )
            ]
        )
        connection = SourceConnectionInput(
            source_id=None,
            expected_revision=None,
            provider=ConfigurationSourceProvider.CONSUL,
            endpoint=self.endpoint,
            location="dc1",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )
        writer = ConsulRuleSourceWriter(policy, _CreateCasBarrierClient())
        reader = ConsulRuleSourceReader(policy)

        async def attempt(candidate: bytes) -> tuple[bytes, str | None]:
            try:
                receipt = await writer.write(
                    ConsulRuleSourceWrite(connection, test_key, None, candidate)
                )
            except ConsulRuleSourceConflict:
                return candidate, None
            return candidate, receipt.modify_index

        results = await asyncio.gather(*(attempt(candidate) for candidate in candidates))
        winners = [(candidate, revision) for candidate, revision in results if revision]
        losers = [(candidate, revision) for candidate, revision in results if not revision]

        self.assertEqual(len(winners), 1)
        self.assertEqual(len(losers), 1)
        current = await reader.read(connection, test_key)
        self.assertEqual(current.value, winners[0][0])
        self.assertEqual(current.modify_index, winners[0][1])

    async def test_registered_source_check_is_read_only_against_real_consul(self) -> None:
        policy = RegisteredSourceTargetPolicy(
            [
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.CONSUL,
                    "127.0.0.1",
                    ["127.0.0.1/32"],
                    frozenset({self.port}),
                )
            ]
        )
        connection = SourceConnectionInput(
            source_id=None,
            expected_revision=None,
            provider=ConfigurationSourceProvider.CONSUL,
            endpoint=self.endpoint,
            location="dc1",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )
        reader = ConsulRuleSourceReader(policy)
        writer = ConsulRuleSourceWriter(policy)
        key = f"sentinel/acceptance/{uuid4().hex}/read-only-check.json"
        before = await writer.write(
            ConsulRuleSourceWrite(connection, key, None, b"stable-value")
        )

        checker = ConsulRegisteredSourceChecker(
            policy, PinnedAioHttpJsonClient().request
        )
        result = await checker.check(connection, "acceptance-operator")
        after = await reader.read(connection, key)

        self.assertTrue(result.reachable)
        self.assertEqual(
            result.capabilities,
            (SourceCheckCapability.READ, SourceCheckCapability.WATCH),
        )
        self.assertIsNone(result.reason)
        self.assertEqual(after.value, b"stable-value")
        self.assertEqual(after.modify_index, before.modify_index)

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + 45
        last_error: OSError | None = None
        while time.monotonic() < deadline:
            try:
                with urlopen(f"{self.endpoint}/v1/status/leader", timeout=1) as response:
                    if response.status == 200 and response.read().strip() != b'""':
                        return
            except OSError as error:
                last_error = error
            time.sleep(0.2)
        logs = subprocess.run(
            ["docker", "logs", self.container_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        ).stderr[-4000:]
        raise AssertionError(
            f"disposable Consul did not become ready; last_error={last_error!r}; "
            f"container_stderr={logs}"
        )

    def _remove_container(self) -> None:
        if getattr(self, "_started", False):
            subprocess.run(
                ["docker", "rm", "--force", self.container_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self._started = False
