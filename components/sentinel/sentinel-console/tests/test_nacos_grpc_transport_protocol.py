"""Wire-shape checks for the optional Nacos gRPC protobuf envelope."""

from __future__ import annotations

import asyncio
import ipaddress
import unittest
from unittest.mock import patch

try:
    from google.protobuf import descriptor_pb2, descriptor_pool
    from google.protobuf.message_factory import GetMessageClass
except ImportError:  # The protobuf package is intentionally an optional extra.
    descriptor_pb2 = None
    descriptor_pool = None
    GetMessageClass = None

from atlas_richie.sentinel_console.infrastructure.nacos_grpc_transport import (
    NacosGrpcTlsCredentials,
    NacosGrpcTransport,
    NacosGrpcUnavailable,
    _decode_payload,
    _payload,
    _payload_message_class,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    PinnedSourceTarget,
)


@unittest.skipIf(descriptor_pb2 is None, "install the nacos-grpc optional extra")
class NacosGrpcTransportProtocolTests(unittest.TestCase):
    def test_payload_metadata_body_and_header_field_numbers_match_sdk_wire_shape(self):
        payload_type = _payload_message_class(
            descriptor_pb2, descriptor_pool, GetMessageClass
        )
        descriptor = payload_type.DESCRIPTOR
        metadata = descriptor.fields_by_name["metadata"]
        body = descriptor.fields_by_name["body"]
        metadata_type = metadata.message_type
        self.assertEqual((metadata.number, body.number), (2, 3))
        self.assertEqual(metadata_type.fields_by_name["type"].number, 3)
        self.assertEqual(metadata_type.fields_by_name["headers"].number, 7)

    def test_round_trip_preserves_request_type_json_and_auth_header(self):
        payload_type = _payload_message_class(
            descriptor_pb2, descriptor_pool, GetMessageClass
        )
        expected_body = {"casMd5": "0123456789abcdef0123456789abcdef", "tenant": "租户"}
        payload = _payload(
            payload_type,
            "ConfigPublishRequest",
            expected_body,
            {"accessToken": "ephemeral-token"},
        )

        actual_type, actual_body = _decode_payload(
            payload_type.FromString(payload.SerializeToString())
        )

        self.assertEqual(actual_type, "ConfigPublishRequest")
        self.assertEqual(actual_body, expected_body)
        self.assertEqual(payload.metadata.headers["accessToken"], "ephemeral-token")


