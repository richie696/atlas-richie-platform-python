"""Focused contracts for Nacos gRPC CAS and exact HTTP read-back."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import unittest

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.nacos_grpc_transport import (
    NacosGrpcConflict,
    NacosGrpcOutcomeUnknown,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_reader import (
    NacosRuleSourceSnapshot,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_writer import (
    NacosRuleSourceConflict,
    NacosRuleSourceOutcomeUnknown,
    NacosRuleSourceUnavailable,
    NacosRuleSourceWrite,
    NacosRuleSourceWriter,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)


def _md5(value: bytes) -> str:
    return hashlib.md5(value, usedforsecurity=False).hexdigest()


class _Resolver:
    async def __call__(self, hostname, port):
        return (
            (
                socket.AF_INET,
                1,
                6,
                "",
                ("192.0.2.17", port),
            ),
        )


class _Reader:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []
        self.error = None

    async def read(self, connection, target):
        self.calls.append((connection, target))
        if self.error is not None:
            raise self.error
        return self.snapshot


class _GrpcClient:
    def __init__(self):
        self.calls = []
        self.error = None
        self.response = ("ConfigPublishResponse", {"resultCode": 200, "errorCode": 0})

    async def request(self, target, *, request_type, body, headers):
        self.calls.append((target, request_type, body, headers))
        if self.error is not None:
            raise self.error
        return self.response


class _HttpClient:
    def __init__(self):
        self.calls = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        return 200, {"accessToken": "ephemeral-access-token"}, {}


class NacosRuleSourceWriterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.connection = SourceConnectionInput(
            source_id="source-1",
            expected_revision="source-revision-1",
            provider=ConfigurationSourceProvider.NACOS,
            endpoint="https://nacos.example.test:8848",
            location="tenant-a",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )
        self.target = NacosRulePublicationTarget(
            binding_id="binding-1",
            source_id="source-1",
            namespace="tenant-a",
            group="SENTINEL_GROUP",
            data_id="sentinel-rules.json",
        )
        self.policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.NACOS,
                    "nacos.example.test",
                    ("192.0.2.0/24",),
                    frozenset({8848, 9848}),
                ),
            ),
            resolver=_Resolver(),
        )
        self.reader = _Reader(
            NacosRuleSourceSnapshot(
                namespace="tenant-a",
                group="SENTINEL_GROUP",
                data_id="sentinel-rules.json",
                value=b"new-rules",
                md5=_md5(b"new-rules"),
            )
        )
        self.grpc = _GrpcClient()
        self.http = _HttpClient()
        self.writer = NacosRuleSourceWriter(
            self.policy,
            self.reader,
            http_client=self.http,
            grpc_client=self.grpc,
            clock_ns=lambda: 1_800_000_000_000_000_000,
            request_id_factory=lambda: "request-1",
        )
        self.command = NacosRuleSourceWrite(
            connection=self.connection,
            target=self.target,
            expected_md5=_md5(b"old-rules"),
            value=b"new-rules",
        )

    async def test_uses_provider_md5_and_pinned_grpc_port_then_reads_back_exact_bytes(self):
        receipt = await self.writer.write(self.command)

        self.assertEqual(receipt.md5, _md5(b"new-rules"))
        self.assertEqual(len(self.grpc.calls), 1)
        target, request_type, body, headers = self.grpc.calls[0]
        self.assertEqual(target.hostname, "nacos.example.test")
        self.assertEqual(target.port, 9848)
        self.assertEqual(target.addresses, (ipaddress.ip_address("192.0.2.17"),))
        self.assertTrue(target.secure)
        self.assertEqual(request_type, "ConfigPublishRequest")
        self.assertEqual(body["tenant"], "tenant-a")
        self.assertEqual(body["group"], "SENTINEL_GROUP")
        self.assertEqual(body["dataId"], "sentinel-rules.json")
        self.assertEqual(body["casMd5"], _md5(b"old-rules"))
        self.assertEqual(body["content"], "new-rules")
        self.assertNotIn("accessToken", headers)
        self.assertEqual(len(self.reader.calls), 1)

    async def test_rejects_unapproved_grpc_port_before_dispatch(self):
        policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.NACOS,
                    "nacos.example.test",
                    ("192.0.2.0/24",),
                    frozenset({8848}),
                ),
            ),
            resolver=_Resolver(),
        )
        writer = NacosRuleSourceWriter(
            policy, self.reader, grpc_client=self.grpc
        )

        with self.assertRaises(NacosRuleSourceUnavailable):
            await writer.write(self.command)

        self.assertEqual(self.grpc.calls, [])
        self.assertEqual(self.reader.calls, [])

    async def test_direct_credentials_are_exchanged_over_pinned_http_and_sent_as_grpc_header(self):
        connection = SourceConnectionInput(
            source_id="source-1",
            expected_revision="source-revision-1",
            provider=ConfigurationSourceProvider.NACOS,
            endpoint="https://nacos.example.test:8848",
            location="tenant-a",
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            username="console-user",
            password="not-logged-or-repr",
        )
        command = NacosRuleSourceWrite(
            connection=connection,
            target=self.target,
            expected_md5=_md5(b"old-rules"),
            value=b"new-rules",
        )

        await self.writer.write(command)

        self.assertEqual(len(self.http.calls), 1)
        self.assertEqual(self.http.calls[0]["path"], "/v3/auth/user/login")
        self.assertEqual(self.http.calls[0]["target"].addresses, self.grpc.calls[0][0].addresses)
        self.assertEqual(
            self.grpc.calls[0][3]["accessToken"], "ephemeral-access-token"
        )
        self.assertNotIn("not-logged-or-repr", repr(connection))
        self.assertNotIn("not-logged-or-repr", repr(command))

    async def test_rejects_unverified_create_without_sending_rpc(self):
        with self.assertRaises(ValueError):
            NacosRuleSourceWrite(
                connection=self.connection,
                target=self.target,
                expected_md5="",
                value=b"new-rules",
            )
        self.assertEqual(self.grpc.calls, [])

    async def test_maps_provider_cas_conflict_without_readback(self):
        self.grpc.response = (
            "ErrorResponse",
            {"resultCode": 500, "errorCode": 20_005},
        )

        with self.assertRaises(NacosRuleSourceConflict):
            await self.writer.write(self.command)

        self.assertEqual(len(self.reader.calls), 0)

    async def test_maps_nacos_32_admin_cas_failure_envelope_to_conflict(self):
        self.grpc.response = (
            "ConfigPublishResponse",
            {
                "resultCode": 500,
                "errorCode": 500,
                "message": "Cas publish fail, server md5 may have changed.",
                "success": False,
            },
        )

        with self.assertRaises(NacosRuleSourceConflict):
            await self.writer.write(self.command)

        self.assertEqual(len(self.grpc.calls), 1)
        self.assertEqual(self.reader.calls, [])

    async def test_does_not_map_unrelated_nacos_server_error_to_conflict(self):
        self.grpc.response = (
            "ConfigPublishResponse",
            {
                "resultCode": 500,
                "errorCode": 500,
                "message": "Internal server error.",
                "success": False,
            },
        )

        with self.assertRaises(NacosRuleSourceOutcomeUnknown):
            await self.writer.write(self.command)

        self.assertEqual(len(self.reader.calls), 0)

    async def test_dispatch_unknown_is_not_retried_or_read_as_success(self):
        self.grpc.error = NacosGrpcOutcomeUnknown

        with self.assertRaises(NacosRuleSourceOutcomeUnknown):
            await self.writer.write(self.command)

        self.assertEqual(len(self.grpc.calls), 1)
        self.assertEqual(self.reader.calls, [])

    async def test_success_ack_with_mismatched_readback_remains_unknown(self):
        self.reader.snapshot = NacosRuleSourceSnapshot(
            namespace="tenant-a",
            group="SENTINEL_GROUP",
            data_id="sentinel-rules.json",
            value=b"old-rules",
            md5=_md5(b"old-rules"),
        )

        with self.assertRaises(NacosRuleSourceOutcomeUnknown):
            await self.writer.write(self.command)

        self.assertEqual(len(self.grpc.calls), 1)
        self.assertEqual(len(self.reader.calls), 1)

    async def test_transport_conflict_is_not_retried(self):
        self.grpc.error = NacosGrpcConflict

        with self.assertRaises(NacosRuleSourceConflict):
            await self.writer.write(self.command)

        self.assertEqual(len(self.grpc.calls), 1)


if __name__ == "__main__":
    unittest.main()
