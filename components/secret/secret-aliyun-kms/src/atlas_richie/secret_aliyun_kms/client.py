"""`AliyunSecretClient` — 4-SPI composite over Alibaba Secrets Manager + KMS。

中文
----
对位 Java `cn.richie696.component.secret.provider.aliyun.AliyunSecretClient`。
Python 端用 1 个 `KmsClient`(Secrets Manager 读 + KMS 加解密都在
`kms20160120` endpoint 上;Aliyun SDK 统一入口),由一个 `AliyunKmsGateway`
Protocol 适配:

- `get_secret_value` → Secrets Manager `GetSecretValue`(`VersionStage`
  默认 `ACSCurrent`)
- `encrypt` / `decrypt` → KMS `Encrypt` / `Decrypt`(server-side 对称
  wrap,`EncryptionContext` 携带 AAD binding)

`SecretBackend` → `SecretOperations` 名字对位 Python Protocol 体系;
`KeyWrappingBackend` duck-typed(框架 `crypto/key.py` 的 `WrappedKey`
+ `CryptoContext`);`SecretBootstrapClient` 框架入口 +
`load(request, missing_policy)` 高阶入口(对位 Java `load(...)` 完整
逻辑:JSON 解析 + 递归 flatten + 冲突检测)。

**不**实现:

- `SigningBackend`(Aliyun 对称 KMS 无 sign / verify;Java 同)
- `SecretWriter` / `SecretDeletable` / `SecretListable`(`can_list=False`)

加密上下文(对位 Java `AliyunSecretClient.encryptionContext(...)`):

- `atlas-component` = provider name
- `atlas-aad-sha256` = hex SHA-256 of `CryptoContext.aad` bytes
- `atlas-key` = `KeyReference.key_id`
- `atlas-version` = `0.2.0`
- `atlas-purpose` = `CryptoContext.purpose.name()`
- 可选:`atlas-envelope-version` / `atlas-algorithm` /
  `atlas-nonce-sha256`,从 `context.aad` 读

错误映射(对位 Java `AliyunSecretClient.mapError(...)`):

- `TeaException.code == "Forbidden.ResourceNotFound"` →
  `SecretIntegrityException`(404 等价;由 facade 翻译成
  "missing")
- 其它 `TeaException` / `Exception` → `SecretException("SEC-PROVIDER-001", ...)`

`MissingPolicy` 是 aliyun-specific enum(对位 Java
`BootstrapSecretProperties.MissingPolicy`),控制 `load(...)` 在某条
secret 物理不存在时的行为:

- `MissingPolicy.FAIL`(默认)— 抛 `SecretBootstrapException("SEC-STORE-001")`
- `MissingPolicy.LOCAL` — 静默跳过(对位 Java
  `MissingPolicy.LOCAL`,允许 partial bootstrap)

English
--------
Composite client over Alibaba SDK. Mirrors Java's narrower 4-SPI
scope (no signing / no listing). The Alibaba SDK is reached via the
internal `AliyunKmsGateway` Protocol; this client never imports the
SDK at module top level, so unit tests can drive it through a
`FakeAliyunGateway` without installing Alibaba SDK packages.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol, runtime_checkable

from atlas_richie.secret.bootstrap.catalog import RequiredWhen
from atlas_richie.secret.bootstrap.spi import (
    SecretBootstrapClient,
    SecretBootstrapContext,
    SecretBootstrapRequest,
    SecretBootstrapResult,
)
from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyReference,
    WrappedKey,
)
from atlas_richie.secret.errors import (
    SecretBootstrapException,
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
from atlas_richie.secret.value import DestroyableSecretValue, SecretValue

from atlas_richie.secret_aliyun_kms.configuration import ResolvedAliyunConfiguration

_logger = logging.getLogger("atlas_richie.secret_aliyun_kms.client")

# 1:1 with Java `AliyunSecretClient.WRAPPING_ALGORITHM`
_WRAPPING_ALGORITHM = "aliyun-kms-symmetric-default"

# Alibaba Secrets Manager current version stage. Mirrors Java
# `AliyunSecretClient.ACSCurrent` (the alias Alibaba attaches to
# the most recent version when staging is enabled).
_ACSCURRENT = "ACSCurrent"

# Secret data type constants from the Alibaba SDK. We only use the
# string form so the public surface stays SDK-free.
_SECRET_DATA_TYPE_TEXT = "Text"
_SECRET_DATA_TYPE_BINARY = "Binary"

# Vendor code for a "not found" response on the Alibaba KMS / SM
# service. The Python SDK surfaces this via `TeaException.code`.
_ALIYUN_CODE_NOT_FOUND = "Forbidden.ResourceNotFound"


# ---------------------------------------------------------------------------
# MissingPolicy (aliyun-specific)
# ---------------------------------------------------------------------------


class MissingPolicy(StrEnum):
    """How `load(request, missing_policy)` treats a missing secret path.

    Mirrors Java `BootstrapSecretProperties.MissingPolicy`:
    - `FAIL` — raise `SecretBootstrapException("SEC-STORE-001")` when
      any logical path does not resolve. Default.
    - `LOCAL` — silently skip the missing path. The merged result
      simply omits keys that would have come from it.
    """

    FAIL = "fail"
    LOCAL = "local"


# ---------------------------------------------------------------------------
# AliyunKmsGateway Protocol + frozen response dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AliyunGetSecretValueResponse:
    """Mirror of Alibaba SDK's `GetSecretValueResponse`.

    Defined as a frozen dataclass so the public surface stays
    SDK-free; the real `AliyunClientFactory` adapter translates the
    SDK's mutable model into this shape.

    Attributes:
        secret_name: Physical name of the secret.
        secret_data: The secret payload. For `Text` data types this
            is the raw string; for `Binary` data types it is the
            base64-encoded byte string (matching the SDK's wire
            format).
        secret_data_type: One of `"Text"` / `"Binary"`. The client
            uses this to decide between `bytes(text, "utf-8")` and
            `base64.b64decode(...)`.
        version_id: Opaque version id assigned by Alibaba.
        version_stages: Tuple of stage labels attached to this
            version (e.g. `("ACSCurrent", "ACSPrevious")`).
        create_time: UTC creation time as reported by Alibaba.
            `None` when the backend did not return one.
        request_id: Vendor request id for diagnostics.
    """

    secret_name: str
    secret_data: str
    secret_data_type: str
    version_id: str
    version_stages: tuple[str, ...] = ()
    create_time: datetime | None = None
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class AliyunEncryptResponse:
    """Mirror of Alibaba SDK's `EncryptResponse`."""

    ciphertext_blob: str  # base64-encoded ciphertext
    key_id: str
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class AliyunDecryptResponse:
    """Mirror of Alibaba SDK's `DecryptResponse`."""

    plaintext: str  # base64-encoded plaintext
    key_id: str
    request_id: str = ""