@unittest.skipIf(descriptor_pb2 is None, "install the nacos-grpc optional extra")
class NacosGrpcConnectionSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_registers_connection_before_sending_config_request(self):
        import grpc

        payload_type = _payload_message_class(
            descriptor_pb2, descriptor_pool, GetMessageClass
        )
        timeline: list[str] = []
        setup_bodies: list[dict[str, object]] = []
        setup_ack_responses: list[dict[str, object]] = []
        setup_received = asyncio.Event()
        stop_stream = asyncio.Event()

        class FakeStreamCall:
            def __init__(self, requests):
                self._requests = requests
                self._responses = asyncio.Queue()

            def __aiter__(self):
                return self._read()

            async def _read(self):
                async def consume_requests():
                    async for request in self._requests:
                        request_type, body = _decode_payload(request)
                        timeline.append(f"stream:{request_type}")
                        if request_type == "ConnectionSetupRequest":
                            setup_bodies.append(body)
                            setup_received.set()
                            await self._responses.put(
                                _payload(
                                    payload_type,
                                    "SetupAckRequest",
                                    {
                                        "requestId": "setup-ack-1",
                                        "abilityTable": {"mcp": True},
                                    },
                                    {},
                                )
                            )
                        elif request_type == "SetupAckResponse":
                            setup_ack_responses.append(body)
                    await stop_stream.wait()

                consumer = asyncio.create_task(consume_requests())
                try:
                    while not stop_stream.is_set():
                        response = await self._responses.get()
                        yield response
                finally:
                    stop_stream.set()
                    consumer.cancel()
                    await asyncio.gather(consumer, return_exceptions=True)

            def cancel(self):
                stop_stream.set()

        class FakeChannel:
            def channel_ready(self):
                async def ready():
                    return None

                return ready()

            def unary_unary(self, path, **_kwargs):
                self.unary_path = path

                async def request(envelope, timeout):
                    request_type, body = _decode_payload(envelope)
                    timeline.append(f"unary:{request_type}")
                    self.last_unary_body = body
                    if request_type == "ServerCheckRequest":
                        return _payload(
                            payload_type,
                            "ServerCheckResponse",
                            {
                                "resultCode": 200,
                                "connectionId": "connection-1",
                                "supportAbilityNegotiation": True,
                            },
                            {},
                        )
                    return _payload(
                        payload_type,
                        "ConfigPublishResponse",
                        {"resultCode": 200},
                        {},
                    )

                return request

            def stream_stream(self, path, **_kwargs):
                self.stream_path = path
                return lambda requests: FakeStreamCall(requests)

            async def close(self):
                stop_stream.set()

        channel = FakeChannel()
        target = PinnedSourceTarget(
            hostname="nacos.example.test",
            port=9848,
            addresses=(ipaddress.ip_address("192.0.2.17"),),
            secure=True,
        )
        tls_credentials = NacosGrpcTlsCredentials(
            root_certificates=b"private-ca-bundle",
            private_key=b"client-private-key",
            certificate_chain=b"client-certificate-chain",
        )
        grpc_credentials = object()
        with (
            patch.object(grpc.aio, "secure_channel", return_value=channel),
            patch.object(
                grpc, "ssl_channel_credentials", return_value=grpc_credentials
            ) as create_credentials,
        ):
            response_type, response_body = await NacosGrpcTransport(
                tls_credentials
            ).request(
                target,
                request_type="ConfigPublishRequest",
                body={"tenant": "tenant-a", "casMd5": "old-md5"},
                headers={"accessToken": "ephemeral-token"},
            )

        self.assertEqual(response_type, "ConfigPublishResponse")
        self.assertEqual(response_body["resultCode"], 200)
        create_credentials.assert_called_once_with(
            root_certificates=b"private-ca-bundle",
            private_key=b"client-private-key",
            certificate_chain=b"client-certificate-chain",
        )
        self.assertEqual(
            timeline,
            [
                "unary:ServerCheckRequest",
                "stream:ConnectionSetupRequest",
                "stream:SetupAckResponse",
                "unary:ConfigPublishRequest",
            ],
        )
        self.assertEqual(channel.stream_path, "/BiRequestStream/requestBiStream")
        self.assertEqual(channel.unary_path, "/Request/request")
        self.assertEqual(channel.last_unary_body["casMd5"], "old-md5")
        self.assertEqual(setup_bodies[0]["tenant"], "tenant-a")
        self.assertEqual(setup_bodies[0]["clientVersion"], "Nacos-Python-Client:v3.2.0")
        self.assertEqual(setup_bodies[0]["labels"], {"source": "sdk"})
        self.assertEqual(setup_bodies[0]["abilityTable"], {"mcp": True, "agent": True})
        self.assertEqual(
            setup_ack_responses[0],
            {
                "resultCode": 200,
                "errorCode": 0,
                "message": "",
                "requestId": "setup-ack-1",
            },
        )

    async def test_client_identity_requires_certificate_and_private_key_pair(self):
        with self.assertRaisesRegex(ValueError, "configured together"):
            NacosGrpcTlsCredentials(private_key=b"key")

        with self.assertRaisesRegex(ValueError, "configured together"):
            NacosGrpcTlsCredentials(certificate_chain=b"certificate")

    async def test_tls_material_never_falls_back_to_plaintext_target(self):
        import grpc

        target = PinnedSourceTarget(
            hostname="nacos.example.test",
            port=9848,
            addresses=(ipaddress.ip_address("192.0.2.17"),),
            secure=False,
        )
        with (
            patch.object(grpc.aio, "insecure_channel") as create_insecure_channel,
            self.assertRaises(NacosGrpcUnavailable),
        ):
            await NacosGrpcTransport(
                NacosGrpcTlsCredentials(root_certificates=b"private-ca")
            ).request(
                target,
                request_type="ConfigPublishRequest",
                body={"tenant": "tenant-a"},
                headers={},
            )

        create_insecure_channel.assert_not_called()

    async def test_setup_registration_failure_prevents_config_dispatch(self):
        import grpc
        from atlas_richie.sentinel_console.infrastructure import nacos_grpc_transport

        payload_type = _payload_message_class(
            descriptor_pb2, descriptor_pool, GetMessageClass
        )
        unary_requests: list[str] = []

        class ClosedStream:
            def __init__(self, _requests):
                pass

            def __aiter__(self):
                async def closed():
                    if False:
                        yield None

                return closed()

            def cancel(self):
                return None

        class FakeChannel:
            def channel_ready(self):
                async def ready():
                    return None

                return ready()

            def unary_unary(self, _path, **_kwargs):
                async def request(envelope, timeout):
                    request_type, _ = _decode_payload(envelope)
                    unary_requests.append(request_type)
                    return _payload(
                        payload_type,
                        "ServerCheckResponse",
                        {
                            "resultCode": 200,
                            "connectionId": "connection-1",
                            "supportAbilityNegotiation": True,
                        },
                        {},
                    )

                return request

            def stream_stream(self, _path, **_kwargs):
                return lambda requests: ClosedStream(requests)

            async def close(self):
                return None

        target = PinnedSourceTarget(
            hostname="nacos.example.test",
            port=9848,
            addresses=(ipaddress.ip_address("192.0.2.17"),),
            secure=True,
        )
        with (
            patch.object(grpc.aio, "secure_channel", return_value=FakeChannel()),
            patch.object(nacos_grpc_transport, "_REQUEST_TIMEOUT_SECONDS", 0.01),
            self.assertRaises(NacosGrpcUnavailable),
        ):
            await NacosGrpcTransport().request(
                target,
                request_type="ConfigPublishRequest",
                body={"tenant": "tenant-a"},
                headers={},
            )

        self.assertEqual(unary_requests, ["ServerCheckRequest"])


if __name__ == "__main__":
    unittest.main()
