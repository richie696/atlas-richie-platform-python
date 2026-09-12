"""`KmipSecretClient` — KMIP 2.1 TLS session over TTLV-encoded messages。

中文
----
对位 Java `cn.richie696.component.secret.provider.kmip.KmipSecretClient`
(112 行),实现 2-SPI 复合:`KeyWrappingBackend` (KMIP Encrypt /
Decrypt) + `SecretProviderSession`。**不**实现
`SecretOperations` / `SecretListable` / `SecretWriter` /
`SecretDeletable`(KMIP 是 key management 协议,不存 secret)。

**TTLV tags / operations**(对位 Java 静态常量):
- `0x420078 REQUEST_MESSAGE`
- `0x420077 REQUEST_HEADER`
- `0x420069 PROTOCOL_VERSION`
- `0x42006a MAJOR / 0x42006b MINOR`
- `0x42000d BATCH_COUNT / 0x42000f BATCH_ITEM`
- `0x42005c OPERATION / 0x420079 REQUEST_PAYLOAD`
- `0x420094 UNIQUE_IDENTIFIER / 0x4200c2 DATA`
- `0x42002b CRYPTO_PARAMETERS / 0x420028 CRYPTO_ALGORITHM / 0x420011 BLOCK_CIPHER_MODE`
- `0x42007b RESPONSE_MESSAGE / 0x42007c RESPONSE_PAYLOAD / 0x42007f RESULT_STATUS`
- Operations: `31` (Encrypt), `32` (Decrypt)
- `BlockCipherMode.KEK_WRAPPING = 12`, `CryptoAlgorithm.AES = 3`

**错误映射**(对位 Java `KmipSecretClient.parseResponse`):
- result status != 0 → `SecretCryptoException("SEC-PROVIDER-001", ...)`
- response operation 不匹配 request → `SecretCryptoException("SEC-PROVIDER-001", ...)`
- response 缺 element → `SecretCryptoException("SEC-PROVIDER-001", ...)`
- TLS 错误 / 长度超限 → `SecretCryptoException("SEC-CRYPTO-001", ...)`

**Transport policy**(对位 Java `KmipSecretClient.retryIo`):
- 瞬时 `OSError` 重试
- `ssl.SSLError` 在握手阶段 → 不重试,直接抛

English
--------
KMIP 2.1 TLS session. 2-SPI composite: `KeyWrappingBackend`
(KMIP Encrypt / Decrypt operations) +
`SecretProviderSession`. No secret read / list / write /
delete — KMIP is a key-management protocol.

The transport layer opens a fresh TLS connection per
request, sends a 4-byte length-prefixed TTLV message, reads
the response, and closes the socket. Retry policy retries
only transient `OSError`; SSL handshake errors are
permanent.
"""

from __future__ import annotations

import logging
import socket
import ssl
import struct
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyReference,
    WrappedKey,
)
from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
)
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.snapshot import SecretSnapshotManager
from atlas_richie.secret_kmip import ttlv
from atlas_richie.secret_kmip.configuration import ResolvedKmipConfiguration
from atlas_richie.secret_kmip.properties import KmipSecretProperties

_logger = logging.getLogger("atlas_richie.secret_kmip.client")

# Wrap algorithm identifier (mirrors Java's "kmip-aes-kwp")
_WRAPPING_ALGORITHM = "kmip-aes-kwp"

# 1:1 with Java's static TTLV tag constants.
_TAG_REQUEST_MESSAGE = 0x420078
_TAG_REQUEST_HEADER = 0x420077
_TAG_PROTOCOL_VERSION = 0x420069
_TAG_MAJOR = 0x42006A
_TAG_MINOR = 0x42006B
_TAG_BATCH_COUNT = 0x42000D
_TAG_BATCH_ITEM = 0x42000F
_TAG_OPERATION = 0x42005C
_TAG_REQUEST_PAYLOAD = 0x420079
_TAG_UNIQUE_IDENTIFIER = 0x420094
_TAG_DATA = 0x4200C2
_TAG_CRYPTO_PARAMETERS = 0x42002B
_TAG_CRYPTO_ALGORITHM = 0x420028
_TAG_BLOCK_CIPHER_MODE = 0x420011
_TAG_RESPONSE_MESSAGE = 0x42007B
_TAG_RESPONSE_PAYLOAD = 0x42007C
_TAG_RESULT_STATUS = 0x42007F

