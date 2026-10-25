"""Opt-in ACL acceptance against a uniquely named disposable Consul agent."""

from __future__ import annotations

import asyncio
import os
import unittest

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
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_writer import (
    ConsulRuleSourceConflict,
    ConsulRuleSourceWrite,
    ConsulRuleSourceWriter,
    ConsulRuleSourceWriteRejected,
)
from consul_acl_test_support import DisposableConsulAclServer

_RUN_ACCEPTANCE = os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACL_ACCEPTANCE") == "1"
_KEY = "sentinel/acceptance/rules.json"
_RULE_BYTES = b'[{"resource":"GET /acceptance","count":7}]'


@unittest.skipUnless(
    _RUN_ACCEPTANCE,
    "set SENTINEL_CONSOLE_RUN_CONSUL_ACL_ACCEPTANCE=1 to start disposable Consul",
)
class ConsulAclAuthAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    """Exercise scoped Consul ACL reads, writes, and conditional publication."""

    async def asyncSetUp(self) -> None:
        self._consul = DisposableConsulAclServer(_KEY)
        await self._consul.start()
        try:
            self._consul.write_management_value(_KEY, _RULE_BYTES)
            self._management_token = self._consul.management_token
            self._application_token = self._consul.application_token
            self._endpoint = self._consul.endpoint
            self._observed_requests = self._consul.observed_requests
            target_policy = self._consul.registered_target_policy()
            http_client = self._consul.http_client()
            self._reader = ConsulRuleSourceReader(target_policy, http_client)
            self._writer = ConsulRuleSourceWriter(target_policy, http_client)
            native_target_policy = self._consul.registered_native_target_policy()
            self._native_reader = ConsulRuleSourceReader(
                native_target_policy, http_client
            )
            self._native_writer = ConsulRuleSourceWriter(
                native_target_policy, http_client
            )
        except BaseException:
            await self._consul.close()
            raise

    async def asyncTearDown(self) -> None:
        await self._consul.close()

    async def test_acl_token_reads_exact_key_and_missing_or_bad_token_is_denied(
        self,
    ) -> None:
        accepted = await self._reader.read(
            self._connection(self._application_token), _KEY
        )
        self.assertTrue(accepted.exists)
        self.assertEqual(accepted.value, _RULE_BYTES)
        self.assertIsNotNone(accepted.modify_index)
        self.assertNotIn(self._management_token, repr(accepted))
        self.assertEqual(self._observed_requests[0][1], self._application_token)
        self.assertNotIn(self._application_token, self._observed_requests[0][0])

        with self.assertRaises(ConsulRuleSourceReadRejected):
            await self._reader.read(
                self._connection(self._application_token),
                "sentinel/acceptance/outside-policy.json",
            )

        for token in (None, "invalid-consul-acl-token"):
            with (
                self.subTest(has_token=token is not None),
                self.assertRaises(ConsulRuleSourceReadRejected),
            ):
                await self._reader.read(self._connection(token), _KEY)

    async def test_native_consul_https_listener_accepts_verified_acl_requests(
        self,
    ) -> None:
        """Exercise production reader/writer directly against Consul-owned TLS."""
        connection = self._connection(
            self._application_token,
            endpoint=self._consul.native_endpoint,
        )
        baseline = await self._native_reader.read(connection, _KEY)
        candidate = b'[{"resource":"PUT /native-https","count":13}]'
        receipt = await self._native_writer.write(
            ConsulRuleSourceWrite(
                connection=connection,
                key=_KEY,
                expected_modify_index=baseline.modify_index,
                value=candidate,
            )
        )
        verified = await self._native_reader.read(connection, _KEY)

        self.assertEqual(verified.value, candidate)
        self.assertEqual(verified.modify_index, receipt.modify_index)
        self.assertTrue(self._consul.native_endpoint.startswith("https://127.0.0.1:"))

    async def test_acl_token_writes_with_cas_and_verifies_exact_readback(self) -> None:
        baseline = await self._reader.read(
            self._connection(self._application_token), _KEY
        )
        candidate = b'[{"resource":"POST /orders","count":19}]'
        receipt = await self._writer.write(
            ConsulRuleSourceWrite(
                connection=self._connection(self._application_token),
                key=_KEY,
                expected_modify_index=baseline.modify_index,
                value=candidate,
            )
        )
        verified = await self._reader.read(
            self._connection(self._application_token), _KEY
        )

        self.assertEqual(verified.value, candidate)
        self.assertEqual(verified.modify_index, receipt.modify_index)
        self.assertGreater(int(receipt.modify_index), int(baseline.modify_index or 0))
        writer_requests = self._observed_requests[1:3]
        self.assertEqual(len(writer_requests), 2)
        self.assertTrue(writer_requests[0][0].startswith(f"/v1/kv/{_KEY}?"))
        self.assertIn("cas=" + str(baseline.modify_index), writer_requests[0][0])
        self.assertTrue(writer_requests[1][0].startswith(f"/v1/kv/{_KEY}?"))
        self.assertTrue(
            all(token == self._application_token for _, token in writer_requests)
        )
        self.assertTrue(
            all(self._application_token not in path for path, _ in writer_requests)
        )

    async def test_acl_cas_conflict_preserves_an_external_writer_value(self) -> None:
        baseline = await self._reader.read(
            self._connection(self._application_token), _KEY
        )
        external_value = b'[{"resource":"POST /external-writer","count":31}]'
        candidate = b'[{"resource":"POST /console-candidate","count":23}]'
        await asyncio.to_thread(
            self._consul.write_management_value, _KEY, external_value
        )

        with self.assertRaises(ConsulRuleSourceConflict):
            await self._writer.write(
                ConsulRuleSourceWrite(
                    connection=self._connection(self._application_token),
                    key=_KEY,
                    expected_modify_index=baseline.modify_index,
                    value=candidate,
                )
            )

        verified = await self._reader.read(
            self._connection(self._application_token), _KEY
        )
        self.assertEqual(verified.value, external_value)
        self.assertGreater(
            int(verified.modify_index or 0), int(baseline.modify_index or 0)
        )
        attempted_write = self._observed_requests[1]
        self.assertTrue(attempted_write[0].startswith(f"/v1/kv/{_KEY}?"))
        self.assertIn("cas=" + str(baseline.modify_index), attempted_write[0])
        self.assertEqual(attempted_write[1], self._application_token)
        self.assertNotIn(self._application_token, attempted_write[0])

    async def test_acl_denies_missing_and_invalid_tokens_on_write(self) -> None:
        baseline = await self._reader.read(
            self._connection(self._application_token), _KEY
        )
        denied_candidate = b'[{"resource":"POST /must-not-write","count":99}]'

        for token in (None, "invalid-consul-acl-token"):
            with (
                self.subTest(has_token=token is not None),
                self.assertRaises(ConsulRuleSourceWriteRejected),
            ):
                await self._writer.write(
                    ConsulRuleSourceWrite(
                        connection=self._connection(token),
                        key=_KEY,
                        expected_modify_index=baseline.modify_index,
                        value=denied_candidate,
                    )
                )

        with self.assertRaises(ConsulRuleSourceWriteRejected):
            await self._writer.write(
                ConsulRuleSourceWrite(
                    connection=self._connection(self._application_token),
                    key="sentinel/acceptance/outside-policy.json",
                    expected_modify_index=None,
                    value=denied_candidate,
                )
            )

        after_denials = await self._reader.read(
            self._connection(self._application_token), _KEY
        )
        self.assertEqual(after_denials.value, baseline.value)
        self.assertEqual(after_denials.modify_index, baseline.modify_index)
        denied_writes = self._observed_requests[1:4]
        self.assertEqual(len(denied_writes), 3)
        self.assertEqual(denied_writes[0][1], None)
        self.assertEqual(denied_writes[1][1], "invalid-consul-acl-token")
        self.assertEqual(denied_writes[2][1], self._application_token)

    def _connection(
        self, token: str | None, *, endpoint: str | None = None
    ) -> SourceConnectionInput:
        return SourceConnectionInput(
            source_id="disposable-consul-source",
            expected_revision="acceptance-revision-1",
            provider=ConfigurationSourceProvider.CONSUL,
            endpoint=endpoint or self._endpoint,
            location="dc1",
            authentication_mode=(
                SourceCheckAuthenticationMode.DIRECT
                if token is not None
                else SourceCheckAuthenticationMode.NONE
            ),
            acl_token=token,
        )


if __name__ == "__main__":
    unittest.main()
