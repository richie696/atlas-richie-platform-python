"""Controlled-transport tests for Consul's single-key CAS publication boundary."""

from __future__ import annotations

import base64
import json
import unittest

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_writer import (
    ConsulRuleSourceConflict,
    ConsulRuleSourceOutcomeUnknown,
    ConsulRuleSourceUnavailable,
    ConsulRuleSourceWrite,
    ConsulRuleSourceWriter,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)


class ScriptedPinnedHttpClient(PinnedAioHttpJsonClient):
    def __init__(self, *responses: tuple[int, bytes, dict[str, str]]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    async def request_raw(self, **request: object) -> tuple[int, bytes, dict[str, str]]:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ConsulRuleSourceWriterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.policy = RegisteredSourceTargetPolicy(
            [
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.CONSUL,
                    "127.0.0.1",
                    ["127.0.0.1/32"],
                    frozenset({8500}),
                )
            ]
        )
        self.value = b'[{"resource":"POST /api/orders","count":25}]'

    def _connection(self) -> SourceConnectionInput:
        return SourceConnectionInput(
            source_id="source-1",
            expected_revision="registry-revision-1",
            provider=ConfigurationSourceProvider.CONSUL,
            endpoint="https://127.0.0.1:8500/consul",
            location="dc-east",
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            acl_token="[REDACTED_SECRET]",
        )

    def _write(self, expected_index: str | None) -> ConsulRuleSourceWrite:
        return ConsulRuleSourceWrite(
            connection=self._connection(),
            key="sentinel/apps/orders/rules",
            expected_modify_index=expected_index,
            value=self.value,
        )

    def _metadata_response(self, value: bytes | None = None) -> tuple[int, bytes, dict[str, str]]:
        payload = json.dumps(
            [
                {
                    "Key": "sentinel/apps/orders/rules",
                    "ModifyIndex": 42,
                    "Value": base64.b64encode(value or self.value).decode("ascii"),
                }
            ]
        ).encode()
        return 200, payload, {"Content-Type": "application/json"}

    async def test_create_uses_cas_zero_and_reads_exact_value_back(self) -> None:
        client = ScriptedPinnedHttpClient(
            (200, b"true", {}),
            self._metadata_response(),
        )
        writer = ConsulRuleSourceWriter(self.policy, client)

        receipt = await writer.write(self._write(None))

        self.assertEqual(receipt.modify_index, "42")
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(client.requests[0]["method"], "PUT")
        self.assertEqual(
            client.requests[0]["path"],
            "/v1/kv/sentinel/apps/orders/rules",
        )
        self.assertEqual(client.requests[0]["params"], {"dc": "dc-east", "cas": "0"})
        self.assertEqual(client.requests[0]["body"], self.value)
        self.assertEqual(
            client.requests[0]["headers"]["X-Consul-Token"], "[REDACTED_SECRET]"
        )
        self.assertEqual(client.requests[1]["method"], "GET")

    async def test_stale_modify_index_is_conflict_and_is_never_retried(self) -> None:
        client = ScriptedPinnedHttpClient((200, b"false", {}))
        writer = ConsulRuleSourceWriter(self.policy, client)

        with self.assertRaises(ConsulRuleSourceConflict):
            await writer.write(self._write("41"))

        self.assertEqual(len(client.requests), 1)
        self.assertEqual(client.requests[0]["params"], {"dc": "dc-east", "cas": "41"})

    async def test_acknowledged_write_with_mismatched_readback_is_unknown(self) -> None:
        client = ScriptedPinnedHttpClient(
            (200, b"true", {}),
            self._metadata_response(b"another writer replaced the candidate"),
        )
        writer = ConsulRuleSourceWriter(self.policy, client)

        with self.assertRaises(ConsulRuleSourceOutcomeUnknown):
            await writer.write(self._write("41"))

        self.assertEqual(len(client.requests), 2)

    async def test_request_failure_after_dispatch_is_unknown_without_retry(self) -> None:
        client = ScriptedPinnedHttpClient(TimeoutError("simulated timeout"))
        writer = ConsulRuleSourceWriter(self.policy, client)

        with self.assertRaises(ConsulRuleSourceOutcomeUnknown):
            await writer.write(self._write("41"))

        self.assertEqual(len(client.requests), 1)

    async def test_unexpected_transport_programming_error_is_not_reclassified(self) -> None:
        client = ScriptedPinnedHttpClient(RuntimeError("bug in adapter"))
        writer = ConsulRuleSourceWriter(self.policy, client)

        with self.assertRaisesRegex(RuntimeError, "bug in adapter"):
            await writer.write(self._write("41"))

    async def test_unapproved_target_is_rejected_before_any_http_request(self) -> None:
        client = ScriptedPinnedHttpClient()
        other_policy = RegisteredSourceTargetPolicy(
            [
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.CONSUL,
                    "192.0.2.20",
                    ["192.0.2.20/32"],
                    frozenset({8500}),
                )
            ]
        )
        writer = ConsulRuleSourceWriter(other_policy, client)

        with self.assertRaises(ConsulRuleSourceUnavailable):
            await writer.write(self._write("41"))

        self.assertEqual(client.requests, [])

    def test_request_rejects_invalid_provider_key_and_revision(self) -> None:
        connection = self._connection()
        self.assertNotIn("[REDACTED_SECRET]", repr(self._write("41")))
        with self.assertRaisesRegex(ValueError, "Consul connection"):
            ConsulRuleSourceWrite(
                connection=SourceConnectionInput(
                    source_id=None,
                    expected_revision=None,
                    provider=ConfigurationSourceProvider.NACOS,
                    endpoint="http://127.0.0.1:8500",
                    location="",
                    authentication_mode=SourceCheckAuthenticationMode.NONE,
                ),
                key="rules",
                expected_modify_index=None,
                value=self.value,
            )
        for key in ("../escape", "/leading", "trailing/", "double//slash"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "key"):
                ConsulRuleSourceWrite(connection, key, None, self.value)
        for index in ("0", "-1", "1.5", str(1 << 64)):
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "ModifyIndex"):
                ConsulRuleSourceWrite(connection, "rules", index, self.value)


if __name__ == "__main__":
    unittest.main()