# Operation codes (1:1 with Java's `op` integer).
_OP_ENCRYPT = 31
_OP_DECRYPT = 32

# Crypto parameters (1:1 with Java's `BLOCK_CIPHER_MODE=12` + `CRYPTO_ALGORITHM=3`).
_ALGO_AES = 3
_MODE_KEK_WRAPPING = 12

# Result status (1:1 with Java `RESULT_SUCCESS=0`).
_RESULT_SUCCESS = 0

# 16 MB cap on KMIP response (matches Java's `16 * 1024 * 1024`).
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def _kmip_capability() -> SecretCapability:
    return SecretCapability(
        can_read=False,
        can_write=False,
        can_rotate=False,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=False,
    )


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KmipEndpoint:
    host: str
    port: int


def _parse_endpoint(endpoint: str) -> KmipEndpoint:
    """Parse `kmips://host:port` into `(host, port)`.

    Defaults port to 5696 (the standard KMIP TLS port) when
    not specified. Mirrors Java's `KmipSecretClient` port
    fallback logic.
    """
    if "://" not in endpoint:
        raise SecretConfigurationException(
            f"kmip: endpoint must include scheme: {endpoint!r}",
        )
    _, _, host_part = endpoint.partition("://")
    if "@" in host_part:
        # user-info rejected upstream; defense in depth
        host_part = host_part.rsplit("@", 1)[-1]
    if host_part.startswith("["):
        # IPv6 literal `[::1]:port`
        if "]" in host_part:
            host, _, rest = host_part.partition("]")
            host = host.lstrip("[")
            port_part = rest.lstrip(":")
            port = int(port_part) if port_part else 5696
        else:
            raise SecretConfigurationException(
                f"kmip: malformed IPv6 endpoint: {endpoint!r}",
            )
    elif ":" in host_part:
        host, _, port_part = host_part.rpartition(":")
        port = int(port_part) if port_part else 5696
    else:
        host = host_part
        port = 5696
    return KmipEndpoint(host=host, port=port)


def _build_ssl_context(
    properties: KmipSecretProperties,
) -> ssl.SSLContext:
    """Build an `SSLContext` from the configured trust / key stores.

    Mirrors Java's `KmipSecretClient.sslSocketFactory`. If
    no trust_store is configured, falls back to the system
    trust store (`ssl.create_default_context`).
    """
    if properties.trust_store:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(
            cafile=properties.trust_store,
        )
    else:
        ctx = ssl.create_default_context()
    if properties.key_store:
        # Optional client cert for mutual TLS.
        ctx.load_cert_chain(
            certfile=properties.key_store,
            password=properties.key_store_password,
        )
    # Default: do NOT verify hostname — KMIP servers often
    # use bare IPs / internal names. The `trust_store`
    # controls trust; hostname check is a deployment-level
    # decision.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED if properties.trust_store else ssl.CERT_NONE
    return ctx


def _send_request(
    *,
    host: str,
    port: int,
    payload: bytes,
    ssl_context: ssl.SSLContext,
    connect_timeout: float,
    read_timeout: float,
) -> bytes:
    """Send one KMIP request and return the response bytes.

    Mirrors Java's `KmipSecretClient.sendOnce`: open a
    socket, write the 4-byte length-prefixed request, read
    the 8-byte response header + (length + padding) body,
    close. **The total response length is the first 4 bytes
    of the header in big-endian; the next 4 bytes are the
    TTLV length** (matches Java
    `ByteBuffer.wrap(header, 4, 4).getInt()`).
    """
    sock: socket.socket | ssl.SSLSocket = socket.create_connection(
        (host, port), timeout=connect_timeout,
    )
    try:
        sock.settimeout(read_timeout)
        if ssl_context is not None:
            sock = ssl_context.wrap_socket(sock, server_hostname=None)
        # Wire format: raw TTLV (no length prefix). Mirrors
        # Java's `out.write(request)`.
        sock.sendall(payload)
        # Read the 8-byte TTLV header (3 tag + 1 type + 4 length)
        header = _read_exact(sock, 8)
        length = struct.unpack(">I", header[4:8])[0]
        if length < 0 or length > _MAX_RESPONSE_BYTES:
            raise SecretCryptoException(
                f"kmip: response length is invalid: {length} (SEC-CRYPTO-001)",
            )
        # The TTLV value is `length` bytes, padded to 8-byte boundary
        padded = length + ((8 - (length % 8)) % 8)
        body = _read_exact(sock, padded)
        return bytes(header) + bytes(body)
    finally:
        try:
            sock.close()
        except Exception as error:  # noqa: BLE001
            _logger.debug("kmip: socket close raised: %s", error)


