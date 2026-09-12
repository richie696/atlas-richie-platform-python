"""`OciSecretClient` — 3-SPI 复合,跑在 OCI Vault + KMS 官方 SDK 上。

中文
----
对位 Java `cn.richie696.component.secret.provider.oci.OciSdkSecretTransport`
(SDK 改造版,~85 行),实现 3-SPI 复合:`SecretOperations` via
OCI Vault `getSecretBundle` + `KeyWrappingBackend` via OCI
KMS `encrypt` / `decrypt` + `SecretBootstrapClient` +
`SecretProviderSession`。

**SDK 类型隔离**:`SecretsClient` / `KmsCryptoClient` /
OCI SDK model 全部不进 framework 边界。Python 端通过两个
Protocol(`VaultLike` / `KmsLike`)抽象,`OciClientFactory`
负责 SDK 适配。

**Error mapping**(对位 Java `OciSdkSecretTransport`):
- HTTP 404 → missing(返回 `None` / 抛 `SecretIntegrityException`)
- 其它 `BmcException` → `SEC-PROVIDER-001`
- wrap / unwrap 任意 exception → `SEC-CRYPTO-001` /
  `SEC-CRYPTO-002`
- 不支持 AAD byte 形式(AAD 作为 `associatedData` bytes)
  → framework 接受 AAD dict 编码

**AAD 编码**(对位 Java `aad`):OCI KMS 的 `associatedData`
接 byte[];Python 端 AAD `Mapping[str, str]` 走确定性
JSON 编码 + base64。

English
--------
3-SPI composite over OCI's official SDK (`oci-python-sdk`).
SDK types are isolated via `VaultLike` / `KmsLike` Protocols.

NotFound boundary: only HTTP 404 maps to `null`; all
other `BmcException` surface as `SEC-PROVIDER-001`. AAD
is supported via `associatedData` bytes (Base64 + JSON).
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, runtime_checkable

from atlas_richie.secret.bootstrap.catalog import RequiredWhen
from atlas_richie.secret.bootstrap.spi import (
    SecretBootstrapContext,
    SecretBootstrapRequest,
    SecretBootstrapResult,
)
from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyPurpose,
    KeyReference,
    WrappedKey,
    assert_can_read,
)
from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend, SecretMetadata
from atlas_richie.secret.operations import SecretOperations
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.reference import (
    SecretReference,
    SecretVersion,
    SecretVersionSelectorKind,
)
from atlas_richie.secret.snapshot import SecretSnapshotManager
from atlas_richie.secret.value import SecretValue
from atlas_richie.secret_oci_vault_kms.configuration import ResolvedOciConfiguration

_logger = logging.getLogger("atlas_richie.secret_oci_vault_kms.client")

_WRAPPING_ALGORITHM = "oci-kms-default"
_NOT_FOUND_HTTP = 404


# ---------------------------------------------------------------------------
# SDK-isolating Protocols + response dataclasses
# ---------------------------------------------------------------------------


class OciVersionKind(str, Enum):
    """Mirrors Java's `SecretVersionSelector.Type` (LATEST / VERSION / STAGE / ALIAS)."""

    LATEST = "latest"
    VERSION = "version"
    STAGE = "stage"
    ALIAS = "alias"


@dataclass(frozen=True, slots=True)
class OciVaultSecret:
    """Frozen response for Vault `getSecretBundle` (mirrors Java
    `SecretBundle` + `Base64SecretBundleContentDetails`).

    Attributes:
        secret_id: Physical OCI secret OCID.
        version_name: Concrete version (Java `getVersionName()`).
        content: Base64-decoded secret bytes (Java
            `Base64SecretBundleContentDetails.getContent()`
            base64-decoded).
        create_time: UTC creation time (Java `getTimeCreated().toInstant()`).
    """

    secret_id: str
    version_name: str
    content: bytes
    create_time: datetime | None


@dataclass(frozen=True, slots=True)
class OciKmsEncryptResponse:
    """Frozen response for KMS `encrypt` (mirrors Java
    `EncryptedData.getCiphertext()`).
    """

    ciphertext: str


@dataclass(frozen=True, slots=True)
class OciKmsDecryptResponse:
    """Frozen response for KMS `decrypt` (mirrors Java
    `DecryptedData.getPlaintext()`).
    """

    plaintext: str


@runtime_checkable
class VaultLike(Protocol):
    def get_secret_bundle(
        self,
        secret_id: str,
        version_number: int | None,
        stage: str | None,
        secret_version_name: str | None,
    ) -> OciVaultSecret | None: ...


