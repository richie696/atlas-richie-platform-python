"""`BaiduSecretClient` — 2-SPI 复合,跑在 Baidu Cloud KMS 官方 SDK 上。

中文
----
对位 Java
`cn.richie696.component.secret.provider.baidu.BaiduSdkSecretTransport`
(SDK 改造版,3 个文件),实现 2-SPI 复合:
`KeyWrappingBackend` via BCE KMS `encrypt` / `decrypt` +
`SecretProviderSession`。
**无** `SecretOperations` / `SecretListable` /
`SecretWriter` / `SecretDeletable`(Baidu KMS 是 KMS-only,
对位 Java `read()` 抛 `SEC-CAP-001`)。

**SDK 类型隔离**:`KmsClient` + `EncryptRequest` /
`DecryptRequest` / `EncryptResult` /
`DecryptResult` 全部不进 framework 边界。Python 端通过
一个 `KmsLike` Protocol 抽象,`BaiduClientFactory` 负责
SDK 适配。

**Error mapping**(对位 Java `BaiduSdkSecretTransport`):
- wrap / unwrap 任意 exception → `SEC-CRYPTO-001` /
  `SEC-CRYPTO-002`
- **不支持 AAD**:Java 端 `requireNoAad(context)` 抛
  `SEC-CAP-001`,Python 端走 framework
  `require_aad_support` 门禁

English
--------
2-SPI composite over Baidu Cloud KMS official SDK
(`bce-python-sdk` v0.9.x). SDK types are isolated via
`KmsLike` Protocol. AAD is not supported; the framework
`require_aad_support` gate rejects it with `SEC-CAP-001`.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from atlas_richie.secret.crypto import (
    KeyReference,
    WrappedKey,
    assert_can_read,
    require_aad_support,
)
from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
)
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.snapshot import SecretSnapshotManager
from atlas_richie.secret_baidu_kms.configuration import ResolvedBaiduConfiguration

_logger = logging.getLogger("atlas_richie.secret_baidu_kms.client")

_WRAPPING_ALGORITHM = "baidu-kms-default"


@dataclass(frozen=True, slots=True)
class BaiduKmsEncryptResponse:
    """Frozen response for BCE KMS `encrypt` (mirrors Java
    `BaiduSdkSecretTransport.wrap` returning
    `kms.encrypt(request).getCiphertext()`).
    """

    ciphertext: str


@dataclass(frozen=True, slots=True)
class BaiduKmsDecryptResponse:
    """Frozen response for BCE KMS `decrypt` (mirrors Java
    `BaiduSdkSecretTransport.unwrap` returning
    `kms.decrypt(request).getPlaintext()`).
    """

    plaintext: str


@runtime_checkable
class KmsLike(Protocol):
    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
    ) -> BaiduKmsEncryptResponse: ...

    def decrypt(
        self,
        key_id: str,
        ciphertext: str,
    ) -> BaiduKmsDecryptResponse: ...


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class BaiduSecretClient:
    """2-SPI composite over Baidu Cloud KMS."""

    __slots__ = (
        "_closed",
        "_configuration_hash",
        "_descriptor_backend",
        "_kms",
        "_properties",
        "_provider_id",
        "_resolved",
        "_snapshot_manager",
    )

    def __init__(
        self,
        resolved: ResolvedBaiduConfiguration,
        kms: KmsLike,
        *,
        descriptor_backend: SecretBackend = SecretBackend.BAIDU,
    ) -> None:
        self._resolved = resolved
        self._properties = resolved.properties
        self._provider_id = resolved.provider_id
        self._configuration_hash = resolved.configuration_hash
        self._descriptor_backend = descriptor_backend
        self._kms = kms
        self._snapshot_manager = SecretSnapshotManager()
        self._closed = False

    # --- KMS-only contract: read() always raises SEC-CAP-001 ---

    def read(self, reference):  # type: ignore[no-untyped-def, override]
        self._ensure_open()
        assert_can_read(self._resolved.capability, backend_label="baidu-kms")
        raise SecretException(  # pragma: no cover
            "baidu-kms: read() should have been blocked by capability gate",
        )

    def metadata(self, reference):  # type: ignore[no-untyped-def, override]
        self._ensure_open()
        assert_can_read(self._resolved.capability, backend_label="baidu-kms")
        raise SecretException(  # pragma: no cover
            "baidu-kms: metadata() should have been blocked by capability gate",
        )

    # --- KeyWrappingBackend ----------------------------------------------

    def wrap_key(
        self,
        dek: bytes,
        kek: KeyReference,
        *,
        algorithm: str | None = None,  # noqa: ARG002 - reserved
    ) -> WrappedKey:
        self._ensure_open()
        require_aad_support(
            self._resolved.capability,
            context=None,
            backend_label="baidu-kms",
        )
        if not dek:
            raise SecretCryptoException(
                "baidu-kms: wrap_key requires a non-empty DEK (SEC-CRYPTO-001)",
            )
        key_id = self._resolve_key_id(kek)
        plaintext_b64 = base64.b64encode(dek).decode("ascii")
        try:
            response = self._kms.encrypt(
                key_id=key_id,
                plaintext_b64=plaintext_b64,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"baidu-kms: KMS Encrypt failed (SEC-CRYPTO-001): {error}",
            ) from error
        if not response.ciphertext:
            raise SecretCryptoException(
                "baidu-kms: KMS returned no ciphertext (SEC-CRYPTO-001)",
            )
        return WrappedKey(
            kek_reference=kek,
            ciphertext=response.ciphertext.encode("utf-8"),
            algorithm=_WRAPPING_ALGORITHM,
        )

    def unwrap_key(
        self,
        wrapped: WrappedKey,
        context,  # type: ignore[no-untyped-def]
    ) -> bytes:
        self._ensure_open()
        require_aad_support(
            self._resolved.capability,
            context=context,
            backend_label="baidu-kms",
        )
        if wrapped.algorithm != _WRAPPING_ALGORITHM:
            raise SecretCryptoException(
                f"baidu-kms: wrapped key algorithm "
                f"{wrapped.algorithm!r} is not supported; expected "
                f"{_WRAPPING_ALGORITHM!r} (SEC-CRYPTO-002)",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "baidu-kms: wrapped ciphertext is empty (SEC-CRYPTO-002)",
            )
        key_id = self._resolve_key_id(context.primary_key)
        try:
            response = self._kms.decrypt(
                key_id=key_id,
                ciphertext=bytes(wrapped.ciphertext).decode("utf-8"),
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"baidu-kms: KMS Decrypt failed (SEC-CRYPTO-002): {error}",
            ) from error
        if not response.plaintext:
            raise SecretCryptoException(
                "baidu-kms: KMS returned no plaintext (SEC-CRYPTO-002)",
            )
        return base64.b64decode(response.plaintext)

    # --- SecretProviderSession -------------------------------------------

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
            namespace=self._properties.region,
        )

    @property
    def operations(self):  # type: ignore[override]
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

    def _resolve_key_id(self, kek: KeyReference) -> str:
        binding = (self._properties.kms_key_bindings or {}).get(kek.key_id)
        if not binding or not binding.strip():
            raise SecretConfigurationException(
                f"baidu-kms: no KMS key binding for KeyReference "
                f"{kek!r} (SEC-KEY-001)",
            )
        return binding

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException("baidu-kms: Secret Provider session is closed")


__all__ = [
    "BaiduSecretClient",
    "KmsLike",
    "BaiduKmsEncryptResponse",
    "BaiduKmsDecryptResponse",
]