@runtime_checkable
class AliyunKmsGateway(Protocol):
    """The single integration boundary between this client and the Alibaba SDK.

    The real `AliyunClientFactory` returns an adapter that wraps the
    SDK's `KmsClient` and translates `get_secret_value_with_options` /
    `encrypt_with_options` / `decrypt_with_options` into the three
    protocol methods. Unit tests provide a `FakeAliyunGateway` that
    returns canned responses without touching the network.
    """

    def get_secret_value(
        self,
        secret_name: str,
        version_id: str | None,
        version_stage: str | None,
    ) -> AliyunGetSecretValueResponse | None:
        """Return the requested secret value, or `None` if missing.

        The vendor may surface "not found" as either a raised
        `TeaException(code=Forbidden.ResourceNotFound)` or a `None`
        response (depending on SDK version). The adapter
        normalises both to `None`; the client treats `None` as a
        missing secret.
        """
        ...

    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
        encryption_context: Mapping[str, str],
    ) -> AliyunEncryptResponse:
        """Server-side symmetric wrap. `plaintext_b64` is base64."""
        ...

    def decrypt(
        self,
        ciphertext_blob: str,
        encryption_context: Mapping[str, str],
    ) -> AliyunDecryptResponse:
        """Server-side symmetric unwrap. `ciphertext_blob` is base64.
        Response's `plaintext` is base64."""
        ...

    def close(self) -> None:
        """Release the underlying SDK client. Idempotent."""
        ...


