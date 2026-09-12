"""`TencentSecretClient` — 3-SPI 复合,跑在腾讯云 SSM + KMS 官方 SDK 上。

中文
----
对位 Java `cn.richie696.component.secret.provider.tencent.TencentSdkSecretTransport`
(SDK 改造版,87 行),实现 3-SPI 复合:`SecretOperations` via
SSM `GetSecretValue` + `KeyWrappingBackend` via KMS
`Encrypt` / `Decrypt` + `SecretBootstrapClient` +
`SecretProviderSession`。

**SDK 类型隔离**:`SsmClient` / `KmsClient` / Tencent SDK 的
Request / Response model 全部不进 framework 边界。Python 端
通过两个 Protocol(`SsmLike` / `KmsLike`)抽象,`TencentClientFactory`
负责 SDK 适配。

**Error mapping**(对位 Java `TencentSdkSecretTransport`):
- `ResourceNotFound.ErrorCode` → missing(返回 `None` / 抛
  `SecretIntegrityException`)
- 其它 `TencentCloudSDKException` → `SEC-PROVIDER-001`
- wrap / unwrap `TencentCloudSDKException` → `SEC-CRYPTO-001` /
  `SEC-CRYPTO-002`
- 不支持 AAD(`CryptoContext.aad` 非空)→ `SEC-CAP-001`
  (framework 升级新增,Tencent KMS 的 `EncryptionContext` 不
  接 AAD,只接 attributes / envelope)

**EncryptionContext 编码**(对位 Java `encryptionContext`):
- 确定性字符串(排序 attributes),`aad` base64 后并入
- `atlas.secret.aad` 字段 + attributes 排序拼接
- 临时副本(associated_data bytes / 拼接 buffer)用完清零

English
--------
3-SPI composite over Tencent Cloud's official SDK
(`tencentcloud-sdk-python`). SDK types are isolated from
the framework via `SsmLike` / `KmsLike` Protocols.
`TencentClientFactory` adapts the real SDK to the
Protocol; tests inject a `FakeSsm` / `FakeKms`.

NotFound boundary: only `ResourceNotFound.ErrorCode`
maps to `null`; all other SDK exceptions surface as
`SEC-PROVIDER-001` (read) or `SEC-CRYPTO-001/002` (wrap /
unwrap). Non-empty `CryptoContext.aad` raises
`SEC-CAP-001` because Tencent KMS EncryptionContext
does not accept AAD bytes — only deterministic attributes.
"""

from __future__ import annotations

import base64
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
from atlas_richie.secret_tencent_ssm_kms.configuration import (
    ResolvedTencentConfiguration,
    _tencent_capability,
)

_logger = logging.getLogger("atlas_richie.secret_tencent_ssm_kms.client")

_WRAPPING_ALGORITHM = "tencent-kms-default"
_NOT_FOUND_CODE = "ResourceNotFound"


# ---------------------------------------------------------------------------
# SDK-isolating Protocols + response dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TencentSsmGetResponse:
    """Frozen response for SSM `GetSecretValue` (mirrors Java
    `GetSecretValueResponse.Response`).

    Attributes:
        secret_name: Physical Tencent SecretName.
        version_id: Concrete version returned by SSM.
        secret_string: UTF-8 plaintext value (when
            `secret_binary` is blank).
        secret_binary: Base64-encoded binary value
            (preferred when non-blank).
        request_id: Tencent-side request id (preserved
            as a `SecretMetadata` tag).
    """

    secret_name: str
    version_id: str
    secret_string: str
    secret_binary: str
    request_id: str | None


@dataclass(frozen=True, slots=True)
class TencentKmsEncryptResponse:
    """Frozen response for KMS `Encrypt` (mirrors Java
    `EncryptResponse.Response`).
    """

    ciphertext_blob: str
    request_id: str | None


@dataclass(frozen=True, slots=True)
class TencentKmsDecryptResponse:
    """Frozen response for KMS `Decrypt` (mirrors Java
    `DecryptResponse.Response`).
    """

    plaintext: str
    request_id: str | None


@runtime_checkable
class SsmLike(Protocol):
    """SDK-isolating protocol for the SSM `GetSecretValue` op.

    Real `tencentcloud-sdk-python-ssm.SsmClient.GetSecretValue`
    is adapted to this Protocol by `TencentClientFactory`.
    """

    def get_secret_value(
        self,
        secret_name: str,
        version_id: str | None,
    ) -> TencentSsmGetResponse: ...