@runtime_checkable
class KmsLike(Protocol):
    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
        associated_data: "dict[str, str] | None",
    ) -> OciKmsEncryptResponse: ...

    def decrypt(
        self,
        key_id: str,
        ciphertext: str,
        associated_data: "dict[str, str] | None",
    ) -> OciKmsDecryptResponse: ...


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class OciSecretClient:
    """3-SPI composite over OCI Vault + KMS."""

    __slots__ = (
        "_closed",
        "_configuration_hash",
        "_descriptor_backend",
        "_kms",
        "_properties",
        "_provider_id",
        "_resolved",
        "_snapshot_manager",
        "_vault",
    )

    def __init__(
        self,
        resolved: ResolvedOciConfiguration,
        vault: VaultLike,
        kms: KmsLike,
        *,
        descriptor_backend: SecretBackend = SecretBackend.OCI,
    ) -> None:
        self._resolved = resolved
        self._properties = resolved.properties
        self._provider_id = resolved.provider_id
        self._configuration_hash = resolved.configuration_hash
        self._descriptor_backend = descriptor_backend
        self._vault = vault
        self._kms = kms
        self._snapshot_manager = SecretSnapshotManager()
        self._closed = False

    # --- SecretOperations ------------------------------------------------

    def read(self, reference: SecretReference) -> SecretValue:
        self._ensure_open()
        assert_can_read(self._resolved.capability, backend_label="oci")
        secret_id = self._resolve_secret_id(reference)
        kind, value = self._version_selector_to_vault(reference)
        try:
            response = self._vault.get_secret_bundle(
                secret_id=secret_id,
                version_number=value if kind is OciVersionKind.VERSION else None,
                stage=value if kind is OciVersionKind.STAGE else None,
                secret_version_name=value if kind is OciVersionKind.ALIAS else None,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            if _is_not_found(error):
                raise SecretIntegrityException(
                    f"oci: Secret is missing: {secret_id!r}",
                )
            raise SecretException(
                f"oci: Vault read failed (SEC-PROVIDER-001): {error}",
            ) from error
        if response is None:
            raise SecretIntegrityException(
                f"oci: Secret is missing: {secret_id!r}",
            )
        try:
            return SecretValue(
                plaintext=response.content,
                metadata=SecretMetadata(
                    reference=reference,
                    version=SecretVersion(
                        number=response.version_name or "latest",
                        created_at=response.create_time or datetime.now(tz=timezone.utc),
                    ),
                    backend=self._descriptor_backend,
                    created_at=response.create_time or datetime.now(tz=timezone.utc),
                    expires_at=None,
                    tags={"provider": "oci"},
                ),
            )
        finally:
            self._zero(response.content)

    def metadata(self, reference: SecretReference) -> SecretMetadata:
        self._ensure_open()
        assert_can_read(self._resolved.capability, backend_label="oci")
        secret_id = self._resolve_secret_id(reference)
        kind, value = self._version_selector_to_vault(reference)
        try:
            response = self._vault.get_secret_bundle(
                secret_id=secret_id,
                version_number=value if kind is OciVersionKind.VERSION else None,
                stage=value if kind is OciVersionKind.STAGE else None,
                secret_version_name=value if kind is OciVersionKind.ALIAS else None,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            if _is_not_found(error):
                raise SecretIntegrityException(
                    f"oci: Secret metadata is missing: {secret_id!r}",
                )
            raise SecretException(
                f"oci: Vault metadata failed (SEC-PROVIDER-001): {error}",
            ) from error
        if response is None:
            raise SecretIntegrityException(
                f"oci: Secret metadata is missing: {secret_id!r}",
            )
        return SecretMetadata(
            reference=reference,
            version=SecretVersion(
                number=response.version_name or "latest",
                created_at=response.create_time or datetime.now(tz=timezone.utc),
            ),
            backend=self._descriptor_backend,
            created_at=response.create_time or datetime.now(tz=timezone.utc),
            expires_at=None,
            tags={"provider": "oci"},
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
        if not dek:
            raise SecretCryptoException(
                "oci: wrap_key requires a non-empty DEK (SEC-CRYPTO-001)",
            )
        key_id = self._resolve_key_id(kek)
        plaintext_b64 = base64.b64encode(dek).decode("ascii")
        try:
            response = self._kms.encrypt(
                key_id=key_id,
                plaintext_b64=plaintext_b64,
                associated_data=None,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"oci: KMS Encrypt failed (SEC-CRYPTO-001): {error}",
            ) from error
        if not response.ciphertext:
            raise SecretCryptoException(
                "oci: KMS returned no ciphertext (SEC-CRYPTO-001)",
            )
        return WrappedKey(
            kek_reference=kek,
            ciphertext=response.ciphertext.encode("utf-8"),
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
                f"oci: wrapped key algorithm {wrapped.algorithm!r} is not "
                f"supported; expected {_WRAPPING_ALGORITHM!r} (SEC-CRYPTO-002)",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "oci: wrapped ciphertext is empty (SEC-CRYPTO-002)",
            )
        key_id = self._resolve_key_id(context.primary_key)
        aad_map = self._aad_map_for(context)
        try:
            response = self._kms.decrypt(
                key_id=key_id,
                ciphertext=bytes(wrapped.ciphertext).decode("utf-8"),
                associated_data=aad_map,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"oci: KMS Decrypt failed (SEC-CRYPTO-002): {error}",
            ) from error
        if not response.plaintext:
            raise SecretCryptoException(
                "oci: KMS returned no plaintext (SEC-CRYPTO-002)",
            )
        return base64.b64decode(response.plaintext)

    # --- SecretBootstrapClient -------------------------------------------

    def bootstrap(
        self,
        request: SecretBootstrapRequest,
        context: SecretBootstrapContext,
    ) -> SecretBootstrapResult:
        self._ensure_open()
        started_at = context.now
        resolved: dict[str, SecretValue] = {}
        missing: list[str] = []
        for binding in request.catalog.bindings:
            try:
                secret_id = self._resolve_secret_id(binding.reference)
                kind, value = self._version_selector_to_vault(binding.reference)
                try:
                    response = self._vault.get_secret_bundle(
                        secret_id=secret_id,
                        version_number=value if kind is OciVersionKind.VERSION else None,
                        stage=value if kind is OciVersionKind.STAGE else None,
                        secret_version_name=value if kind is OciVersionKind.ALIAS else None,
                    )
                except Exception as error:  # noqa: BLE001
                    if _is_not_found(error):
                        raise SecretIntegrityException(
                            f"oci: Secret is missing: {secret_id!r}",
                        )
                    raise SecretException(
                        f"oci: Vault read failed (SEC-PROVIDER-001): {error}",
                    ) from error
                if response is None:
                    raise SecretIntegrityException(
                        f"oci: Secret is missing: {secret_id!r}",
                    )
                try:
                    resolved[binding.name] = SecretValue(
                        plaintext=response.content,
                        metadata=SecretMetadata(
                            reference=binding.reference,
                            version=SecretVersion(
                                number=response.version_name or "latest",
                                created_at=response.create_time or datetime.now(tz=timezone.utc),
                            ),
                            backend=self._descriptor_backend,
                            created_at=response.create_time or datetime.now(tz=timezone.utc),
                            expires_at=None,
                            tags={"provider": "oci"},
                        ),
                    )
                finally:
                    self._zero(response.content)
            except SecretIntegrityException as error:
                if binding.required_when in (
                    RequiredWhen.STARTUP,
                    RequiredWhen.PRODUCTION_ONLY,
                ):
                    raise SecretException(
                        f"oci: bootstrap Secret binding {binding.name!r} is missing "
                        f"(SEC-STORE-001): {error}",
                    ) from error
                missing.append(binding.name)
                _logger.warning(
                    "oci: bootstrap binding %r missing (required_when=%s); continuing",
                    binding.name,
                    binding.required_when.value,
                )
        return SecretBootstrapResult(
            resolved=resolved,
            missing=tuple(missing),
            started_at=started_at,
            finished_at=context.now,
        )

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
    def operations(self) -> SecretOperations | None:  # type: ignore[override]
        return self  # type: ignore[return-value]

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

    def _resolve_secret_id(self, reference: SecretReference) -> str:
        mapping = (self._properties.secrets or {}).get(reference.path)
        if mapping:
            return mapping
        return reference.path

    def _resolve_key_id(self, kek: KeyReference) -> str:
        binding = (self._properties.kms_key_bindings or {}).get(kek.key_id)
        if not binding or not binding.strip():
            raise SecretConfigurationException(
                f"oci: no KMS key binding for KeyReference {kek!r} (SEC-KEY-001)",
            )
        return binding

    def _version_selector_to_vault(
        self,
        reference: SecretReference,
    ) -> tuple[OciVersionKind, str | int | None]:
        selector = reference.version_selector
        if selector.kind is SecretVersionSelectorKind.STATIC and selector.static_version:
            return OciVersionKind.VERSION, int(selector.static_version.number)
        if selector.kind is SecretVersionSelectorKind.PINNED_AT_TIME:
            return OciVersionKind.LATEST, None
        return OciVersionKind.LATEST, None

    def _aad_map_for(self, context: CryptoContext) -> dict[str, str] | None:
        if not context.aad:
            return None
        return dict(sorted(context.aad.items()))

    @staticmethod
    def _zero(buffer: bytearray | bytes | memoryview) -> None:
        if isinstance(buffer, (bytearray, memoryview)):
            try:
                buffer[:] = b"\x00" * len(buffer)
            except (TypeError, ValueError):
                pass

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException("oci: Secret Provider session is closed")


def _is_not_found(error: BaseException) -> bool:
    """Detect OCI's HTTP 404 not-found variant.

    Mirrors Java's `exception.getStatusCode() == 404`. The
    Python SDK's `BmcException` exposes `.status`; we also
    accept a fallback marker for tests.
    """
    code = getattr(error, "status", None) or getattr(error, "status_code", None)
    if code == _NOT_FOUND_HTTP:
        return True
    return False


__all__ = [
    "OciSecretClient",
    "VaultLike",
    "KmsLike",
    "OciVaultSecret",
    "OciKmsEncryptResponse",
    "OciKmsDecryptResponse",
]
