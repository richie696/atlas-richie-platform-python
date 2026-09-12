"""`HuaweiSecretClient` — 3-SPI 复合,跑在华为云 CSMS + DEW KMS 官方 SDK 上。

中文
----
对位 Java `cn.richie696.component.secret.provider.huawei.HuaweiSdkSecretTransport`
(SDK 改造版,150+ 行),实现 3-SPI 复合:`SecretOperations` via
CSMS `ShowSecretVersion` + `KeyWrappingBackend` via DEW
`EncryptData` / `DecryptData` + `SecretBootstrapClient` +
`SecretProviderSession`。

**SDK 类型隔离**:`CsmsClient` / `KmsClient` / 华为云 SDK
Request / Response model 全部不进 framework 边界。Python 端
通过两个 Protocol(`CsmsLike` / `KmsLike`)抽象,
`HuaweiClientFactory` 负责 SDK 适配。

**Error mapping**(对位 Java `HuaweiSdkSecretTransport`):
- HTTP 404 → missing(返回 `None` / 抛 `SecretIntegrityException`)
- 其它 `ServiceResponseException` → `SEC-PROVIDER-001`
- wrap / unwrap `RuntimeException` → `SEC-CRYPTO-001` /
  `SEC-CRYPTO-002`
- project_id 缺失 → `SEC-BOOT-003`

**AAD 编码**(对位 Java `aad` 方法):华为云 DEW KMS 的
`additionalAuthenticatedData` 字段接 base64 字符串。Python
端 AAD 是 `Mapping[str, str]`,framework 端需要做 base64 +
key-value 编码(此处简化为:把 AAD 字典做确定性 JSON 编码后
base64,作为 additionalAuthenticatedData)。

English
--------
3-SPI composite over Huawei Cloud's official SDK
(`huaweicloud-sdk-python`). SDK types are isolated from
the framework via `CsmsLike` / `KmsLike` Protocols.

NotFound boundary: only HTTP 404 maps to `null`; all
other `ServiceResponseException` surface as
`SEC-PROVIDER-001` (read) or `SEC-CRYPTO-001/002`
(wrap / unwrap). AAD is supported via DEW
`additionalAuthenticatedData` (Base64-encoded).
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

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
from atlas_richie.secret_huawei_csms_kms.configuration import ResolvedHuaweiConfiguration

_logger = logging.getLogger("atlas_richie.secret_huawei_csms_kms.client")

_WRAPPING_ALGORITHM = "huawei-dew-default"
_NOT_FOUND_HTTP = 404


# ---------------------------------------------------------------------------
# SDK-isolating Protocols + response dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HuaweiCsmsGetResponse:
    """Frozen response for CSMS `ShowSecretVersion` (mirrors Java
    `ShowSecretVersionResponse`).

    Attributes:
        secret_name: Physical Huawei SecretName.
        version_id: Concrete version.
        secret_string: UTF-8 plaintext (when `secret_binary` blank).
        secret_binary: Base64-encoded binary (when non-blank).
        create_time: Creation epoch millis (mirrors Java
            `VersionMetadata.getCreateTime()`).
    """

    secret_name: str
    version_id: str
    secret_string: str
    secret_binary: str
    create_time: int | None


@dataclass(frozen=True, slots=True)
class HuaweiKmsEncryptResponse:
    """Frozen response for DEW `EncryptData` (mirrors Java
    `EncryptDataResponse`).
    """

    cipher_text: str


@dataclass(frozen=True, slots=True)
class HuaweiKmsDecryptResponse:
    """Frozen response for DEW `DecryptData` (mirrors Java
    `DecryptDataResponse`).
    """

    plain_text: str
    plain_text_base64: str


@runtime_checkable
class CsmsLike(Protocol):
    def show_secret_version(
        self,
        secret_name: str,
        version_id: str | None,
    ) -> HuaweiCsmsGetResponse: ...


@runtime_checkable
class KmsLike(Protocol):
    def encrypt_data(
        self,
        key_id: str,
        plain_text_b64: str,
        aad_b64: str | None,
    ) -> HuaweiKmsEncryptResponse: ...

    def decrypt_data(
        self,
        cipher_text: str,
        aad_b64: str | None,
    ) -> HuaweiKmsDecryptResponse: ...


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class HuaweiSecretClient:
    """3-SPI composite over Huawei CSMS + DEW KMS."""

    __slots__ = (
        "_closed",
        "_configuration_hash",
        "_csms",
        "_descriptor_backend",
        "_kms",
        "_properties",
        "_provider_id",
        "_resolved",
        "_snapshot_manager",
    )

    def __init__(
        self,
        resolved: ResolvedHuaweiConfiguration,
        csms: CsmsLike,
        kms: KmsLike,
        *,
        descriptor_backend: SecretBackend = SecretBackend.HUAWEI,
    ) -> None:
        self._resolved = resolved
        self._properties = resolved.properties
        self._provider_id = resolved.provider_id
        self._configuration_hash = resolved.configuration_hash
        self._descriptor_backend = descriptor_backend
        self._csms = csms
        self._kms = kms
        self._snapshot_manager = SecretSnapshotManager()
        self._closed = False

    # --- SecretOperations ------------------------------------------------

    def read(self, reference: SecretReference) -> SecretValue:
        self._ensure_open()
        assert_can_read(self._resolved.capability, backend_label="huawei")
        secret_name = self._resolve_secret_name(reference)
        version_id = self._resolve_version_id(reference)
        try:
            response = self._csms.show_secret_version(secret_name, version_id)
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            if _is_not_found(error):
                raise SecretIntegrityException(
                    f"huawei: Secret is missing: {secret_name!r}",
                )
            raise SecretException(
                f"huawei: CSMS read failed (SEC-PROVIDER-001): {error}",
            ) from error
        raw = self._extract_value(response, secret_name)
        try:
            return SecretValue(
                plaintext=raw,
                metadata=SecretMetadata(
                    reference=reference,
                    version=SecretVersion(
                        number=response.version_id or "latest",
                        created_at=datetime.now(tz=timezone.utc),
                    ),
                    backend=self._descriptor_backend,
                    created_at=datetime.now(tz=timezone.utc),
                    expires_at=None,
                    tags={"provider": "huawei"},
                ),
            )
        finally:
            self._zero(raw)

    def metadata(self, reference: SecretReference) -> SecretMetadata:
        self._ensure_open()
        assert_can_read(self._resolved.capability, backend_label="huawei")
        secret_name = self._resolve_secret_name(reference)
        version_id = self._resolve_version_id(reference)
        try:
            response = self._csms.show_secret_version(secret_name, version_id)
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            if _is_not_found(error):
                raise SecretIntegrityException(
                    f"huawei: Secret metadata is missing: {secret_name!r}",
                )
            raise SecretException(
                f"huawei: CSMS metadata failed (SEC-PROVIDER-001): {error}",
            ) from error
        return SecretMetadata(
            reference=reference,
            version=SecretVersion(
                number=response.version_id or "latest",
                created_at=datetime.now(tz=timezone.utc),
            ),
            backend=self._descriptor_backend,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=None,
            tags={"provider": "huawei"},
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
                "huawei: wrap_key requires a non-empty DEK (SEC-CRYPTO-001)",
            )
        key_id = self._resolve_key_id(kek)
        plain_text_b64 = base64.b64encode(dek).decode("ascii")
        try:
            response = self._kms.encrypt_data(
                key_id=key_id,
                plain_text_b64=plain_text_b64,
                aad_b64=None,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"huawei: DEW EncryptData failed (SEC-CRYPTO-001): {error}",
            ) from error
        return WrappedKey(
            kek_reference=kek,
            ciphertext=response.cipher_text.encode("utf-8"),
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
                f"huawei: wrapped key algorithm {wrapped.algorithm!r} is not "
                f"supported; expected {_WRAPPING_ALGORITHM!r} (SEC-CRYPTO-002)",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "huawei: wrapped ciphertext is empty (SEC-CRYPTO-002)",
            )
        key_id = self._resolve_key_id(context.primary_key)
        aad_b64 = self._aad_b64_for(context)
        try:
            response = self._kms.decrypt_data(
                cipher_text=bytes(wrapped.ciphertext).decode("utf-8"),
                aad_b64=aad_b64,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"huawei: DEW DecryptData failed (SEC-CRYPTO-002): {error}",
            ) from error
        if response.plain_text_base64:
            return base64.b64decode(response.plain_text_base64)
        if response.plain_text:
            return response.plain_text.encode("utf-8")
        raise SecretCryptoException(
            "huawei: DEW returned no plaintext (SEC-CRYPTO-002)",
        )

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
                secret_name = self._resolve_secret_name(binding.reference)
                version_id = self._resolve_version_id(binding.reference)
                try:
                    response = self._csms.show_secret_version(secret_name, version_id)
                except Exception as error:  # noqa: BLE001
                    if _is_not_found(error):
                        raise SecretIntegrityException(
                            f"huawei: Secret is missing: {secret_name!r}",
                        )
                    raise SecretException(
                        f"huawei: CSMS read failed (SEC-PROVIDER-001): {error}",
                    ) from error
                raw = self._extract_value(response, secret_name)
                try:
                    resolved[binding.name] = SecretValue(
                        plaintext=raw,
                        metadata=SecretMetadata(
                            reference=binding.reference,
                            version=SecretVersion(
                                number=response.version_id or "latest",
                                created_at=datetime.now(tz=timezone.utc),
                            ),
                            backend=self._descriptor_backend,
                            created_at=datetime.now(tz=timezone.utc),
                            expires_at=None,
                            tags={"provider": "huawei"},
                        ),
                    )
                finally:
                    self._zero(raw)
            except SecretIntegrityException as error:
                if binding.required_when in (
                    RequiredWhen.STARTUP,
                    RequiredWhen.PRODUCTION_ONLY,
                ):
                    raise SecretException(
                        f"huawei: bootstrap Secret binding {binding.name!r} is missing "
                        f"(SEC-STORE-001): {error}",
                    ) from error
                missing.append(binding.name)
                _logger.warning(
                    "huawei: bootstrap binding %r missing (required_when=%s); continuing",
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

    def _resolve_secret_name(self, reference: SecretReference) -> str:
        mapping = (self._properties.secrets or {}).get(reference.path)
        if mapping:
            return mapping
        return reference.path

    def _resolve_version_id(self, reference: SecretReference) -> str | None:
        selector = reference.version_selector
        if selector.kind is SecretVersionSelectorKind.STATIC and selector.static_version:
            return str(selector.static_version.number)
        if selector.kind is SecretVersionSelectorKind.PINNED_AT_TIME:
            return None
        return None

    def _resolve_key_id(self, kek: KeyReference) -> str:
        binding = (self._properties.kms_key_bindings or {}).get(kek.key_id)
        if not binding or not binding.strip():
            raise SecretConfigurationException(
                f"huawei: no KMS key binding for KeyReference {kek!r} (SEC-KEY-001)",
            )
        return binding

    def _aad_b64_for(self, context: CryptoContext) -> str | None:
        """Encode `CryptoContext.aad` (framework-level Mapping) to a
        base64 string suitable for Huawei DEW
        `additionalAuthenticatedData`.
        """
        if not context.aad:
            return None
        canonical = json.dumps(
            dict(sorted(context.aad.items())),
            separators=(",", ":"),
        )
        return base64.b64encode(canonical.encode("utf-8")).decode("ascii")

    def _extract_value(
        self,
        response: HuaweiCsmsGetResponse,
        secret_name: str,
    ) -> bytes:
        if response.secret_binary and response.secret_binary.strip():
            try:
                return base64.b64decode(response.secret_binary)
            except Exception as error:  # noqa: BLE001
                raise SecretException(
                    f"huawei: secret_binary is not valid base64 "
                    f"({secret_name!r}, SEC-PROVIDER-001): {error}",
                ) from error
        if response.secret_string is None:
            raise SecretIntegrityException(
                f"huawei: Secret has no value: {secret_name!r}",
            )
        return response.secret_string.encode("utf-8")

    @staticmethod
    def _zero(buffer: bytearray | bytes | memoryview) -> None:
        if isinstance(buffer, (bytearray, memoryview)):
            try:
                buffer[:] = b"\x00" * len(buffer)
            except (TypeError, ValueError):
                pass

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException("huawei: Secret Provider session is closed")


def _is_not_found(error: BaseException) -> bool:
    """Detect Huawei's HTTP 404 not-found variant.

    Mirrors Java's `exception.getHttpStatusCode() == 404`.
    The Python SDK's `ServiceResponseException` exposes
    `.http_status_code`; we also accept a fallback marker
    for tests.
    """
    code = getattr(error, "http_status_code", None)
    if code == _NOT_FOUND_HTTP:
        return True
    code = getattr(error, "status_code", None)
    if code == _NOT_FOUND_HTTP:
        return True
    return False


__all__ = [
    "HuaweiSecretClient",
    "CsmsLike",
    "KmsLike",
    "HuaweiCsmsGetResponse",
    "HuaweiKmsEncryptResponse",
    "HuaweiKmsDecryptResponse",
]