# ---------------------------------------------------------------------------
# AliyunBootstrapLoadResult — the spec's rich `load(...)` return shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AliyunBootstrapLoadResult:
    """Output of `AliyunSecretClient.load(request, missing_policy)`.

    Mirrors Java `BootstrapResult` (NOT the framework's narrower
    `SecretBootstrapResult`):

    Attributes:
        provider_id: The provider id that produced this result.
        version_digest: SHA-256 hex digest of the sorted
            `(version_id, value_sha256)` pairs across all
            successfully loaded secrets.
        paths_loaded: Comma-joined string of logical paths that
            were successfully loaded.
        loaded_at: UTC time the load finished.
        merged: Flat key/value map of the merged (flattened) secret
            contents. Each binding contributes a sub-map whose keys
            are prefixed with `<binding_name>.` (e.g. `db.username`)
            to avoid collisions across bindings.
        binding_names: Tuple of binding names that were successfully
            loaded. The framework's `bootstrap(...)` uses this to
            decide which bindings ended up in the `missing` tuple.
        last_request_id: Vendor request id from the most recent
            secret fetch (useful for diagnostics).
    """

    provider_id: str
    version_digest: str
    paths_loaded: str
    loaded_at: datetime
    merged: Mapping[str, str]
    binding_names: tuple[str, ...]
    last_request_id: str


# ---------------------------------------------------------------------------
# AliyunSecretClient
# ---------------------------------------------------------------------------


