"""KMIP integration test — real TLS mock server + `KmipSecretClient` round-trip.

中文
----
本地启动一个真 KMIP mock server:
1. 用 `cryptography` 生成自签证书
2. 用 `socket + ssl` 起单线程 TLS server
3. server 解析 client 发的请求(TTLV decode)
4. 找到 UNIQUE_IDENTIFIER(用 key_bindings 映射到 simulated key),
   用 simple XOR 把 plaintext / ciphertext 翻转(模拟 AES-KWP,
   测试用)
5. 构造 response,length-prefix 写回

client 走完整个 wrap / unwrap 路径,验证 round-trip 一致。
不依赖任何外部 KMIP server。

English
--------
End-to-end test: spin up a real KMIP mock server (TLS +
self-signed cert) and exercise the full `KmipSecretClient`
wrap / unwrap round-trip. The mock implements
Encrypt (op=31) and Decrypt (op=32) using a simple
key-binding lookup + XOR transform (sufficient for
round-trip verification, not a real KWP).

Mirrors the local-emulator pattern from R-238
(`SoftHSM2` for PKCS#11).
"""

from __future__ import annotations

import datetime
import ipaddress
import socket
import ssl
import struct
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from atlas_richie.secret.crypto import CryptoContext, KeyPurpose, KeyReference
from atlas_richie.secret.errors import SecretCryptoException
from atlas_richie.secret_kmip import ttlv
from atlas_richie.secret_kmip.client import (
    _OP_DECRYPT,
    _OP_ENCRYPT,
    _TAG_BATCH_ITEM,
    _TAG_DATA,
    _TAG_OPERATION,
    _TAG_RESPONSE_MESSAGE,
    _TAG_RESPONSE_PAYLOAD,
    _TAG_RESULT_STATUS,
    _TAG_UNIQUE_IDENTIFIER,
    _RESULT_SUCCESS,
    KmipSecretClient,
)
from atlas_richie.secret_kmip.configuration import (
    KmipConfigurationResolver,
)
from atlas_richie.secret_kmip.factory import KmipSecretProviderFactory
from atlas_richie.secret_kmip.properties import KmipSecretProperties


# ---------------------------------------------------------------------------
# TLS mock server
# ---------------------------------------------------------------------------


