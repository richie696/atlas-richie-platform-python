"""`VolcengineSecretClient` — KMS-only 2-SPI 复合(对位 Java SDK 改造)。

中文
----
对位 Java `cn.richie696.component.secret.provider.volcengine.VolcengineSdkSecretTransport`
(SDK 改造版,~100 行),实现 2-SPI 复合:`KeyWrappingBackend` via
KMS `Encrypt` / `Decrypt` + `SecretProviderSession`。**不**实现
`SecretOperations` / `SecretListable` / `SecretWriter` /
`SecretDeletable`(Volcengine KMS-only;Java 端 read() 直接
抛 `SEC-CAP-001`)。

**SDK 类型隔离**:`KmsApi` / Request model 全部不进 framework
边界。Python 端通过 `KmsLike` Protocol 抽象,
`VolcengineClientFactory` 负责 SDK 适配。

**Error mapping**(对位 Java `VolcengineSdkSecretTransport`):
- `SEC-CAP-001`:`read` 抛 `SecretCapabilityException`(
  Java 端 read 直接抛 `SEC-CAP-001` 错误)
- wrap / unwrap 任意 exception → `SEC-CRYPTO-001` /
  `SEC-CRYPTO-002`

**EncryptionContext 编码**(对位 Java `encryptionContext`):
`Map<String, String>`,`aad` byte[] base64 后作
`atlas.secret.aad` 字段;attributes 一起进 map;Python 端
用 AAD dict(framework AAD `Mapping[str, str]`)直接
序列化。

English
--------
KMS-only 2-SPI composite over Volcengine's official SDK
(`volcengine-python-sdk`). SDK types are isolated from
the framework via `KmsLike` Protocol.

NotFound boundary: N/A (KMS-only). Capability gate
(`SEC-CAP-001`) fires on `read` calls because Volcengine
has no Secret Store.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyReference,
    WrappedKey,
)
from atlas_richie.secret.errors import (
    SecretCapabilityException,
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
)
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.snapshot import SecretSnapshotManager
from atlas_richie.secret_volcengine_kms.configuration import (
    ResolvedVolcengineConfiguration,
)

_logger = logging.getLogger("atlas_richie.secret_volcengine_kms.client")

_WRAPPING_ALGORITHM = "volcengine-kms-default"


# ---------------------------------------------------------------------------
# SDK-isolating Protocol + response dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VolcengineKmsEncryptResponse:
    """Frozen response for KMS `Encrypt` (mirrors Java
    `EncryptResponse.getCiphertextBlob()`).
    """

    ciphertext_blob: str


@dataclass(frozen=True, slots=True)
class VolcengineKmsDecryptResponse:
    """Frozen response for KMS `Decrypt` (mirrors Java
    `DecryptResponse.getPlaintext()`).
    """

    plaintext: str


@runtime_checkable
class KmsLike(Protocol):
    """SDK-isolating protocol for Volcengine KMS Encrypt / Decrypt."""

    def encrypt(
        self,
        keyring_name: str,
        key_name: str,
        plaintext_b64: str,
        encryption_context: Mapping[str, str],
    ) -> VolcengineKmsEncryptResponse: ...

    def decrypt(
        self,
        ciphertext_blob: str,
        encryption_context: Mapping[str, str],
    ) -> VolcengineKmsDecryptResponse: ...


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class VolcengineSecretClient:
    """2-SPI composite (KMS-only) over a `KmsLike`."""

    __slots__ = (
        "_closed",
        "_configuration_hash",
        "_descriptor_backend",
        "_kms",
        "_namespace",
        "_properties",
        "_provider_id",
        "_resolved",
        "_snapshot_manager",
    )

    def __init__(
        self,
        resolved: ResolvedVolcengineConfiguration,
        kms: KmsLike,
        *,
        descriptor_backend: SecretBackend = SecretBackend.VOLCENGINE,
    ) -> None:
        self._resolved = resolved
        self._properties = resolved.properties
        self._provider_id = resolved.provider_id
        self._configuration_hash = resolved.configuration_hash
        self._descriptor_backend = descriptor_backend
        self._kms = kms
        self._namespace = resolved.properties.namespace
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
                "volcengine: wrap_key requires a non-empty DEK (SEC-CRYPTO-001)",
            )
        key_name = self._resolve_key_name(kek)
        plain_text_b64 = base64.b64encode(dek).decode("ascii")
        ctx = self._encryption_context_for()
        try:
            response = self._kms.encrypt(
                keyring_name=self._namespace,
                key_name=key_name,
                plaintext_b64=plain_text_b64,
                encryption_context=ctx,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"volcengine: KMS Encrypt failed (SEC-CRYPTO-001): {error}",
            ) from error
        if not response.ciphertext_blob:
            raise SecretCryptoException(
                "volcengine: KMS returned no ciphertext (SEC-CRYPTO-001)",
            )
        return WrappedKey(
            kek_reference=kek,
            ciphertext=response.ciphertext_blob.encode("utf-8"),
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
                f"volcengine: wrapped key algorithm {wrapped.algorithm!r} is not "
                f"supported; expected {_WRAPPING_ALGORITHM!r} (SEC-CRYPTO-002)",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "volcengine: wrapped ciphertext is empty (SEC-CRYPTO-002)",
            )
        key_name = self._resolve_key_name(context.primary_key)
        ctx = self._encryption_context_for(context=context)
        try:
            response = self._kms.decrypt(
                ciphertext_blob=bytes(wrapped.ciphertext).decode("utf-8"),
                encryption_context=ctx,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"volcengine: KMS Decrypt failed (SEC-CRYPTO-002): {error}",
            ) from error
        if not response.plaintext:
            raise SecretCryptoException(
                "volcengine: KMS returned no plaintext (SEC-CRYPTO-002)",
            )
        return base64.b64decode(response.plaintext)

    # --- SecretProviderSession (KMS-only: read / write / list all None) -

    @property
    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self._provider_id,
            backend=self._descriptor_backend,
            capability=self._resolved.capability,
            version="0.2.0",
        )

    @property
    def configuration(self) -> SecretProviderConfiguration:
        return SecretProviderConfiguration(
            name=self._provider_id,
            parameters={},
            timeout_seconds=self._properties.read_timeout_seconds,
            retries=self._properties.max_attempts,
            namespace=self._namespace,
        )

    @property
    def operations(self):  # type: ignore[override]
        # Volcengine has no Secret Store; framework's
        # `list_capability(session)` probe must observe
        # `None` so it doesn't try to call `read` /
        # `get_metadata` / `exists`.
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

    def _resolve_key_name(self, kek: KeyReference) -> str:
        binding = (self._properties.kms_key_bindings or {}).get(kek.key_id)
        if not binding or not binding.strip():
            raise SecretConfigurationException(
                f"volcengine: no KMS key binding for KeyReference {kek!r} (SEC-KEY-001)",
            )
        return binding

    def _encryption_context_for(
        self,
        context: CryptoContext | None = None,
    ) -> dict[str, str]:
        """Build the deterministic `encryptionContext` map.

        Mirrors Java `VolcengineSdkSecretTransport.encryptionContext`:
        - attributes appended as Map entries
        - AAD bytes (when present) Base64-encoded as
          `atlas.secret.aad`
        """
        ctx: dict[str, str] = {}
        if context is not None:
            ctx.update(context.aad)
        return ctx

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException("volcengine: Secret Provider session is closed")


__all__ = [
    "VolcengineSecretClient",
    "KmsLike",
    "VolcengineKmsEncryptResponse",
    "VolcengineKmsDecryptResponse",
]
