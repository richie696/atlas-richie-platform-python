"""Loopback gRPC TLS acceptance for deployment-owned Nacos credentials."""

from __future__ import annotations

import asyncio
import ipaddress
import unittest
from datetime import UTC, datetime, timedelta

try:
    import grpc
    from google.protobuf import descriptor_pb2, descriptor_pool
    from google.protobuf.message_factory import GetMessageClass
except ImportError:  # The Nacos gRPC transport is an optional Console extra.
    grpc = None
    descriptor_pb2 = None
    descriptor_pool = None
    GetMessageClass = None

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
except ImportError:  # pragma: no cover - the Console runtime depends on cryptography.
    x509 = None
    hashes = None
    serialization = None
    ec = None
    ExtendedKeyUsageOID = None
    NameOID = None

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


@unittest.skipIf(
    grpc is None or descriptor_pb2 is None,
    "install the nacos-grpc optional extra",
)
class NacosGrpcTlsAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_ca_and_mutual_tls_client_identity_complete_real_handshake(
        self,
    ):
        server_ca_key, server_ca_certificate = _create_ca("Nacos test CA")
        client_ca_key, client_ca_certificate = _create_ca("Client test CA")
        server_key, server_certificate = _create_leaf(
            server_ca_key,
            server_ca_certificate,
            "nacos.example.test",
            ExtendedKeyUsageOID.SERVER_AUTH,
        )
        client_key, client_certificate = _create_leaf(
            client_ca_key,
            client_ca_certificate,
            "sentinel-console.test",
            ExtendedKeyUsageOID.CLIENT_AUTH,
        )
        server_ca_pem = _certificate_pem(server_ca_certificate)
        server_key_pem = _private_key_pem(server_key)
        server_certificate_pem = _certificate_pem(server_certificate)
        client_ca_pem = _certificate_pem(client_ca_certificate)
        client_key_pem = _private_key_pem(client_key)
        client_certificate_pem = _certificate_pem(client_certificate)
        payload_type = _payload_message_class(
            descriptor_pb2, descriptor_pool, GetMessageClass
        )
        received_types: list[str] = []

        async def unary_request(request, _context):
            request_type, request_body = _decode_payload(request)
            received_types.append(request_type)
            if request_type == "ServerCheckRequest":
                return _payload(
                    payload_type,
                    "ServerCheckResponse",
                    {
                        "resultCode": 200,
                        "connectionId": "loopback-tls-connection",
                        "supportAbilityNegotiation": False,
                    },
                    {},
                )
            if request_type == "ConfigPublishRequest":
                return _payload(
                    payload_type,
                    "ConfigPublishResponse",
                    {"resultCode": 200, "receivedTenant": request_body["tenant"]},
                    {},
                )
            raise AssertionError(f"unexpected Nacos request type: {request_type}")

        async def bi_request_stream(requests, _context):
            async for request in requests:
                request_type, _ = _decode_payload(request)
                received_types.append(request_type)
            await asyncio.Event().wait()

        server = grpc.aio.server()
        server.add_generic_rpc_handlers(
            (
                grpc.method_handlers_generic_handler(
                    "Request",
                    {
                        "request": grpc.unary_unary_rpc_method_handler(
                            unary_request,
                            request_deserializer=payload_type.FromString,
                            response_serializer=lambda message: (
                                message.SerializeToString()
                            ),
                        )
                    },
                ),
                grpc.method_handlers_generic_handler(
                    "BiRequestStream",
                    {
                        "requestBiStream": grpc.stream_stream_rpc_method_handler(
                            bi_request_stream,
                            request_deserializer=payload_type.FromString,
                            response_serializer=lambda message: (
                                message.SerializeToString()
                            ),
                        )
                    },
                ),
            )
        )
        port = server.add_secure_port(
            "127.0.0.1:0",
            grpc.ssl_server_credentials(
                ((server_key_pem, server_certificate_pem),),
                root_certificates=client_ca_pem,
                require_client_auth=True,
            ),
        )
        await server.start()
        try:
            target = PinnedSourceTarget(
                hostname="nacos.example.test",
                port=port,
                addresses=(ipaddress.ip_address("127.0.0.1"),),
                secure=True,
            )
            transport = NacosGrpcTransport(
                NacosGrpcTlsCredentials(
                    root_certificates=server_ca_pem,
                    private_key=client_key_pem,
                    certificate_chain=client_certificate_pem,
                )
            )
            response_type, response_body = await transport.request(
                target,
                request_type="ConfigPublishRequest",
                body={"tenant": "loopback-test"},
                headers={},
            )

            self.assertEqual(response_type, "ConfigPublishResponse")
            self.assertEqual(response_body["receivedTenant"], "loopback-test")
            self.assertEqual(
                received_types,
                [
                    "ServerCheckRequest",
                    "ConnectionSetupRequest",
                    "ConfigPublishRequest",
                ],
            )

            with self.assertRaises(NacosGrpcUnavailable):
                await NacosGrpcTransport(
                    NacosGrpcTlsCredentials(
                        root_certificates=client_ca_pem,
                        private_key=client_key_pem,
                        certificate_chain=client_certificate_pem,
                    )
                ).request(
                    target,
                    request_type="ConfigPublishRequest",
                    body={"tenant": "must-not-reach-server"},
                    headers={},
                )
            self.assertEqual(received_types.count("ConfigPublishRequest"), 1)

            with self.assertRaises(NacosGrpcUnavailable):
                await NacosGrpcTransport(
                    NacosGrpcTlsCredentials(root_certificates=server_ca_pem)
                ).request(
                    target,
                    request_type="ConfigPublishRequest",
                    body={"tenant": "missing-client-identity"},
                    headers={},
                )
            self.assertEqual(received_types.count("ConfigPublishRequest"), 1)
        finally:
            await server.stop(0)


def _create_ca(common_name: str):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, certificate


def _create_leaf(issuer_key, issuer_certificate, common_name: str, usage):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_certificate.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common_name)]),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
        .sign(issuer_key, hashes.SHA256())
    )
    return key, certificate


def _certificate_pem(certificate) -> bytes:
    return certificate.public_bytes(serialization.Encoding.PEM)


def _private_key_pem(key) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