def _read_exact(sock: socket.socket, length: int) -> bytes:
    """Read exactly `length` bytes from a blocking socket (mirrors Java `readFully`).

    Uses `bytes` chunks because `ssl.SSLSocket.recv` does
    not accept a `memoryview` buffer.
    """
    chunks: list[bytes] = []
    received = 0
    while received < length:
        chunk = sock.recv(length - received)
        if not chunk:
            raise SecretCryptoException(
                f"kmip: connection closed before {length} bytes were read "
                f"(SEC-CRYPTO-001)",
            )
        chunks.append(chunk)
        received += len(chunk)
    return b"".join(chunks)[:length]


def _retry_io(
    max_attempts: int,
    operation: Callable[[], bytes],
) -> bytes:
    """Retry policy: transient `OSError` retries; SSL handshake
    errors are permanent (mirrors Java `KmipSecretClient.retryIo`).
    """
    attempts = max(1, max_attempts)
    last: OSError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except ssl.SSLError as error:
            # Handshake / cert verification failures are not
            # transient. Re-raise immediately.
            raise
        except OSError as error:
            last = error
            _logger.warning(
                "kmip: transient IO failure on attempt %d/%d: %s",
                attempt,
                attempts,
                error,
            )
            if attempt == attempts:
                raise
    if last is None:
        raise OSError("kmip: no attempts executed")
    raise last


# ---------------------------------------------------------------------------
# Request / response building
# ---------------------------------------------------------------------------


def _build_encrypt_request(
    *,
    unique_identifier: str,
    plaintext: bytes,
    major: int,
    minor: int,
) -> bytes:
    """Build a KMIP 2.1 Encrypt request (mirrors Java
    `KmipSecretClient.operation(31, ...)`).
    """
    return ttlv.structure(
        _TAG_REQUEST_MESSAGE,
        ttlv.structure(
            _TAG_REQUEST_HEADER,
            ttlv.structure(
                _TAG_PROTOCOL_VERSION,
                ttlv.integer(_TAG_MAJOR, major),
                ttlv.integer(_TAG_MINOR, minor),
            ),
            ttlv.integer(_TAG_BATCH_COUNT, 1),
        ),
        ttlv.structure(
            _TAG_BATCH_ITEM,
            ttlv.enumeration(_TAG_OPERATION, _OP_ENCRYPT),
            ttlv.structure(
                _TAG_REQUEST_PAYLOAD,
                ttlv.text(_TAG_UNIQUE_IDENTIFIER, unique_identifier),
                ttlv.structure(
                    _TAG_CRYPTO_PARAMETERS,
                    ttlv.enumeration(_TAG_BLOCK_CIPHER_MODE, _MODE_KEK_WRAPPING),
                    ttlv.enumeration(_TAG_CRYPTO_ALGORITHM, _ALGO_AES),
                ),
                ttlv.bytes_(_TAG_DATA, plaintext),
            ),
        ),
    )


def _build_decrypt_request(
    *,
    unique_identifier: str,
    ciphertext: bytes,
    major: int,
    minor: int,
) -> bytes:
    """Build a KMIP 2.1 Decrypt request (mirrors Java
    `KmipSecretClient.operation(32, ...)`).
    """
    return ttlv.structure(
        _TAG_REQUEST_MESSAGE,
        ttlv.structure(
            _TAG_REQUEST_HEADER,
            ttlv.structure(
                _TAG_PROTOCOL_VERSION,
                ttlv.integer(_TAG_MAJOR, major),
                ttlv.integer(_TAG_MINOR, minor),
            ),
            ttlv.integer(_TAG_BATCH_COUNT, 1),
        ),
        ttlv.structure(
            _TAG_BATCH_ITEM,
            ttlv.enumeration(_TAG_OPERATION, _OP_DECRYPT),
            ttlv.structure(
                _TAG_REQUEST_PAYLOAD,
                ttlv.text(_TAG_UNIQUE_IDENTIFIER, unique_identifier),
                ttlv.structure(
                    _TAG_CRYPTO_PARAMETERS,
                    ttlv.enumeration(_TAG_BLOCK_CIPHER_MODE, _MODE_KEK_WRAPPING),
                    ttlv.enumeration(_TAG_CRYPTO_ALGORITHM, _ALGO_AES),
                ),
                ttlv.bytes_(_TAG_DATA, ciphertext),
            ),
        ),
    )