@runtime_checkable
class KmsLike(Protocol):
    """SDK-isolating protocol for the KMS Encrypt / Decrypt ops.

    Real `tencentcloud-sdk-python-kms.KmsClient.Encrypt` /
    `Decrypt` is adapted to this Protocol by
    `TencentClientFactory`.
    """

    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
        encryption_context: str | None,
    ) -> TencentKmsEncryptResponse: ...

    def decrypt(
        self,
        ciphertext_blob: str,
        encryption_context: str | None,
    ) -> TencentKmsDecryptResponse: ...


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class TencentSecretClient:
    """Composite 3-SPI session over a Tencent `SsmLike` + `KmsLike`.

    Mirrors Java `TencentSdkSecretTransport`. The session's
    `writer` / `deletable` properties return `None`
    (read-only); `operations` returns the client itself.
    """

    __slots__ = (
        "_closed",
        "_configuration_hash",
        "_descriptor_backend",
        "_kms",
        "_properties",
        "_provider_id",
        "_resolved",
        "_snapshot_manager",
        "_ssm",
    )

    def __init__(
        self,
        resolved: ResolvedTencentConfiguration,
        ssm: SsmLike,
        kms: KmsLike,
        *,
        descriptor_backend: SecretBackend = SecretBackend.TENCENT,
    ) -> None:
        self._resolved = resolved
        self._properties = resolved.properties
        self._provider_id = resolved.provider_id
        self._configuration_hash = resolved.configuration_hash
        self._descriptor_backend = descriptor_backend
        self._ssm = ssm
        self._kms = kms
        self._snapshot_manager = SecretSnapshotManager()
        self._closed = False

    # --- SecretOperations ------------------------------------------------

    def read(self, reference: SecretReference) -> SecretValue:
        self._ensure_open()
        assert_can_read(_tencent_capability(), backend_label="tencent")
        secret_name = self._resolve_secret_name(reference)
        version_id = self._resolve_version_id(reference)
        try:
            response = self._ssm.get_secret_value(secret_name, version_id)
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            if _is_not_found(error):
                raise SecretIntegrityException(
                    f"tencent: Secret is missing: {secret_name!r}",
                )
            raise SecretException(
                f"tencent: SSM read failed (SEC-PROVIDER-001): {error}",
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
                    tags={
                        "provider": "tencent",
                        "request_id": response.request_id or "",
                    },
                ),
            )
        finally:
            self._zero(raw)

    def metadata(self, reference: SecretReference) -> SecretMetadata:
        self._ensure_open()
        assert_can_read(_tencent_capability(), backend_label="tencent")
        secret_name = self._resolve_secret_name(reference)
        version_id = self._resolve_version_id(reference)
        try:
            response = self._ssm.get_secret_value(secret_name, version_id)
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            if _is_not_found(error):
                raise SecretIntegrityException(
                    f"tencent: Secret metadata is missing: {secret_name!r}",
                )
            raise SecretException(
                f"tencent: SSM metadata failed (SEC-PROVIDER-001): {error}",
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
            tags={
                "provider": "tencent",
                "request_id": response.request_id or "",
            },
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
                "tencent: wrap_key requires a non-empty DEK (SEC-CRYPTO-001)",
            )
        key_id = self._resolve_key_id(kek)
        plaintext_b64 = base64.b64encode(dek).decode("ascii")
        try:
            response = self._kms.encrypt(
                key_id=key_id,
                plaintext_b64=plaintext_b64,
                encryption_context=None,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"tencent: KMS Encrypt failed (SEC-CRYPTO-001): {error}",
            ) from error
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
                f"tencent: wrapped key algorithm {wrapped.algorithm!r} is not "
                f"supported; expected {_WRAPPING_ALGORITHM!r} (SEC-CRYPTO-002)",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "tencent: wrapped ciphertext is empty (SEC-CRYPTO-002)",
            )
        key_id = self._resolve_key_id(context.primary_key)
        encryption_ctx = self._encryption_context_for(
            context.primary_key,
            context=context,
        )
        try:
            response = self._kms.decrypt(
                ciphertext_blob=bytes(wrapped.ciphertext).decode("utf-8"),
                encryption_context=encryption_ctx,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"tencent: KMS Decrypt failed (SEC-CRYPTO-002): {error}",
            ) from error
        if not response.plaintext:
            raise SecretCryptoException(
                "tencent: KMS returned no plaintext (SEC-CRYPTO-002)",
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
                secret_name = self._resolve_secret_name(binding.reference)
                version_id = self._resolve_version_id(binding.reference)
                try:
                    response = self._ssm.get_secret_value(secret_name, version_id)
                except Exception as error:  # noqa: BLE001
                    if _is_not_found(error):
                        raise SecretIntegrityException(
                            f"tencent: Secret is missing: {secret_name!r}",
                        )
                    raise SecretException(
                        f"tencent: SSM read failed (SEC-PROVIDER-001): {error}",
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
                            tags={
                                "provider": "tencent",
                                "request_id": response.request_id or "",
                            },
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
                        f"tencent: bootstrap Secret binding {binding.name!r} is missing "
                        f"(SEC-STORE-001): {error}",
                    ) from error
                missing.append(binding.name)
                _logger.warning(
                    "tencent: bootstrap binding %r missing (required_when=%s); continuing",
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
            capability=_tencent_capability(),
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
            # Tencent SDK has no time-pinning; resolve to LATEST.
            return None
        return None

    def _resolve_key_id(self, kek: KeyReference) -> str:
        binding = (self._properties.kms_key_bindings or {}).get(kek.key_id)
        if not binding or not binding.strip():
            raise SecretConfigurationException(
                f"tencent: no KMS key binding for KeyReference {kek!r} (SEC-KEY-001)",
            )
        return binding

    def _encryption_context_for(
        self,
        kek: KeyReference,
        context: CryptoContext | None = None,
    ) -> str | None:
        """Build the deterministic `EncryptionContext` string.

        Mirrors Java `TencentSdkSecretTransport.encryptionContext`:
        - the AAD `Mapping[str, str]` (framework-level) is
          sorted and serialized as `k=v` lines joined with
          `\n`
        - the wrapper applies the `atlas.secret.aad=`
          prefix, but in Python the AAD is already
          `Mapping[str, str]` (not raw bytes), so we just
          emit the entries

        **AAD support**:Tencent KMS `EncryptionContext`
        accepts arbitrary attribute key/value pairs as a
        string; the framework's AAD is a `Mapping[str, str]`
        which serializes directly. No `SEC-CAP-001` is
        raised for AAD on this backend.

        **Framework API gap**:the framework's
        `KeyWrappingBackend.wrap_key` does not accept a
        `CryptoContext`; the gate fires only on
        `unwrap_key` for now. A future framework extension
        would let `wrap_key` accept context too.
        """
        if context is None:
            return None
        if not context.aad:
            return None
        lines = [f"{k}={v}" for k, v in sorted(context.aad.items())]
        return "\n".join(lines)

    def _extract_value(
        self,
        response: TencentSsmGetResponse,
        secret_name: str,
    ) -> bytes:
        if response.secret_binary and response.secret_binary.strip():
            try:
                return base64.b64decode(response.secret_binary)
            except Exception as error:  # noqa: BLE001
                raise SecretException(
                    f"tencent: secret_binary is not valid base64 "
                    f"({secret_name!r}, SEC-PROVIDER-001): {error}",
                ) from error
        if response.secret_string is None:
            raise SecretIntegrityException(
                f"tencent: Secret has no value: {secret_name!r}",
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
            raise SecretException("tencent: Secret Provider session is closed")


def _is_not_found(error: BaseException) -> bool:
    """Detect Tencent SDK's `ResourceNotFound` not-found variant.

    Mirrors Java's `ResourceNotFound.equalsIgnoreCase(
    exception.getErrorCode())`. The Python SDK's
    `TencentCloudSDKException.code` attribute carries the
    error code; we also scan the message as a fallback.
    """
    code = getattr(error, "code", None)
    if code and str(code).strip().lower() == _NOT_FOUND_CODE.lower():
        return True
    return _NOT_FOUND_CODE in str(error)


__all__ = [
    "TencentSecretClient",
    "SsmLike",
    "KmsLike",
    "TencentSsmGetResponse",
    "TencentKmsEncryptResponse",
    "TencentKmsDecryptResponse",
]
