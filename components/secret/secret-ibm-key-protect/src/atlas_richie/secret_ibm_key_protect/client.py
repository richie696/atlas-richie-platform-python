"""`IbmKeyProtectSecretClient` — 2-SPI 复合,跑在 IBM Key Protect REST 上。

中文
----
对位 Java
`cn.richie696.component.secret.provider.ibm.IbmKeyProtectSdkSecretTransport`
(SDK 改造版,IBM Cloud Key Protect 官方 Python SDK 在 PyPI
**不存在**,所以用 `ibm-cloud-sdk-core` 提供
`BearerTokenAuthenticator` + `httpx` 直连 IBM Key Protect
REST API),实现 2-SPI 复合:`KeyWrappingBackend` via
Key Protect `wrap` / `unwrap` + `SecretProviderSession`。
**无** `SecretOperations` / `SecretListable` /
`SecretWriter` / `SecretDeletable`(IBM Key Protect 是
KMS-only,对位 Java `read()` 抛 `SEC-CAP-001`)。

**SDK 类型隔离**:`httpx.Client` + JSON 请求体全部不进
framework 边界。Python 端通过一个 `KmsLike` Protocol
抽象,`IbmKeyProtectClientFactory` 负责 HTTP 适配。

**Error mapping**(对位 Java `IbmKeyProtectSdkSecretTransport`):
- wrap / unwrap 任意 HTTP / SDK 异常 →
  `SEC-CRYPTO-001` / `SEC-CRYPTO-002`
- **不支持 AAD**:Java 端 `requireNoAad(context)` 抛
  `SEC-CAP-001`,Python 端走 framework `require_aad_support`
  门禁
- HTTP 4xx 的 `vault.read` → 不发生(KMS-only)

English
--------
2-SPI composite over IBM Key Protect REST API
(`/api/v2/keys/{id}/wrap` /
`/api/v2/keys/{id}/unwrap`). No official Python SDK on
PyPI, so this wheel uses
`ibm-cloud-sdk-core.BearerTokenAuthenticator` for auth
signing plus `httpx.Client` for HTTP. AAD is not
supported; the framework `require_aad_support` gate
rejects it with `SEC-CAP-001`.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from enum import Enum
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
from atlas_richie.secret_ibm_key_protect.configuration import (
    ResolvedIbmKeyProtectConfiguration,
)

_logger = logging.getLogger("atlas_richie.secret_ibm_key_protect.client")

_WRAPPING_ALGORITHM = "ibm-key-protect-default"


class WrapOperation(str, Enum):
    """Mirrors Java's `IbmKeyProtectSdkSecretTransport` wrap/unwrap
    key-action types (used as JSON `keyAction` marker in the
    request body when present).
    """

    WRAP = "wrap"
    UNWRAP = "unwrap"


@dataclass(frozen=True, slots=True)
class IbmKeyProtectWrapResponse:
    """Frozen response for Key Protect `wrap` (mirrors Java
    `WrapKeyOptions.execute().getResult().getCiphertext()`).
    """

    ciphertext: str  # base64


@dataclass(frozen=True, slots=True)
class IbmKeyProtectUnwrapResponse:
    """Frozen response for Key Protect `unwrap` (mirrors Java
    `UnwrapKeyOptions.execute().getResult().getPlaintext()`).
    """

    plaintext: str  # base64


@runtime_checkable
class KmsLike(Protocol):
    """`KmsLike` — minimal Protocol for IBM Key Protect KMS.

    The IBM Key Protect REST API does not separate plaintext /
    ciphertext into different response fields; the adapter
    is responsible for base64-encoding the DEK before the
    call and base64-decoding the response.
    """

    def wrap(
        self,
        key_id: str,
        plaintext_b64: str,
    ) -> IbmKeyProtectWrapResponse: ...

    def unwrap(
        self,
        key_id: str,
        ciphertext: str,
    ) -> IbmKeyProtectUnwrapResponse: ...


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class IbmKeyProtectSecretClient:
    """2-SPI composite over IBM Key Protect REST."""

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
        resolved: ResolvedIbmKeyProtectConfiguration,
        kms: KmsLike,
        *,
        descriptor_backend: SecretBackend = SecretBackend.IBM_KEY_PROTECT,
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
        assert_can_read(self._resolved.capability, backend_label="ibm-key-protect")
        # Defensive: assert_can_read should raise before reaching here
        raise SecretException(  # pragma: no cover
            "ibm-key-protect: read() should have been blocked by capability gate",
        )

    def metadata(self, reference):  # type: ignore[no-untyped-def, override]
        self._ensure_open()
        assert_can_read(self._resolved.capability, backend_label="ibm-key-protect")
        raise SecretException(  # pragma: no cover
            "ibm-key-protect: metadata() should have been blocked by capability gate",
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
            backend_label="ibm-key-protect",
        )
        if not dek:
            raise SecretCryptoException(
                "ibm-key-protect: wrap_key requires a non-empty DEK (SEC-CRYPTO-001)",
            )
        key_id = self._resolve_key_id(kek)
        plaintext_b64 = base64.b64encode(dek).decode("ascii")
        try:
            response = self._kms.wrap(
                key_id=key_id,
                plaintext_b64=plaintext_b64,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"ibm-key-protect: wrap failed (SEC-CRYPTO-001): {error}",
            ) from error
        if not response.ciphertext:
            raise SecretCryptoException(
                "ibm-key-protect: wrap returned no ciphertext (SEC-CRYPTO-001)",
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
            backend_label="ibm-key-protect",
        )
        if wrapped.algorithm != _WRAPPING_ALGORITHM:
            raise SecretCryptoException(
                f"ibm-key-protect: wrapped key algorithm "
                f"{wrapped.algorithm!r} is not supported; expected "
                f"{_WRAPPING_ALGORITHM!r} (SEC-CRYPTO-002)",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "ibm-key-protect: wrapped ciphertext is empty (SEC-CRYPTO-002)",
            )
        key_id = self._resolve_key_id(context.primary_key)
        try:
            response = self._kms.unwrap(
                key_id=key_id,
                ciphertext=bytes(wrapped.ciphertext).decode("utf-8"),
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"ibm-key-protect: unwrap failed (SEC-CRYPTO-002): {error}",
            ) from error
        if not response.plaintext:
            raise SecretCryptoException(
                "ibm-key-protect: unwrap returned no plaintext (SEC-CRYPTO-002)",
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
                f"ibm-key-protect: no KMS key binding for KeyReference "
                f"{kek!r} (SEC-KEY-001)",
            )
        return binding

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException("ibm-key-protect: Secret Provider session is closed")


__all__ = [
    "IbmKeyProtectSecretClient",
    "KmsLike",
    "IbmKeyProtectWrapResponse",
    "IbmKeyProtectUnwrapResponse",
    "WrapOperation",
]