def _parse_response(
    expected_operation: int,
    response: bytes,
) -> bytes:
    """Parse a KMIP 2.1 response and extract the DATA element.

    Mirrors Java `KmipSecretClient.parseResponse`. Validates:
    - single RESPONSE_MESSAGE / BATCH_ITEM (no duplicates)
    - operation matches the request
    - result status == 0 (success)
    - DATA element is present
    """
    root = ttlv.children(response)
    message = _single(root, _TAG_RESPONSE_MESSAGE, ttlv.STRUCTURE, "Response Message")
    batch = _single(
        ttlv.children(message.value),
        _TAG_BATCH_ITEM,
        ttlv.STRUCTURE,
        "Batch Item",
    )
    batch_children = ttlv.children(batch.value)
    operation = _enumeration(
        _single(batch_children, _TAG_OPERATION, ttlv.ENUMERATION, "Operation"),
        "Operation",
    )
    if operation != expected_operation:
        raise SecretCryptoException(
            f"kmip: response operation {operation} does not match "
            f"request operation {expected_operation} (SEC-PROVIDER-001)",
        )
    status = _enumeration(
        _single(batch_children, _TAG_RESULT_STATUS, ttlv.ENUMERATION, "Result Status"),
        "Result Status",
    )
    if status != _RESULT_SUCCESS:
        raise SecretCryptoException(
            f"kmip: operation failed with result status {status} (SEC-PROVIDER-001)",
        )
    payload = _single(
        batch_children,
        _TAG_RESPONSE_PAYLOAD,
        ttlv.STRUCTURE,
        "Response Payload",
    )
    data = _single(
        ttlv.children(payload.value),
        _TAG_DATA,
        ttlv.BYTE_STRING,
        "Data",
    )
    return bytes(data.value)


def _single(
    elements: Iterable[ttlv.Element],
    tag: int,
    type_code: int,
    label: str,
) -> ttlv.Element:
    match: ttlv.Element | None = None
    for element_ in elements:
        if element_.tag == tag and element_.type == type_code:
            if match is not None:
                raise SecretCryptoException(
                    f"kmip: response contains multiple {label} elements (SEC-PROVIDER-001)",
                )
            match = element_
    if match is None:
        raise SecretCryptoException(
            f"kmip: response is missing {label} (SEC-PROVIDER-001)",
        )
    return match