class AliyunSecretClient(
    SecretOperations,
    SecretBootstrapClient,
    SecretProviderSession,
):
    """Composite secret client for Alibaba Cloud (Secrets Manager + KMS).

    Implements 4 SPI roles:

    - `SecretOperations` — Alibaba Secrets Manager reads
    - `KeyWrappingBackend` (duck-typed) — Alibaba KMS `Encrypt` /
      `Decrypt` (symmetric only; no signing)
    - `SecretBootstrapClient` — startup-time batch read
    - `SecretProviderSession` — provider lifecycle

    Does **not** implement `SecretWriter` / `SecretDeletable` /
    `SecretListable` — matches Java's narrower 4-SPI scope.

    Constructor parameters:
    - `resolved`: immutable `ResolvedAliyunConfiguration`
    - `gateway`: any object that satisfies the `AliyunKmsGateway`
      Protocol (real `AliyunSdkGateway` in production,
      `FakeAliyunGateway` in unit tests)
    - `snapshot_manager`: optional `SecretSnapshotManager`
    - `close_action`: optional callable invoked from `close()`
    """

    __slots__ = (
        "_closed",
        "_close_action",
        "_gateway",
        "_resolved",
        "_snapshot_manager",
    )

    def __init__(
        self,
        resolved: ResolvedAliyunConfiguration,
        gateway: AliyunKmsGateway,
        *,
        snapshot_manager: SecretSnapshotManager | None = None,
        close_action: Callable[[], None] | None = None,
    ) -> None:
        self._resolved = resolved
        self._gateway = gateway
        self._snapshot_manager = snapshot_manager or SecretSnapshotManager()
        self._close_action = close_action
        self._closed = False

    # --- SecretProviderSession Protocol ---------------------------------

    @property
    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self._resolved.provider_id,
            backend=SecretBackend.ALIYUN,
            capability=self._resolved.capability,
            version="0.2.0",
        )

    @property
    def configuration(self) -> SecretProviderConfiguration:
        properties = self._resolved.properties
        parameters: dict[str, str] = {
            "region": properties.region,
        }
        if properties.endpoint:
            parameters["endpoint"] = properties.endpoint
        if properties.ca_file:
            parameters["ca_file"] = properties.ca_file
        if properties.secrets_manager_path_prefix:
            parameters["secrets_manager_path_prefix"] = properties.secrets_manager_path_prefix
        return SecretProviderConfiguration(
            name=self._resolved.provider_id,
            parameters=parameters,
            timeout_seconds=properties.read_timeout_seconds,
            retries=properties.max_attempts,
            namespace=properties.region,
        )

    @property
    def operations(self) -> SecretOperations:
        return self

    @property
    def writer(self):  # type: ignore[override]
        return None

    @property
    def deletable(self):  # type: ignore[override]
        return None

    @property
    def signing(self):
        # Mirrors Java: Alibaba symmetric KMS does not expose
        # sign / verify. Returning `None` makes the absence
        # explicit to `list_capability(session)`.
        return None

    @property
    def snapshot_manager(self) -> SecretSnapshotManager:
        return self._snapshot_manager

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._gateway.close()
        except Exception:  # noqa: BLE001
            _logger.exception(
                "aliyun: error during gateway.close() for provider %r",
                self._resolved.provider_id,
            )
        if self._close_action is None:
            return
        try:
            self._close_action()
        except Exception:  # noqa: BLE001
            _logger.exception(
                "aliyun: error during close_action for provider %r",
                self._resolved.provider_id,
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException(
                f"aliyun: provider session {self._resolved.provider_id!r} is closed",
            )

    # --- SecretOperations Protocol --------------------------------------

    def get(self, reference: SecretReference) -> SecretValue:
        self._ensure_open()
        # Delegate to `read(...)` (which returns a `DestroyableSecretValue`)
        # so the intermediate buffer lifecycle is consistent with the
        # spec's "Zero intermediate buffers" rule. We immediately
        # destroy the wrapper after extracting the `SecretValue` to
        # ensure the framework's `get(...)` contract still returns a
        # plain `SecretValue` without exposing the wrapper.
        handle = self.read(reference)
        try:
            value = handle.value
        finally:
            handle.destroy()
        return value

    def read(self, reference: SecretReference) -> DestroyableSecretValue:
        """Read a secret and return a `DestroyableSecretValue` wrapper.

        Mirrors Java `AliyunSecretClient.read(reference)`. The wrapper
        is the caller's responsibility: use it as a context manager
        or call `destroy()` explicitly so the plaintext bytes are
        zeroed once the caller no longer needs them.
        """
        self._ensure_open()
        version = self._resolve_version(reference)
        response = self._read_secret(reference, version_id=version, version_stage=None)
        if response is None:
            raise SecretIntegrityException(
                f"SEC-PROVIDER-001 aliyun: secret {reference.path!r} not found",
            )
        value = self._build_value(reference, response)
        return DestroyableSecretValue(value)

    def get_version(
        self,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        self._ensure_open()
        response = self._read_secret(reference, version_id=version.number, version_stage=None)
        if response is None:
            raise SecretIntegrityException(
                f"SEC-PROVIDER-001 aliyun: secret {reference.path!r} version {version.number!r} not found",
            )
        return self._build_value(reference, response)

    def get_metadata(self, reference: SecretReference) -> SecretMetadata:
        self._ensure_open()
        response = self._read_secret(reference, version_id=None, version_stage=None)
        if response is None:
            raise SecretIntegrityException(
                f"SEC-PROVIDER-001 aliyun: secret {reference.path!r} not found",
            )
        return self._build_metadata(reference, response)

    def exists(self, reference: SecretReference) -> bool:
        self._ensure_open()
        try:
            response = self._read_secret(reference, version_id=None, version_stage=None)
        except SecretException:
            return False
        return response is not None

    # --- KeyWrappingBackend (duck-typed) --------------------------------

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
                "SEC-CRYPTO-001 aliyun: wrap_key requires a non-empty DEK",
            )
        physical_key_id = self._physical_key_id(kek)
        plaintext_b64 = base64.b64encode(dek).decode("ascii")
        encryption_context = self._encryption_context(
            reference=kek,
            context=CryptoContext(primary_key=kek, purpose=self._purpose_for(kek)),
        )
        try:
            response = self._gateway.encrypt(
                key_id=physical_key_id,
                plaintext_b64=plaintext_b64,
                encryption_context=encryption_context,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._map_sdk_error("wrap_key", kek, error) from error
        # The Alibaba SDK returns ciphertext as a base64 string. Decode
        # to bytes so the framework's `WrappedKey.ciphertext` (which is
        # `bytes`) holds a portable representation.
        ciphertext = base64.b64decode(response.ciphertext_blob)
        return WrappedKey(
            kek_reference=kek,
            ciphertext=ciphertext,
            algorithm=_WRAPPING_ALGORITHM,
            nonce=None,
            aad=encryption_context,
        )

    def unwrap_key(
        self,
        wrapped: WrappedKey,
        context: CryptoContext,
    ) -> bytes:
        self._ensure_open()
        if wrapped.algorithm != _WRAPPING_ALGORITHM:
            raise SecretCryptoException(
                f"SEC-CRYPTO-002 aliyun: cannot unwrap a key with algorithm "
                f"{wrapped.algorithm!r}; expected {_WRAPPING_ALGORITHM!r}",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "SEC-CRYPTO-002 aliyun: wrapped ciphertext is empty",
            )
        physical_key_id = self._physical_key_id(context.primary_key)
        encryption_context = self._encryption_context(
            reference=context.primary_key,
            context=context,
        )
        try:
            response = self._gateway.decrypt(
                ciphertext_blob=base64.b64encode(wrapped.ciphertext).decode("ascii"),
                encryption_context=encryption_context,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._map_sdk_error("unwrap_key", context.primary_key, error) from error
        if response.key_id and response.key_id != physical_key_id:
            raise SecretCryptoException(
                f"SEC-CRYPTO-002 aliyun: decrypt returned key_id {response.key_id!r} "
                f"but the expected physical key is {physical_key_id!r}",
            )
        try:
            return base64.b64decode(response.plaintext)
        except (ValueError, TypeError) as error:
            raise SecretCryptoException(
                "SEC-CRYPTO-002 aliyun: decrypt returned non-base64 plaintext",
            ) from error

    # --- SecretBootstrapClient Protocol --------------------------------

    def bootstrap(
        self,
        request: SecretBootstrapRequest,
        context: SecretBootstrapContext,
    ) -> SecretBootstrapResult:
        """Framework entry. Iterates the catalog and resolves each
        binding via `self.get(binding.reference)`.

        Per-binding `required_when` policy:

        - `RequiredWhen.STARTUP` — raise `SecretException("SEC-STORE-001")`
          when the binding cannot be resolved.
        - `RequiredWhen.LAZY` / `OPTIONAL` / `PRODUCTION_ONLY` — add
          the binding name to `missing` instead of raising.

        Callers that need the rich JSON-flatten behaviour should
        invoke `load(request, missing_policy=...)` directly.
        """
        self._ensure_open()
        started_at = context.now
        resolved: dict[str, SecretValue] = {}
        missing: list[str] = []
        for binding in request.catalog.bindings:
            try:
                resolved[binding.name] = self.get(binding.reference)
            except SecretIntegrityException as error:
                if binding.required_when is RequiredWhen.STARTUP:
                    raise SecretException(
                        f"SEC-STORE-001 aliyun: bootstrap binding "
                        f"{binding.name!r} is required at startup but "
                        f"could not be resolved: {error}",
                    ) from error
                _logger.debug(
                    "aliyun: bootstrap binding %r missing "
                    "(required_when=%s); continuing",
                    binding.name,
                    binding.required_when.value,
                )
                missing.append(binding.name)
        return SecretBootstrapResult(
            resolved=resolved,
            missing=tuple(missing),
            started_at=started_at,
            finished_at=context.now,
        )

    # --- Spec's high-level `load(...)` ---------------------------------

    def load(
        self,
        request: SecretBootstrapRequest,
        *,
        missing_policy: MissingPolicy = MissingPolicy.FAIL,
    ) -> AliyunBootstrapLoadResult:
        """Read every binding in `request.catalog` and merge into one map.

        Mirrors Java `AliyunSecretBootstrapProviderFactory.load(...)`:
        1. For each binding, resolve the physical secret via
           `self._read_secret(...)`.
        2. If missing:
           - `MissingPolicy.FAIL` → raise
             `SecretBootstrapException("SEC-STORE-001")`.
           - `MissingPolicy.LOCAL` → silently skip.
        3. If present, parse the value as JSON when possible and
           flatten it (recursive dot-notation for dicts, `[i]`
           for lists). The flatten root is the binding's `name`,
           so the merged map keys are namespaced by binding
           (e.g. `db.username` for a binding named `db`).
        4. Merge with `merge_without_ambiguity(...)`; raise
           `SecretBootstrapException("SEC-STORE-003")` on a
           conflicting key.
        5. Return a rich `AliyunBootstrapLoadResult` carrying the
           merged map + a SHA-256 digest of `(version_id,
           value_sha256)` pairs (mirrors Java's `digestVersions`).
        """
        self._ensure_open()
        merged: dict[str, str] = {}
        version_pairs: list[tuple[str, str]] = []
        paths_loaded: list[str] = []
        binding_names: list[str] = []
        last_request_id = ""
        for binding in request.catalog.bindings:
            response = self._read_secret(binding.reference, version_id=None, version_stage=_ACSCURRENT)
            if response is None:
                if missing_policy is MissingPolicy.FAIL:
                    raise SecretBootstrapException(
                        f"SEC-STORE-001 aliyun: bootstrap binding {binding.name!r} "
                        f"(path={binding.reference.path!r}) is missing",
                    )
                _logger.debug(
                    "aliyun: bootstrap binding %r missing (MissingPolicy.LOCAL); skipping",
                    binding.name,
                )
                continue
            if response.request_id:
                last_request_id = response.request_id
            document = self._parse_for_load(response)
            # Flatten with no binding-name prefix so that two bindings
            # writing the same key (e.g. `db.password`) conflict at the
            # top level — this is what `merge_without_ambiguity` is
            # designed to detect.
            flat = self._flatten(document, prefix="")
            self._merge_without_ambiguity(merged, flat, binding_name=binding.name)
            version_pairs.append((response.version_id, self._value_sha256(response.secret_data)))
            paths_loaded.append(binding.reference.path)
            binding_names.append(binding.name)
        version_digest = self._digest_versions(version_pairs)
        return AliyunBootstrapLoadResult(
            provider_id=self._resolved.provider_id,
            version_digest=version_digest,
            paths_loaded=", ".join(paths_loaded),
            loaded_at=datetime.now(tz=timezone.utc),
            merged=merged,
            binding_names=tuple(binding_names),
            last_request_id=last_request_id,
        )

    # --- Internal: SecretOperations read path ---------------------------

    def _read_secret(
        self,
        reference: SecretReference,
        *,
        version_id: str | None,
        version_stage: str | None,
    ) -> AliyunGetSecretValueResponse | None:
        physical_name = self._resolve_physical_secret_name(reference)
        try:
            return self._gateway.get_secret_value(
                secret_name=physical_name,
                version_id=version_id,
                version_stage=version_stage,
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            code = self._extract_sdk_code(error)
            if code == _ALIYUN_CODE_NOT_FOUND:
                return None
            raise self._map_sdk_error("read", reference, error) from error

    def _resolve_physical_secret_name(self, reference: SecretReference) -> str:
        """Map a logical `SecretReference.path` to a physical Secrets
        Manager name, using `properties.secrets` first and falling
        back to `<path_prefix>/atlas-richie/<env>/<app>/runtime/<logical>`.
        """
        properties = self._resolved.properties
        mapping = properties.secrets.get(reference.path)
        if mapping is not None:
            return mapping.secret_name
        # Fall back: build the canonical path. Java side hardcodes
        # `atlas-richie/<env>/<app>/runtime`; Python keeps the same
        # shape using `reference.path` as `<app>` and the framework
        # `request.environment` (when available) as `<env>`.
        prefix = properties.secrets_manager_path_prefix
        if prefix:
            return f"{prefix}/atlas-richie/{self._default_environment()}/{reference.path}/runtime"
        return f"atlas-richie/{self._default_environment()}/{reference.path}/runtime"

    @staticmethod
    def _default_environment() -> str:
        # Without a real `SecretBootstrapContext` we cannot know the
        # active environment. Use the conventional ``"default"``
        # placeholder so the physical name is stable in tests and
        # in callers that drive `load(...)` directly.
        return "default"

    def _resolve_version(self, reference: SecretReference) -> str | None:
        selector = reference.version_selector
        if selector.kind is SecretVersionSelectorKind.STATIC and selector.static_version is not None:
            return selector.static_version.number
        return None  # LATEST / PINNED_AT_TIME → use the current stage

    def _build_value(
        self,
        reference: SecretReference,
        response: AliyunGetSecretValueResponse,
    ) -> SecretValue:
        plaintext = self._decode_secret_data(response)
        mapping = self._resolved.properties.secrets.get(reference.path)
        if mapping is not None and mapping.field is not None:
            plaintext = self._extract_json_field(plaintext, mapping.field, reference.path)
        metadata = self._build_metadata(reference, response)
        return SecretValue(plaintext=plaintext, metadata=metadata)

    def _build_metadata(
        self,
        reference: SecretReference,
        response: AliyunGetSecretValueResponse,
    ) -> SecretMetadata:
        created_at = response.create_time or datetime.now(tz=timezone.utc)
        tags: dict[str, str] = {
            "provider": "aliyun",
            "stages": ",".join(response.version_stages),
        }
        if self._resolved.properties.region:
            tags["region"] = self._resolved.properties.region
        return SecretMetadata(
            reference=reference,
            version=SecretVersion(number=response.version_id, created_at=created_at),
            backend=SecretBackend.ALIYUN,
            created_at=created_at,
            expires_at=None,
            tags=tags,
        )

    @staticmethod
    def _decode_secret_data(response: AliyunGetSecretValueResponse) -> bytes:
        """Decode the wire `SecretData` into raw plaintext bytes.

        - `Text` payloads are UTF-8 strings; we encode to bytes so
          the framework's `SecretValue.plaintext: bytes` shape is
          consistent.
        - `Binary` payloads are base64-encoded byte strings; we
          decode to the original byte content.
        """
        if response.secret_data_type == _SECRET_DATA_TYPE_BINARY:
            try:
                return base64.b64decode(response.secret_data, validate=False)
            except (ValueError, TypeError) as error:
                raise SecretException(
                    f"SEC-PROVIDER-001 aliyun: secret {response.secret_name!r} "
                    "is marked Binary but its data is not valid base64",
                ) from error
        if response.secret_data_type == _SECRET_DATA_TYPE_TEXT:
            return response.secret_data.encode("utf-8")
        # Unknown data type — treat as text and let the caller fail
        # downstream if the encoding is wrong.
        return response.secret_data.encode("utf-8", errors="replace")

    @classmethod
    def _parse_for_load(cls, response: AliyunGetSecretValueResponse) -> object:
        """Decode + try-JSON-parse a `GetSecretValue` response for `load(...)`.

        Mirrors Java's `AliyunSecretBootstrapProviderFactory.parse(...)`:
        - Decode the wire data to raw bytes (handles Binary vs Text).
        - Attempt `json.loads(...)` on the UTF-8 string. If the value
          is not JSON, fall back to a `str` so flatten produces a
          single entry keyed by the binding name.
        - Non-`dict` / non-`list` JSON scalars (string, number, bool)
          are returned as the decoded Python value so the flatten
          step emits one entry per scalar.
        """
        raw = cls._decode_secret_data(response)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text

    def _extract_json_field(
        self,
        plaintext: bytes,
        field: str,
        logical_name: str,
    ) -> bytes:
        try:
            document = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SecretException(
                f"SEC-PROVIDER-001 aliyun: secret {logical_name!r} field {field!r} "
                "requires a JSON document but the stored value is not JSON",
            ) from error
        if not isinstance(document, dict):
            raise SecretException(
                f"SEC-PROVIDER-001 aliyun: secret {logical_name!r} field {field!r} "
                "requires a JSON object at the top level",
            )
        if field not in document:
            raise SecretException(
                f"SEC-PROVIDER-001 aliyun: secret {logical_name!r} has no field {field!r}",
            )
        value = document[field]
        if not isinstance(value, (str, int, float, bool)) or isinstance(value, bool):
            # Non-scalar (dict / list) → SEC-STORE-003 (data conflict).
            # Booleans are technically `int` in Python; reject them
            # explicitly to keep the "scalar" contract clean.
            raise SecretBootstrapException(
                f"SEC-STORE-003 aliyun: secret {logical_name!r} field {field!r} "
                f"is not a scalar (got {type(value).__name__})",
            )
        if isinstance(value, bool):
            # Defensive: `isinstance(True, int)` is True, but we
            # explicitly want to reject booleans.
            raise SecretBootstrapException(
                f"SEC-STORE-003 aliyun: secret {logical_name!r} field {field!r} is a boolean, not a scalar",
            )
        return str(value).encode("utf-8")

    # --- Internal: KeyWrappingBackend helpers ---------------------------

    def _physical_key_id(self, key: KeyReference) -> str:
        """Resolve a logical `KeyReference.key_id` to the physical CMK id.

        Looks up `properties.kms_key_bindings[key.key_id]`; raises
        `SecretConfigurationException("SEC-KEY-001")` when missing
        (mirrors Java `AliyunSecretClient.physicalKey(...)`).
        """
        logical = key.key_id
        physical = self._resolved.properties.kms_key_bindings.get(logical)
        if not physical:
            raise SecretConfigurationException(
                f"SEC-KEY-001 aliyun: no KMS key binding for logical key {logical!r}",
            )
        return physical

    @staticmethod
    def _purpose_for(key: KeyReference) -> "atlas_richie.secret.crypto.KeyPurpose":
        # The framework's `KeyReference` does not carry a `purpose`;
        # default to `KeyPurpose.WRAP` so KMS-side policy always
        # has a value to evaluate. Callers that need a different
        # purpose should pass a `CryptoContext` with the desired
        # `purpose` (which `wrap_key` itself does not currently
        # take, by design).
        from atlas_richie.secret.crypto import KeyPurpose

        return KeyPurpose.WRAP

    def _encryption_context(
        self,
        *,
        reference: KeyReference,
        context: CryptoContext,
    ) -> dict[str, str]:
        """Build the Alibaba `EncryptionContext` map.

        Mirrors Java `AliyunSecretClient.encryptionContext(...)`:

        - `atlas-component` = provider id
        - `atlas-key` = logical key id
        - `atlas-version` = framework protocol version (0.2.0)
        - `atlas-purpose` = `context.purpose.name()`
        - `atlas-aad-sha256` = hex SHA-256 of the canonical JSON of
          `context.aad` (may be empty string when the caller did
          not supply any AAD)
        - `atlas-envelope-version` / `atlas-algorithm` /
          `atlas-nonce-sha256` — optional, taken from
          `context.aad` when present (caller-controlled)
        """
        aad_bytes = self._canonical_aad_bytes(context.aad)
        result: dict[str, str] = {
            "atlas-component": self._resolved.provider_id,
            "atlas-key": reference.key_id,
            "atlas-version": "0.2.0",
            "atlas-purpose": context.purpose.name,
            "atlas-aad-sha256": hashlib.sha256(aad_bytes).hexdigest(),
        }
        for key in ("atlas-envelope-version", "atlas-algorithm", "atlas-nonce-sha256"):
            value = context.aad.get(key) if context.aad else None
            if value is not None:
                result[key] = value
        return result

    @staticmethod
    def _canonical_aad_bytes(aad: Mapping[str, str]) -> bytes:
        if not aad:
            return b""
        items = sorted(aad.items())
        return json.dumps(items, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    # --- Internal: bootstrap helpers ------------------------------------

    @staticmethod
    def _flatten(value: object, *, prefix: str) -> dict[str, str]:
        """Recursively flatten a JSON-compatible value.

        - dict → `prefix.subkey` for each entry
        - list → `prefix[0]`, `prefix[1]`, ...
        - scalar → `prefix` → `str(value)`
        """
        result: dict[str, str] = {}
        if isinstance(value, dict):
            for key, child in value.items():
                child_prefix = f"{prefix}.{key}" if prefix else str(key)
                result.update(AliyunSecretClient._flatten(child, prefix=child_prefix))
            return result
        if isinstance(value, list):
            for index, child in enumerate(value):
                child_prefix = f"{prefix}[{index}]"
                result.update(AliyunSecretClient._flatten(child, prefix=child_prefix))
            return result
        if value is None:
            result[prefix] = ""
        elif isinstance(value, bool):
            result[prefix] = "true" if value else "false"
        elif isinstance(value, (int, float, str)):
            result[prefix] = str(value)
        else:
            # Unknown scalar type — render via repr and keep going.
            result[prefix] = repr(value)
        return result

    @staticmethod
    def _merge_without_ambiguity(
        target: dict[str, str],
        incoming: Mapping[str, str],
        *,
        binding_name: str,
    ) -> None:
        """Merge `incoming` into `target`; raise on conflict.

        Mirrors Java `AliyunSecretBootstrapProviderFactory.
        mergeWithoutAmbiguity(...)`. Two values are considered
        conflicting when both bindings wrote the same key but with
        different string content. A binding writing the same value
        twice is a no-op.
        """
        for key, value in incoming.items():
            if key in target and target[key] != value:
                raise SecretBootstrapException(
                    f"SEC-STORE-003 aliyun: bootstrap merge conflict on key {key!r}: "
                    f"existing={target[key]!r} vs binding {binding_name!r}={value!r}",
                )
            target[key] = value

    @staticmethod
    def _value_sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _digest_versions(pairs: Iterable[tuple[str, str]]) -> str:
        """Return a SHA-256 hex digest over sorted `(version_id, value_sha256)` pairs.

        Mirrors Java `AliyunSecretBootstrapProviderFactory.
        digestVersions(...)`. Sorting guarantees that the digest is
        stable across process restarts and across multiple parallel
        fetches that complete in different orders.
        """
        canonical = "\n".join(
            f"{version_id}\t{value_sha256}"
            for version_id, value_sha256 in sorted(pairs)
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # --- Internal: error translation ------------------------------------

    @staticmethod
    def _extract_sdk_code(error: BaseException) -> str:
        """Best-effort extraction of the vendor code from a Tea / SDK exception.

        The Alibaba SDK attaches the code as either `error.code` or
        `error.errorCode` depending on the SDK version; we check
        both before giving up.
        """
        for attr in ("code", "errorCode", "Code"):
            value = getattr(error, attr, None)
            if isinstance(value, str) and value:
                return value
        return ""

    def _map_sdk_error(
        self,
        operation: str,
        reference: object,
        error: BaseException,
    ) -> SecretException:
        code = self._extract_sdk_code(error)
        return SecretException(
            f"SEC-PROVIDER-001 aliyun: {operation} failed "
            f"(reference={reference!r}, vendor_code={code!r}): {error}",
        )


__all__ = [
    # Gateway protocol + responses
    "AliyunKmsGateway",
    "AliyunGetSecretValueResponse",
    "AliyunEncryptResponse",
    "AliyunDecryptResponse",
    # Spec types
    "MissingPolicy",
    "AliyunBootstrapLoadResult",
    # 4-SPI composite
    "AliyunSecretClient",
]
