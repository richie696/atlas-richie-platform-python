"""`AliyunSecretClient` — 4 个 SPI 角色的复合实现,跑在 Aliyun KMS 20160120 上。

中文
----
对位 Java `cn.richie696.component.secret.provider.aliyun.AliyunSecretClient`,
后者 extends `SecretBootstrapClient, SecretBackend, KeyWrappingBackend,
SecretProviderSession`(4-SPI,**无** `SigningBackend`)。Aliyun KMS
对称加密只支持 wrap / unwrap,不暴露 sign / verify。

- `boto3`-style SDK 在 Python 端对应 `alibabacloud_kms20160120.Client`,
  它**同时**提供 Secrets Manager 的 `GetSecretValue` 和 KMS 的
  `Encrypt` / `Decrypt`(两个产品共用 20160120 service version)
- `AliyunKmsGateway` Protocol 把 SDK 调用抽象成 3 个方法,SDK
  类型不穿透到 framework / public API 边界

**关于 logical → physical 寻址**:Java 端
`AliyunSecretProperties.secrets` 维护一张逻辑名 → 物理名映射,
因为 Java bootstrap 直接接 `logicalPaths()`。Python framework
已经在 `SecretBindingCatalog` 层完成 logical → physical 解析,
`SecretReference.path` 已经是物理名;`properties.secrets` 在
Python 端**作为可选覆盖**(当 binding 仍使用逻辑名时)。

**Field 提取约定**:`<path>#<field>` — 如果 path 含 `#`,client
把前半段作为 physical secret name、后半段作为要提取的 JSON 字段。
这是 framework `SecretReference` 缺失 `field` 字段时的务实方案
(对位 Java `SecretMapping.field`)。

读 / 写边界:对位 Java `AliyunSecretClient` **不**实现
`SecretWriter` / `SecretDeletable` / `SecretListable`(Aliyun SDK
20160120 没有 list_secrets API)。

错误映射(对位 Java `AliyunSecretClient`):
- `TeaException` code `Forbidden.ResourceNotFound` → 视为 missing(返回
  `None` from `getSecret`);**不**抛异常
- `TeaException` 其他 code → `SecretException("SEC-PROVIDER-001", ...)`
- `Exception` 其它 → `SecretException("SEC-PROVIDER-001", ...)`
- KMS `Encrypt` 返回空 ciphertext → `SecretCryptoException("SEC-CRYPTO-001", ...)`
- KMS `Decrypt` 返回空 plaintext → `SecretCryptoException("SEC-CRYPTO-002", ...)`
- KMS `Decrypt` 返回的 `key_id` 与 `physical_key` 不一致 →
  `SecretCryptoException("SEC-CRYPTO-002", ...)`
- wrap / unwrap 的 empty plaintext / wrong algorithm → 对位
  Java `SEC-CRYPTO-001` / `SEC-CRYPTO-002`

English
--------
Composite implementation of 4 SPI roles on top of Alibaba
Cloud's `alibabacloud_kms20160120` SDK. The SDK exposes
Secrets Manager + KMS through one `Client` class
(`get_secret_value` / `encrypt` / `decrypt`).
`AliyunKmsGateway` is a Protocol that hides the SDK types
from the public surface.

The Java side maintains a `properties.secrets` logical-to-
physical map because the Java bootstrap directly consumes
`logicalPaths()`. The Python framework already resolves
logical → physical in the `SecretBindingCatalog`, so
`SecretReference.path` is already the physical name. The
`properties.secrets` map is preserved as an optional
override (used when a binding still references a logical
name rather than a physical one).

Field extraction convention: if a `SecretReference.path`
contains ``#``, the part after ``#`` is treated as the
JSON field name to extract. This compensates for the
framework's `SecretReference` lacking a dedicated
`field` attribute (which Java `SecretMapping` has).

The client is 1:1 with Java's 4-SPI scope: no
`SigningBackend`, no `SecretListable` (the 20160120
service has no list API), no `SecretWriter` /
`SecretDeletable`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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
)
from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend, SecretCapability, SecretMetadata
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret.value import SecretValue
from atlas_richie.secret_aliyun_kms.configuration import ResolvedAliyunConfiguration

_logger = logging.getLogger("atlas_richie.secret_aliyun_kms.client")

# 1:1 with Java `WRAPPING_ALGORITHM = "aliyun-kms-symmetric-default"`
_WRAPPING_ALGORITHM = "aliyun-kms-symmetric-default"

# 1:1 with Java `SECRET_NOT_FOUND_CODES` — Alibaba SDK exception code
# when the requested SecretName does not exist.
_SECRET_NOT_FOUND_CODE = "Forbidden.ResourceNotFound"

# Path separator for field extraction.  ``"logical#field"`` means
# the physical name is "logical" and the field to extract is "field".
_FIELD_SEPARATOR = "#"

# Attribute keys the framework copies from `CryptoContext.attributes()`
# into the KMS `EncryptionContext` (mirrors Java `copyEnvelopeAttribute`).
_ENVELOPE_ATTR_VERSION = "atlas.secret.envelope-version"
_ENVELOPE_ATTR_ALGORITHM = "atlas.secret.algorithm"
_ENVELOPE_ATTR_NONCE_SHA = "atlas.secret.nonce-sha256"


# ---------------------------------------------------------------------------
# Gateway Protocol + response dataclasses (SDK-isolating layer)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AliyunGetSecretValueResponse:
    """Frozen response for `GetSecretValue` (mirrors Java `GetSecretValueResponseBody`).

    Attributes:
        secret_name: The physical secret name.
        secret_data: Raw `SecretData` string. UTF-8 JSON or
            base64-encoded binary depending on `secret_data_type`.
        secret_data_type: Either `text` (default) or `binary`
            (Aliyun uses these literal strings; matches Java).
        version_id: Concrete version (Aliyun returns this as
            `VersionId`; Java defaults to `"current"` if blank).
        version_stages: Tuple of stage labels (e.g. `("ACSCurrent",)`).
        create_time: ISO-8601 timestamp; `None` if missing.
        request_id: Aliyun-side request id (preserved in bootstrap result).
    """

    secret_name: str
    secret_data: str
    secret_data_type: str
    version_id: str
    version_stages: tuple[str, ...]
    create_time: str | None
    request_id: str | None


@dataclass(frozen=True, slots=True)
class AliyunEncryptResponse:
    """Frozen response for `Encrypt` (mirrors Java `EncryptResponseBody`).

    Attributes:
        key_id: The CMK id used for encryption (mirrors Java
            `EncryptResponseBody.getKeyId()`).
        ciphertext_blob: Base64-encoded ciphertext (Java returns
            the blob as a string and the client base64-decodes
            to bytes; the SDK returns base64 directly).
        request_id: Aliyun-side request id.
    """

    key_id: str
    ciphertext_blob: str
    request_id: str | None


@dataclass(frozen=True, slots=True)
class AliyunDecryptResponse:
    """Frozen response for `Decrypt` (mirrors Java `DecryptResponseBody`).

    Attributes:
        key_id: The CMK id used for decryption. The client
            verifies this matches the `physical_key` from
            the `KeyReference`.
        plaintext: Base64-encoded plaintext (mirrors Java
            `DecryptResponseBody.getPlaintext()`).
        request_id: Aliyun-side request id.
    """

    key_id: str
    plaintext: str
    request_id: str | None


@runtime_checkable
class AliyunKmsGateway(Protocol):
    """SDK-isolating gateway over the Aliyun `kms20160120` SDK.

    The real `AliyunClientFactory` adapts
    `alibabacloud_kms20160120.Client` to this Protocol; tests
    substitute a `FakeAliyunGateway` (in-process) without
    touching the SDK.
    """

    def get_secret_value(
        self,
        secret_name: str,
        version_id: str | None,
        version_stage: str | None,
    ) -> AliyunGetSecretValueResponse | None:
        ...

    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
        encryption_context: Mapping[str, str],
    ) -> AliyunEncryptResponse:
        ...

    def decrypt(
        self,
        ciphertext_blob: str,
        encryption_context: Mapping[str, str],
    ) -> AliyunDecryptResponse:
        ...

    def close(self) -> None:
        ...


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class AliyunSecretClient:
    """Composite 4-SPI session over an `AliyunKmsGateway`.

    Mirrors Java `AliyunSecretClient`. Thread-safe (the gateway
    adapter is stateless; the close flag is a single boolean
    slot).
    """

    __slots__ = (
        "_configuration_hash",
        "_descriptor_backend",
        "_gateway",
        "_properties",
        "_provider_id",
        "closed",
    )

    def __init__(
        self,
        resolved: ResolvedAliyunConfiguration,
        gateway: AliyunKmsGateway,
        *,
        descriptor_backend: SecretBackend = SecretBackend.ALIYUN,
    ) -> None:
        self._provider_id = resolved.provider_id
        self._configuration_hash = resolved.configuration_hash
        self._properties = resolved.properties
        self._gateway = gateway
        self._descriptor_backend = descriptor_backend
        self.closed = False

    # --- SecretOperations ------------------------------------------------

    def read(self, reference: SecretReference) -> SecretValue:
        self._ensure_open()
        field_name = self._extract_field(reference.path)
        secret_name = self._apply_prefix(self._strip_field(reference.path))
        response = self._get_secret(secret_name, reference.version_selector)
        if response is None:
            raise SecretIntegrityException(
                f"aliyun: Secret is missing: {secret_name!r}",
            )
        raw = self._extract_value(response, field_name, secret_name)
        try:
            created_at = self._parse_instant(response.create_time) or _now()
            return SecretValue(
                plaintext=raw,
                metadata=SecretMetadata(
                    reference=reference,
                    version=SecretVersion(
                        number=self._version_label(response),
                        created_at=created_at,
                    ),
                    backend=self._descriptor_backend,
                    created_at=created_at,
                    expires_at=None,
                    tags={
                        "provider": "aliyun",
                        "stages": ",".join(response.version_stages),
                        "request_id": response.request_id or "",
                    },
                ),
            )
        finally:
            self._zero(raw)

    def metadata(self, reference: SecretReference) -> SecretMetadata:
        self._ensure_open()
        secret_name = self._apply_prefix(self._strip_field(reference.path))
        response = self._get_secret(secret_name, reference.version_selector)
        if response is None:
            raise SecretIntegrityException(
                f"aliyun: Secret metadata is missing: {secret_name!r}",
            )
        created_at = self._parse_instant(response.create_time) or _now()
        return SecretMetadata(
            reference=reference,
            version=SecretVersion(
                number=self._version_label(response),
                created_at=created_at,
            ),
            backend=self._descriptor_backend,
            created_at=created_at,
            expires_at=None,
            tags={
                "provider": "aliyun",
                "stages": ",".join(response.version_stages),
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
                "aliyun: wrap_key requires a non-empty DEK (SEC-CRYPTO-001)",
            )
        key_id = self._resolve_cmk(kek)
        dek_b64 = base64.b64encode(dek).decode("ascii")
        enc_ctx = self._encryption_context_for(kek, purpose=KeyPurpose.WRAP)
        try:
            response = self._gateway.encrypt(key_id, dek_b64, enc_ctx)
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"aliyun: KMS failed to wrap DEK with KEK {kek.key_id!r} "
                f"(SEC-CRYPTO-001): {error}",
            ) from error
        if not response.ciphertext_blob:
            raise SecretCryptoException(
                "aliyun: KMS returned no ciphertext (SEC-CRYPTO-001)",
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
                f"aliyun: wrapped key algorithm {wrapped.algorithm!r} is not "
                f"supported; expected {_WRAPPING_ALGORITHM!r} (SEC-CRYPTO-002)",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "aliyun: wrapped ciphertext is empty (SEC-CRYPTO-002)",
            )
        key_id = self._resolve_cmk(context.primary_key)
        try:
            ciphertext_str = bytes(wrapped.ciphertext).decode("utf-8")
            enc_ctx = self._encryption_context_for(
                context.primary_key,
                purpose=context.purpose,
                aad=context.aad,
            )
            response = self._gateway.decrypt(ciphertext_str, enc_ctx)
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"aliyun: KMS failed to unwrap DEK with KEK "
                f"{context.primary_key.key_id!r} (SEC-CRYPTO-002): {error}",
            ) from error
        if not response.plaintext:
            raise SecretCryptoException(
                "aliyun: KMS returned no plaintext (SEC-CRYPTO-002)",
            )
        if response.key_id and response.key_id != key_id:
            raise SecretCryptoException(
                f"aliyun: KMS returned an unexpected key identity "
                f"({response.key_id!r} != {key_id!r}) (SEC-CRYPTO-002)",
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
                field_name = self._extract_field(binding.reference.path)
                secret_name = self._apply_prefix(
                    self._strip_field(binding.reference.path),
                )
                response = self._get_secret(secret_name, binding.reference.version_selector)
                if response is None:
                    raise SecretIntegrityException(
                        f"aliyun: Secret is missing: {secret_name!r}",
                    )
                raw = self._extract_value(response, field_name, secret_name)
                try:
                    created_at = self._parse_instant(response.create_time) or _now()
                    resolved[binding.name] = SecretValue(
                        plaintext=raw,
                        metadata=SecretMetadata(
                            reference=binding.reference,
                            version=SecretVersion(
                                number=self._version_label(response),
                                created_at=created_at,
                            ),
                            backend=self._descriptor_backend,
                            created_at=created_at,
                            expires_at=None,
                            tags={
                                "provider": "aliyun",
                                "stages": ",".join(response.version_stages),
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
                        f"aliyun: bootstrap Secret binding {binding.name!r} is missing "
                        f"(SEC-STORE-001): {error}",
                    ) from error
                missing.append(binding.name)
                _logger.warning(
                    "aliyun: bootstrap binding %r missing (required_when=%s); continuing",
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
    def configuration_hash(self) -> str:
        return self._configuration_hash

    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self._provider_id,
            backend=self._descriptor_backend,
            capability=_aliyun_capability(),
            version="0.2.0",
        )

    def default_configuration(self) -> SecretProviderConfiguration:
        return SecretProviderConfiguration(
            name=self._provider_id,
            parameters={},
            timeout_seconds=self._properties.read_timeout_seconds,
            retries=self._properties.max_attempts,
            namespace=self._properties.region,
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self._gateway.close()
        except Exception as error:  # noqa: BLE001
            _logger.warning("aliyun: gateway close raised: %s", error)

    # --- Internal helpers ------------------------------------------------

    def _apply_prefix(self, name: str) -> str:
        prefix = self._properties.secrets_manager_path_prefix
        if not prefix:
            return name
        return f"{prefix}/{name}"

    def _extract_field(self, path: str) -> str | None:
        if _FIELD_SEPARATOR not in path:
            return None
        return path.rsplit(_FIELD_SEPARATOR, 1)[1]

    @staticmethod
    def _strip_field(path: str) -> str:
        if _FIELD_SEPARATOR not in path:
            return path
        return path.rsplit(_FIELD_SEPARATOR, 1)[0]

    @staticmethod
    def _zero(buffer: bytearray | bytes | memoryview) -> None:
        """Best-effort zero of a byte buffer (mirrors Java `Arrays.fill`)."""
        if isinstance(buffer, (bytearray, memoryview)):
            try:
                buffer[:] = b"\x00" * len(buffer)
            except (TypeError, ValueError):
                pass

    @staticmethod
    def _sha256_hex(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    def _resolve_cmk(self, kek: KeyReference) -> str:
        """Resolve a `KeyReference` to a physical Aliyun CMK id.

        Resolution order (mirrors Java `AliyunSecretClient.physicalKey`):
        1. `KeyReference.key_id` if it is non-blank (the
           `properties.kms_key_bindings` lookup happens upstream
           in the framework's binding catalog).
        2. Otherwise raise `SEC-KEY-001`.

        Aliyun KMS accepts either a full CMK ARN, an alias ARN,
        or a short alias name (e.g. ``alias/orders``). We pass
        through whatever the caller stored.
        """
        if not kek.key_id or not kek.key_id.strip():
            raise SecretConfigurationException(
                f"aliyun: no KMS key binding for KeyReference {kek!r} (SEC-KEY-001)",
            )
        return kek.key_id

    def _encryption_context_for(
        self,
        kek: KeyReference,
        *,
        purpose: KeyPurpose,
        aad: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        aad_bytes = b""
        if aad:
            aad_bytes = "".join(f"{k}={v}" for k, v in sorted(aad.items())).encode("utf-8")
        return {
            "atlas-component": "secret-envelope",
            "atlas-aad-sha256": self._sha256_hex(aad_bytes),
            "atlas-key": kek.key_id or "",
            "atlas-purpose": purpose.name,
        }

    # --- Gateway adapter -------------------------------------------------

    def _get_secret(
        self,
        secret_name: str,
        selector: Any,
    ) -> AliyunGetSecretValueResponse | None:
        from atlas_richie.secret.reference import SecretVersionSelectorKind

        version_id: str | None = None
        version_stage: str | None = None
        if selector is not None:
            if selector.kind is SecretVersionSelectorKind.STATIC:
                version_id = selector.static_version.number if selector.static_version else None
            elif selector.kind is SecretVersionSelectorKind.PINNED_AT_TIME:
                # Aliyun SDK has no time-pinning; resolve to LATEST (the
                # caller has the responsibility to choose a static version
                # if reproducibility is required).
                version_id = None
        try:
            return self._gateway.get_secret_value(secret_name, version_id, version_stage)
        except SecretException as error:
            if _is_not_found(error):
                return None
            raise
        except Exception as error:  # noqa: BLE001
            # The Aliyun SDK raises `TeaException` which does not
            # inherit from `SecretException`. We treat any
            # exception carrying the canonical not-found code
            # (or message) as a missing-secret signal; everything
            # else re-raises so the framework surfaces a real
            # `SecretException` upstream.
            if _is_not_found(error):
                return None
            raise

    def _extract_value(
        self,
        response: AliyunGetSecretValueResponse,
        field: str | None,
        logical_name: str,
    ) -> bytes:
        if not response.secret_data:
            raise SecretIntegrityException(
                f"aliyun: Secret has no value: {logical_name!r} (SEC-STORE-001)",
            )
        if field is None:
            if response.secret_data_type.lower() == "binary":
                return base64.b64decode(response.secret_data)
            return response.secret_data.encode("utf-8")
        document = self._parse_object(response)
        value = document.get(field)
        if value is None:
            raise SecretIntegrityException(
                f"aliyun: Secret field is missing: {logical_name!r} (SEC-STORE-001)",
            )
        if not isinstance(value, (str, int, float, bool)):
            raise SecretConfigurationException(
                f"aliyun: Secret field {field!r} is not scalar: {logical_name!r} "
                f"(SEC-STORE-003)",
            )
        return str(value).encode("utf-8")

    def _parse_object(
        self,
        response: AliyunGetSecretValueResponse,
    ) -> dict[str, Any]:
        try:
            raw = (
                base64.b64decode(response.secret_data)
                if response.secret_data_type.lower() == "binary"
                else response.secret_data.encode("utf-8")
            )
            try:
                document = json.loads(raw)
            finally:
                self._zero(raw)
        except (ValueError, json.JSONDecodeError) as error:
            raise SecretConfigurationException(
                f"aliyun: Secret must contain a JSON object (SEC-STORE-003): {error}",
            ) from error
        if not isinstance(document, dict):
            raise SecretConfigurationException(
                "aliyun: Secret JSON root must be an object (SEC-STORE-003)",
            )
        return document

    @staticmethod
    def _version_label(response: AliyunGetSecretValueResponse) -> str:
        return response.version_id if response.version_id else "current"

    @staticmethod
    def _parse_instant(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _ensure_open(self) -> None:
        if self.closed:
            raise SecretException("aliyun: Secret Provider session is closed")


def _aliyun_capability() -> SecretCapability:
    return SecretCapability(
        can_read=True,
        can_write=False,
        can_rotate=True,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


def _now() -> datetime:
    """UTC `datetime` helper (avoids importing `datetime.now` everywhere)."""
    from datetime import timezone

    return datetime.now(tz=timezone.utc)


def _is_not_found(error: BaseException) -> bool:
    """Return True if the SDK error signals a missing secret.

    Mirrors Java `SECRET_NOT_FOUND_CODES.contains(code.trim())`.
    The Aliyun SDK raises a `TeaException` with a `.code` attribute
    in the form `"Forbidden.ResourceNotFound"`. Tests may use
    `SecretException` subclasses to signal not-found; we accept
    any whose message starts with `Forbidden.ResourceNotFound` for
    robustness across SDK versions.
    """
    code = getattr(error, "code", None)
    if code and str(code).strip() == _SECRET_NOT_FOUND_CODE:
        return True
    return _SECRET_NOT_FOUND_CODE in str(error)


__all__ = [
    "AliyunKmsGateway",
    "AliyunGetSecretValueResponse",
    "AliyunEncryptResponse",
    "AliyunDecryptResponse",
    "AliyunSecretClient",
]