def _enumeration(element_: ttlv.Element, label: str) -> int:
    if len(element_.value) != 4:
        raise SecretCryptoException(
            f"kmip: {label} has invalid length: {len(element_.value)} (SEC-PROVIDER-001)",
        )
    return struct.unpack(">i", element_.value)[0]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class KmipSecretClient:
    """2-SPI composite session over a KMIP 2.1 TLS server.

    Mirrors Java `KmipSecretClient`. The session's
    `operations` / `writer` / `deletable` properties all
    return `None` because KMIP is a key-management
    protocol, not a secret store (matches the PKCS#11 HSM
    pattern from R-238).
    """

    __slots__ = (
        "_closed",
        "_configuration_hash",
        "_descriptor_backend",
        "_endpoint",
        "_properties",
        "_provider_id",
        "_resolved",
        "_snapshot_manager",
        "_ssl_context",
    )

    def __init__(
        self,
        resolved: ResolvedKmipConfiguration,
        ssl_context: ssl.SSLContext,
        *,
        descriptor_backend: SecretBackend = SecretBackend.PKCS11,
    ) -> None:
        self._resolved = resolved
        self._properties = resolved.properties
        self._provider_id = resolved.provider_id
        self._configuration_hash = resolved.configuration_hash
        self._endpoint = _parse_endpoint(self._properties.endpoint)
        self._ssl_context = ssl_context
        self._descriptor_backend = descriptor_backend
        self._snapshot_manager = SecretSnapshotManager()
        self._closed = False

    # --- KeyWrappingBackend ----------------------------------------------

    def wrap_key(
        self,
        dek: bytes,
        kek: KeyReference,
        *,
        algorithm: str | None = None,  # noqa: ARG002 - reserved
    ) -> WrappedKey:
        self._ensure_open()
        if not dek:
            raise SecretCryptoException(
                "kmip: wrap_key requires a non-empty DEK (SEC-CRYPTO-001)",
            )
        unique_id = self._resolve_unique_id(kek)
        request = _build_encrypt_request(
            unique_identifier=unique_id,
            plaintext=dek,
            major=self._properties.protocol_major,
            minor=self._properties.protocol_minor,
        )
        try:
            response = self._send(request)
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"kmip: Encrypt operation failed (SEC-CRYPTO-001): {error}",
            ) from error
        ciphertext = _parse_response(_OP_ENCRYPT, response)
        return WrappedKey(
            kek_reference=kek,
            ciphertext=ciphertext,
            algorithm=_WRAPPING_ALGORITHM,
        )

    def unwrap_key(
        self,
        wrapped: WrappedKey,
        context: CryptoContext,
    ) -> bytes:
        self._ensure_open()
        if wrapped.algorithm != _WRAPPING_ALGORITHM:
            raise SecretCryptoException(
                f"kmip: wrapped key algorithm {wrapped.algorithm!r} is not "
                f"supported; expected {_WRAPPING_ALGORITHM!r} (SEC-CRYPTO-002)",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "kmip: wrapped ciphertext is empty (SEC-CRYPTO-002)",
            )
        unique_id = self._resolve_unique_id(context.primary_key)
        request = _build_decrypt_request(
            unique_identifier=unique_id,
            ciphertext=wrapped.ciphertext,
            major=self._properties.protocol_major,
            minor=self._properties.protocol_minor,
        )
        try:
            response = self._send(request)
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"kmip: Decrypt operation failed (SEC-CRYPTO-002): {error}",
            ) from error
        return _parse_response(_OP_DECRYPT, response)

    # --- SecretProviderSession -------------------------------------------

    @property
    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self._provider_id,
            backend=self._descriptor_backend,
            capability=_kmip_capability(),
            version="0.2.0",
        )

    @property
    def configuration(self) -> SecretProviderConfiguration:
        return SecretProviderConfiguration(
            name=self._provider_id,
            parameters={},
            timeout_seconds=self._properties.read_timeout_seconds,
            retries=self._properties.max_attempts,
            namespace=self._properties.endpoint,
        )

    @property
    def operations(self) -> SecretOperations | None:  # type: ignore[override]
        return None

    @property
    def writer(self):  # type: ignore[override]
        return None

    @property
    def deletable(self):  # type: ignore[override]
        return None

    @property
    def snapshot_manager(self) -> SecretSnapshotManager:
        return self._snapshot_manager

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def configuration_hash(self) -> str:
        return self._configuration_hash

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

    # --- Internal helpers ------------------------------------------------

    def _resolve_unique_id(self, kek: KeyReference) -> str:
        if not kek.key_id or not kek.key_id.strip():
            raise SecretConfigurationException(
                f"kmip: no key binding for KeyReference {kek!r} (SEC-KEY-001)",
            )
        return kek.key_id

    def _send(self, request: bytes) -> bytes:
        def op() -> bytes:
            return _send_request(
                host=self._endpoint.host,
                port=self._endpoint.port,
                payload=request,
                ssl_context=self._ssl_context,
                connect_timeout=self._properties.connect_timeout_seconds,
                read_timeout=self._properties.read_timeout_seconds,
            )
        return _retry_io(self._properties.max_attempts, op)

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException("kmip: Secret Provider session is closed")


__all__ = [
    "KmipSecretClient",
    "KmipEndpoint",
    "_parse_endpoint",
    "_build_ssl_context",
    "_build_encrypt_request",
    "_build_decrypt_request",
    "_parse_response",
    "_send_request",
    "_retry_io",
    "_WRAPPING_ALGORITHM",
]