def _generate_self_signed(cn: str) -> tuple[bytes, bytes]:
    """Generate a self-signed RSA cert + key (PEM bytes)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, cn)],
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cert_pem, key_pem


class KmipMockServer:
    """Single-threaded TLS KMIP mock server.

    Handles Encrypt (op=31) and Decrypt (op=32) only.
    Each request is answered immediately; the connection
    is closed after one response (matches Java
    `KmipSecretClient.sendOnce`'s one-shot pattern).
    """

    def __init__(self, *, port: int = 0) -> None:
        self._port = port
        self._server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._cert_pem: bytes = b""
        self._key_pem: bytes = b""

    @property
    def port(self) -> int:
        assert self._server_sock is not None
        return self._server_sock.getsockname()[1]

    def start(self) -> None:
        self._cert_pem, self._key_pem = _generate_self_signed("127.0.0.1")
        # Write to temp files for ssl.SSLContext.load_cert_chain
        import tempfile

        cert_dir = Path(tempfile.mkdtemp(prefix="kmip-mock-"))
        cert_path = cert_dir / "cert.pem"
        key_path = cert_dir / "key.pem"
        cert_path.write_bytes(self._cert_pem)
        key_path.write_bytes(self._key_pem)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))

        server_sock = socket.create_server(("127.0.0.1", self._port), backlog=4)
        self._server_sock = server_sock
        self._thread = threading.Thread(
            target=self._serve, args=(ctx,), daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server_sock is not None:
            self._server_sock.close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _serve(self, ctx: ssl.SSLContext) -> None:
        assert self._server_sock is not None
        while True:
            try:
                conn, _ = self._server_sock.accept()
            except OSError:
                return
            try:
                ssl_conn = ctx.wrap_socket(conn, server_side=True)
                try:
                    self._handle_one(ssl_conn)
                finally:
                    ssl_conn.close()
            except OSError:
                continue

    def _handle_one(self, conn: ssl.SSLSocket) -> None:
        """Read one raw TTLV request, write one raw TTLV response, close.

        Mirrors Java `KmipSecretClient.sendOnce`: the wire
        format is the TTLV message itself, with no separate
        length prefix.
        """
        # Read the 8-byte TTLV header (3 tag + 1 type + 4 length)
        header = _read_exact(conn, 8)
        length = struct.unpack(">I", header[4:8])[0]
        # The TTLV value is `length` bytes, padded to 8-byte boundary
        padded = length + ((8 - (length % 8)) % 8)
        body = _read_exact(conn, padded)
        try:
            request = header + body
            response = self._process(request)
        except Exception:
            return
        conn.sendall(response)

    def _process(self, request: bytes) -> bytes:
        """Parse a request and build a response (TTLV)."""
        root = ttlv.children(request)
        # Find OPERATION (recursively into Request Message > Batch Item)
        op_value = ttlv.first(root, _TAG_OPERATION, ttlv.ENUMERATION)
        if op_value is None:
            return b""
        op = struct.unpack(">i", op_value)[0]
        # Find UNIQUE_IDENTIFIER
        uid_value = ttlv.first(root, _TAG_UNIQUE_IDENTIFIER, ttlv.TEXT)
        if uid_value is None:
            return b""
        # Find DATA
        data_value = ttlv.first(root, _TAG_DATA, ttlv.BYTE_STRING)
        if data_value is None:
            return b""

        if op == _OP_ENCRYPT:
            # Mock: append the UniqueID as a tag (NOT real KWP)
            ciphertext = data_value + b":" + uid_value
        elif op == _OP_DECRYPT:
            # Mock: reverse — strip the ":uid" suffix
            # If the suffix doesn't match, raise to simulate a real
            # server's response with non-zero status.
            suffix = b":" + uid_value
            if not data_value.endswith(suffix):
                # Return a failure response
                return self._failure(op, "UniqueID mismatch")
            ciphertext = data_value[: -len(suffix)]
        else:
            return self._failure(op, f"unsupported operation {op}")
        return self._success(op, ciphertext)

    def _success(self, op: int, data: bytes) -> bytes:
        return ttlv.structure(
            _TAG_RESPONSE_MESSAGE,
            ttlv.structure(
                _TAG_BATCH_ITEM,
                ttlv.enumeration(_TAG_OPERATION, op),
                ttlv.enumeration(_TAG_RESULT_STATUS, _RESULT_SUCCESS),
                ttlv.structure(
                    _TAG_RESPONSE_PAYLOAD,
                    ttlv.bytes_(_TAG_DATA, data),
                ),
            ),
        )

    def _failure(self, op: int, message: str) -> bytes:
        # Encode the failure message as DATA (real KMIP would
        # use a Result Reason structure; this is enough for
        # the client to raise SEC-PROVIDER-001).
        return ttlv.structure(
            _TAG_RESPONSE_MESSAGE,
            ttlv.structure(
                _TAG_BATCH_ITEM,
                ttlv.enumeration(_TAG_OPERATION, op),
                ttlv.enumeration(_TAG_RESULT_STATUS, 1),
                ttlv.structure(
                    _TAG_RESPONSE_PAYLOAD,
                    ttlv.bytes_(_TAG_DATA, message.encode("utf-8")),
                ),
            ),
        )


def _read_exact(conn: socket.socket, length: int) -> bytes:
    # `ssl.SSLSocket.recv` requires a plain `bytes` (or
    # int) buffer, NOT a `memoryview`. Build incrementally
    # using `bytes` chunks.
    chunks: list[bytes] = []
    received = 0
    while received < length:
        chunk = conn.recv(length - received)
        if not chunk:
            raise OSError("connection closed")
        chunks.append(chunk)
        received += len(chunk)
    return b"".join(chunks)[:length]


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_server() -> Iterator[KmipMockServer]:
    server = KmipMockServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def client_ssl_context(mock_server: KmipMockServer) -> ssl.SSLContext:
    """Build a client SSL context that trusts the mock server's cert."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(
        cadata=mock_server._cert_pem.decode("ascii"),
    )
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


