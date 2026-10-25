"""Controlled-transport tests for exact Consul KV reconciliation reads."""

from __future__ import annotations

import base64
import json
import unittest
from typing import cast

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_reader import (
    ConsulRuleSourceReader,
    ConsulRuleSourceReadRejected,
    ConsulRuleSourceReadUnavailable,
    ConsulRuleSourceSnapshot,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)

_KEY = "sentinel/apps/orders/rules"
_RULES = b'[{"resource":"POST /api/orders","count":25}]'


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


class ConsulRuleSourceReaderTests(unittest.IsolatedAsyncioTestCase):
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

    def _response(self, *, key: str = _KEY, value: bytes = _RULES):
        return (
            200,
            json.dumps(
                [
                    {
                        "Key": key,
                        "ModifyIndex": 42,
                        "Value": base64.b64encode(value).decode("ascii"),
                    }
                ]
            ).encode(),
            {"Content-Type": "application/json"},
        )

    async def test_returns_exact_key_bytes_and_opaque_revision(self) -> None:
        client = ScriptedPinnedHttpClient(self._response())
        reader = ConsulRuleSourceReader(self.policy, client)

        snapshot = await reader.read(self._connection(), _KEY)

        self.assertTrue(snapshot.exists)
        self.assertEqual(snapshot.value, _RULES)
        self.assertEqual(snapshot.modify_index, "42")
        self.assertNotIn(_RULES.decode(), repr(snapshot))
        request = client.requests[0]
        self.assertEqual(request["method"], "GET")
        self.assertEqual(request["path"], "/v1/kv/sentinel/apps/orders/rules")
        self.assertEqual(request["params"], {"dc": "dc-east", "consistent": "true"})
        self.assertEqual(request["headers"]["X-Consul-Token"], "[REDACTED_SECRET]")

    async def test_absent_key_is_distinct_from_empty_or_invalid_response(self) -> None:
        reader = ConsulRuleSourceReader(
            self.policy, ScriptedPinnedHttpClient((404, b"", {}))
        )

        snapshot = await reader.read(self._connection(), _KEY)

        self.assertFalse(snapshot.exists)
        self.assertIsNone(snapshot.value)
        self.assertIsNone(snapshot.modify_index)

        empty_value_reader = ConsulRuleSourceReader(
            self.policy, ScriptedPinnedHttpClient(self._response(value=b""))
        )
        empty_value = await empty_value_reader.read(self._connection(), _KEY)
        self.assertTrue(empty_value.exists)
        self.assertEqual(empty_value.value, b"")
        self.assertEqual(empty_value.modify_index, "42")

    def test_snapshot_enforces_value_revision_and_byte_invariants(self) -> None:
        for value, revision in (
            (b"payload", None),
            (None, "42"),
            ("payload", "42"),
            (b"payload", "0"),
            (b"payload", "01x"),
        ):
            with (
                self.subTest(value=value, revision=revision),
                self.assertRaises(ValueError),
            ):
                ConsulRuleSourceSnapshot(_KEY, cast(bytes | None, value), revision)

    async def test_wrong_key_malformed_metadata_and_network_failure_fail_closed(self):
        malformed = (
            200,
            json.dumps([{"Key": _KEY, "ModifyIndex": "42", "Value": ""}]).encode(),
            {},
        )
        for response in (self._response(key="another/key"), malformed, TimeoutError()):
            with self.subTest(response=response):
                reader = ConsulRuleSourceReader(
                    self.policy, ScriptedPinnedHttpClient(response)
                )
                with self.assertRaises(ConsulRuleSourceReadUnavailable):
                    await reader.read(self._connection(), _KEY)

    async def test_unexpected_transport_programming_error_is_not_reclassified(
        self,
    ) -> None:
        reader = ConsulRuleSourceReader(
            self.policy, ScriptedPinnedHttpClient(RuntimeError("bug in adapter"))
        )

        with self.assertRaisesRegex(RuntimeError, "bug in adapter"):
            await reader.read(self._connection(), _KEY)

    async def test_acl_rejection_and_unapproved_target_are_distinct(self) -> None:
        denied_reader = ConsulRuleSourceReader(
            self.policy, ScriptedPinnedHttpClient((403, b"", {}))
        )
        with self.assertRaises(ConsulRuleSourceReadRejected):
            await denied_reader.read(self._connection(), _KEY)

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
        client = ScriptedPinnedHttpClient()
        target_reader = ConsulRuleSourceReader(other_policy, client)
        with self.assertRaises(ConsulRuleSourceReadUnavailable):
            await target_reader.read(self._connection(), _KEY)
        self.assertEqual(client.requests, [])


if __name__ == "__main__":
    unittest.main()