@pytest.fixture
def kmip_client(
    mock_server: KmipMockServer,
    client_ssl_context: ssl.SSLContext,
) -> Iterator[KmipSecretClient]:
    properties = KmipSecretProperties(
        endpoint=f"kmips://127.0.0.1:{mock_server.port}",
        key_bindings={"default-envelope": "key-abc-123"},
        connect_timeout_seconds=2.0,
        read_timeout_seconds=2.0,
        max_attempts=1,
    )
    resolved = KmipConfigurationResolver().resolve(properties, provider_id="kmip-test")
    client = KmipSecretClient(resolved=resolved, ssl_context=client_ssl_context)
    try:
        yield client
    finally:
        client.close()


def _kek(key_id: str = "key-abc-123") -> KeyReference:
    return KeyReference(
        provider="kmip-test",
        key_id=key_id,
        version=None,
        algorithm="AES-256",
    )


class TestKmipClientRoundTrip:
    def test_wrap_then_unwrap_round_trip(self, kmip_client: KmipSecretClient) -> None:
        kek = _kek()
        plaintext = b"this is a 32-byte plaintext key!!"  # 32 bytes
        wrapped = kmip_client.wrap_key(plaintext, kek)
        assert wrapped.algorithm == "kmip-aes-kwp"
        assert wrapped.ciphertext != plaintext

        context = CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP)
        recovered = kmip_client.unwrap_key(wrapped, context)
        assert recovered == plaintext

    def test_wrap_empty_plaintext_raises(self, kmip_client: KmipSecretClient) -> None:
        with pytest.raises(SecretCryptoException) as info:
            kmip_client.wrap_key(b"", _kek())
        assert "non-empty" in str(info.value)

    def test_unwrap_wrong_algorithm_raises(
        self,
        kmip_client: KmipSecretClient,
    ) -> None:
        from atlas_richie.secret.crypto import WrappedKey

        kek = _kek()
        bad = WrappedKey(
            kek_reference=kek,
            ciphertext=b"junk",
            algorithm="aws-kms",
        )
        context = CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP)
        with pytest.raises(SecretCryptoException) as info:
            kmip_client.unwrap_key(bad, context)
        assert "kmip-aes-kwp" in str(info.value)

    def test_unwrap_unique_id_mismatch_returns_failure_status(
        self,
        kmip_client: KmipSecretClient,
    ) -> None:
        kek = _kek()
        plaintext = b"hello-world"  # 11 bytes
        wrapped = kmip_client.wrap_key(plaintext, kek)

        # Now use a different UniqueID for unwrap — the mock
        # server returns Result Status = 1
        wrong_kek = _kek(key_id="different-key-id")
        context = CryptoContext(primary_key=wrong_kek, purpose=KeyPurpose.WRAP)
        with pytest.raises(SecretCryptoException) as info:
            kmip_client.unwrap_key(wrapped, context)
        assert "result status 1" in str(info.value)
        assert "SEC-PROVIDER-001" in str(info.value)

    def test_descriptor_declares_aliyun_capability(
        self,
        kmip_client: KmipSecretClient,
    ) -> None:
        descriptor = kmip_client.descriptor
        assert descriptor.name == "kmip-test"
        assert descriptor.capability.can_read is False
        assert descriptor.capability.can_write is False
        assert descriptor.capability.encrypts_at_rest is True
        assert descriptor.capability.signs_values is False

    def test_operations_writer_deletable_are_none(
        self,
        kmip_client: KmipSecretClient,
    ) -> None:
        assert kmip_client.operations is None
        assert kmip_client.writer is None
        assert kmip_client.deletable is None

    def test_close_is_idempotent(self, kmip_client: KmipSecretClient) -> None:
        kmip_client.close()
        kmip_client.close()  # idempotent
        assert kmip_client.is_closed is True

    def test_read_after_close_raises(self, kmip_client: KmipSecretClient) -> None:
        kmip_client.close()
        with pytest.raises(Exception):
            kmip_client.wrap_key(b"x" * 32, _kek())


__all__ = []
