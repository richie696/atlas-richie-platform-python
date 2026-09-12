"""VaultSecretClient — 5 个 SPI 角色的复合实现,跑在一个 `hvac.Client` 上。

中文
----
对位 Java `cn.richie696.component.secret.provider.vault.VaultSecretClient`,
后者 extends `SecretBootstrapClient, SecretBackend, KeyWrappingBackend,
SigningBackend, SecretProviderSession`。Python 端按 Pythonic 习惯把
SPI 名字改成 framework 已有的 Protocol:

| Java SPI | Python Protocol |
| --- | --- |
| `SecretBackend` (read) | `SecretOperations` |
| `KeyWrappingBackend` | `KeyWrappingBackend`(同名,包不同) |
| `SigningBackend` | `SigningBackend`(同名,包不同) |
| `SecretBootstrapClient` | `SecretBootstrapClient`(同名,包不同) |
| `SecretProviderSession` | `SecretProviderSession`(同名,包不同) |

读 / 写边界与 Java 一致:`VaultSecretClient` **不**实现
`SecretWriter` / `SecretDeletable` / `SecretListable`;Vault 的
KV v2 写入通过 `hvac.Client` 直接走 admin path(与 Java
VaultSecretClient 不暴露写一致)。

hvac 2.4.0 适配:

- **transit `plaintext` / `hash_input` 不自动 base64**:直接传 bytes
  会触发 `TypeError: Object of type bytes is not JSON serializable`。
  本 client 统一走 `_b64()` 适配。`decrypt_data` 返回的 plaintext
  仍是 base64 字符串,需要 `_b64_decoded()` 解码。
- **`create_key` 用 `key_type=`**(不是 `type=`)。
- **ECDSA / HMAC 类型 key 才能签名**,aes256-gcm96 仅 encrypt。

错误映射:

- hvac 401/403 → `SecretCryptoException("SEC-AUTH-001")` /
  `SecretCryptoException("SEC-AUTHZ-001")`
- hvac 5xx / 429 → 已由 `VaultRetryExecutor` 内部重试,真正逃出来
  的不再重试,转译为 `SecretException("SEC-PROVIDER-001")`
- hvac 404 (`InvalidPath`) → 业务层 `SecretIntegrityException`("not found")

English
--------
Composite implementation of 5 SPI roles on top of a single `hvac.Client`.
The class does not implement write/delete/list SPI roles, matching the
Java `VaultSecretClient` (which is read + crypto + bootstrap + session,
never write). Includes the hvac 2.4.0 base64 workaround for transit
APIs and uses `VaultRetryExecutor` for transient failures.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import hvac

from atlas_richie.secret.bootstrap.catalog import RequiredWhen, SecretBinding
from atlas_richie.secret.bootstrap.spi import (
    SecretBootstrapClient,
    SecretBootstrapContext,
    SecretBootstrapRequest,
    SecretBootstrapResult,
)
from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyReference,
    SignatureValue,
    WrappedKey,
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
from atlas_richie.secret_vault.configuration import ResolvedVaultConfiguration
from atlas_richie.secret_vault.request_id import VaultRequestIdCapture
from atlas_richie.secret_vault.retry import VaultRetryExecutor

if TYPE_CHECKING:
    pass

_logger = logging.getLogger("atlas_richie.secret_vault.client")

# 1:1 with Java `WRAPPING_ALGORITHM = "vault-transit"`. Stored on
# `WrappedKey.algorithm` so downstream consumers can detect that
# this DEK is sealed by a Vault Transit KEK.
_WRAPPING_ALGORITHM = "vault-transit"

# Java `VaultSecretClient` does not pin a specific signature algorithm
# string (the algorithm is determined by the Transit key's `type`).
# We record `"vault-transit"` on `SignatureValue.algorithm` for
# symmetry with the wrap-side constant; consumers should treat this
# as opaque metadata, not as a JWT-style algorithm identifier.
_SIGNING_ALGORITHM = "vault-transit"

# Mapping from hvac exception class names to framework error codes.
# Mirrors the Java `mapProviderFailure` / `mapCryptoProviderFailure`
# switch on `RestClientResponseException.getStatusCode()`.
_AUTH_STATUS_CODE = 401
_AUTHZ_STATUS_CODE = 403
_NOT_FOUND_STATUS_CODE = 404


def _b64(data: bytes) -> str:
    """Base64-encode `data` for hvac 2.4 transit APIs.

    hvac 2.4.0 fails to auto-encode bytes for `plaintext` /
    `hash_input` on `encrypt_data` / `sign_data` — it serializes the
    body as JSON and crashes. This helper produces the base64
    string hvac expects, identical to what it would have produced
    for a str input.
    """
    return base64.b64encode(data).decode("ascii")


def _b64_decoded(value: str) -> bytes:
    """Decode the base64 plaintext that hvac's `decrypt_data` returns.

    hvac does not decode the response on our behalf.
    """
    return base64.b64decode(value)


class VaultSecretClient(
    SecretOperations,
    SecretBootstrapClient,
    SecretProviderSession,
):
    """Composite secret client for HashiCorp Vault.

    Implements `SecretOperations` (KV v2 reads), `KeyWrappingBackend`
    and `SigningBackend` (Transit wrap/unwrap/sign/verify),
    `SecretBootstrapClient` (startup-time bundle resolution), and
    `SecretProviderSession` (provider lifecycle). The class
    intentionally does not implement `SecretWriter` /
    `SecretDeletable` / `SecretListable` — Vault writes are an
    admin-path concern, matching the Java `VaultSecretClient`
    design.

    Constructor parameters:

    - `resolved`: the immutable `ResolvedVaultConfiguration`
      (provider_id, properties, configuration_hash, capability).
    - `hvac_client`: an already-authenticated `hvac.Client`. The
      factory in `factory.py` is responsible for applying the
      `VaultAuthStrategy` before passing the client in.
    - `retry_executor`: optional. Defaults to a
      `VaultRetryExecutor(max_attempts=resolved.properties.max_retries)`.
    - `request_id_capture`: optional. Defaults to a fresh
      `VaultRequestIdCapture`; pass an existing one to share state
      with a caller that wants to thread a correlation id.
    - `snapshot_manager`: optional. Defaults to a fresh
      `SecretSnapshotManager`.
    - `close_action`: optional callable invoked from `close()` to
      release the underlying `hvac.Client` (e.g. revoke the token
      or drop a connection pool).
    """

    __slots__ = (
        "_resolved",
        "_hvac_client",
        "_retry",
        "_request_ids",
        "_snapshot_manager",
        "_close_action",
        "_closed",
    )

    def __init__(
        self,
        resolved: ResolvedVaultConfiguration,
        hvac_client: hvac.Client,
        *,
        retry_executor: VaultRetryExecutor | None = None,
        request_id_capture: VaultRequestIdCapture | None = None,
        snapshot_manager: SecretSnapshotManager | None = None,
        close_action: Callable[[], None] | None = None,
    ) -> None:
        self._resolved = resolved
        self._hvac_client = hvac_client
        self._retry = retry_executor or VaultRetryExecutor(
            max_attempts=resolved.properties.max_retries,
        )
        self._request_ids = request_id_capture or VaultRequestIdCapture()
        self._snapshot_manager = snapshot_manager or SecretSnapshotManager()
        self._close_action = close_action
        self._closed = False

    # --- SecretProviderSession Protocol ---------------------------------

    @property
    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self._resolved.provider_id,
            backend=SecretBackend.VAULT,
            capability=self._resolved.capability,
            version="0.2.0",
        )

    @property
    def configuration(self) -> SecretProviderConfiguration:
        # Backend-specific knobs are encoded into `properties`; the
        # `parameters` map is intentionally empty here so the
        # framework does not have to know about Vault fields.
        return SecretProviderConfiguration(
            name=self._resolved.provider_id,
            parameters={},
            timeout_seconds=self._resolved.properties.timeout_seconds,
            retries=self._resolved.properties.max_retries,
            namespace=self._resolved.properties.namespace,
        )

    @property
    def operations(self) -> SecretOperations:
        # The client IS the operations impl (read-only).
        return self

    @property
    def writer(self):  # type: ignore[override]
        # Vault KV v2 writes are an admin-path concern; this
        # provider is read-only at the framework level, mirroring
        # the Java `VaultSecretClient` design.
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

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._close_action is None:
            return
        try:
            self._close_action()
        except Exception:  # noqa: BLE001
            # Context shutdown must not expose provider details or
            # block remaining cleanup — matches Java VaultClientFactory.close.
            _logger.exception(
                "vault: error during close_action for provider %r",
                self._resolved.provider_id,
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException(
                f"vault: provider session {self._resolved.provider_id!r} is closed",
            )

    # --- SecretOperations Protocol --------------------------------------

    def get(self, reference: SecretReference) -> SecretValue:
        self._ensure_open()
        self._request_ids.clear()
        version_number = self._resolve_version(reference)
        return self._read(reference, version_number)

    def get_version(
        self,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        self._ensure_open()
        self._request_ids.clear()
        return self._read(reference, version.number)

    def get_metadata(self, reference: SecretReference) -> SecretMetadata:
        self._ensure_open()
        # Vault KV v2 metadata API is read-without-decode — returns
        # version + created_at but no secret data.
        try:
            response = self._retry.execute(
                lambda: self._hvac_client.secrets.kv.v2.read_secret_metadata(
                    path=reference.path,
                    mount_point=self._resolved.properties.kv_mount,
                ),
            )
        except hvac.exceptions.InvalidPath as error:
            raise SecretIntegrityException(
                f"vault: secret metadata is missing at {reference.path!r}",
            ) from error
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._map_provider_error("get_metadata", error) from error
        latest = _latest_version(response)
        created_at = _parse_created_at(response, latest)
        return SecretMetadata(
            reference=reference,
            version=SecretVersion(number=str(latest), created_at=created_at),
            backend=SecretBackend.VAULT,
            created_at=created_at,
            expires_at=None,
            tags={
                "provider": "vault",
                "kv_mount": self._resolved.properties.kv_mount,
            },
        )

    def exists(self, reference: SecretReference) -> bool:
        self._ensure_open()
        try:
            self._hvac_client.secrets.kv.v2.read_secret_metadata(
                path=reference.path,
                mount_point=self._resolved.properties.kv_mount,
            )
            return True
        except hvac.exceptions.InvalidPath:
            return False
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._map_provider_error("exists", error) from error

    # --- KeyWrappingBackend Protocol (via duck-typing) -------------------

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
                "vault: wrap_key requires a non-empty DEK",
            )
        key_id = self._resolve_transit_key(kek)
        mount = self._resolved.properties.transit_mount
        self._request_ids.clear()
        try:
            ciphertext = self._retry.execute(
                lambda: self._hvac_client.secrets.transit.encrypt_data(
                    name=key_id,
                    plaintext=_b64(dek),
                    mount_point=mount,
                )["data"]["ciphertext"],
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._map_crypto_error("wrap_key", kek, error) from error
        return WrappedKey(
            kek_reference=kek,
            ciphertext=ciphertext.encode("ascii"),
            algorithm=_WRAPPING_ALGORITHM,
            nonce=None,
            aad={},
        )

    def unwrap_key(
        self,
        wrapped: WrappedKey,
        context: CryptoContext,
    ) -> bytes:
        self._ensure_open()
        if wrapped.algorithm != _WRAPPING_ALGORITHM:
            raise SecretCryptoException(
                f"vault: cannot unwrap a key with algorithm "
                f"{wrapped.algorithm!r}; expected {_WRAPPING_ALGORITHM!r}",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "vault: wrapped ciphertext is empty",
            )
        key_id = self._resolve_transit_key(context.primary_key)
        mount = self._resolved.properties.transit_mount
        self._request_ids.clear()
        try:
            ciphertext_str = wrapped.ciphertext.decode("ascii")
        except UnicodeDecodeError as error:
            raise SecretCryptoException(
                "vault: wrapped ciphertext is not valid ASCII",
            ) from error
        if not ciphertext_str.startswith("vault:v"):
            raise SecretCryptoException(
                "vault: wrapped ciphertext is not a Vault Transit ciphertext",
            )
        try:
            plaintext_b64 = self._retry.execute(
                lambda: self._hvac_client.secrets.transit.decrypt_data(
                    name=key_id,
                    ciphertext=ciphertext_str,
                    mount_point=mount,
                )["data"]["plaintext"],
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._map_crypto_error(
                "unwrap_key",
                context.primary_key,
                error,
            ) from error
        return _b64_decoded(plaintext_b64)

    # --- SigningBackend Protocol (via duck-typing) ----------------------

    def sign(
        self,
        payload: bytes,
        key: KeyReference,
        *,
        algorithm: str | None = None,  # noqa: ARG002 - reserved
    ) -> SignatureValue:
        self._ensure_open()
        if not payload:
            raise SecretCryptoException(
                "vault: sign requires non-empty payload",
            )
        key_id = self._resolve_transit_key(key)
        mount = self._resolved.properties.transit_mount
        self._request_ids.clear()
        try:
            signature = self._retry.execute(
                lambda: self._hvac_client.secrets.transit.sign_data(
                    name=key_id,
                    hash_input=_b64(payload),
                    mount_point=mount,
                )["data"]["signature"],
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._map_crypto_error("sign", key, error) from error
        return SignatureValue(
            algorithm=_SIGNING_ALGORITHM,
            signature=signature.encode("ascii"),
            signed_at=datetime.now(tz=timezone.utc),
            key=key,
        )

    def verify(
        self,
        payload: bytes,
        signature: SignatureValue,
    ) -> bool:
        self._ensure_open()
        if not payload:
            raise SecretCryptoException(
                "vault: verify requires non-empty payload",
            )
        if signature is None:
            raise SecretCryptoException(
                "vault: verify requires a SignatureValue",
            )
        if not signature.signature:
            raise SecretCryptoException(
                "vault: verify requires a non-empty signature",
            )
        # The Python `SigningBackend.verify` Protocol does not
        # accept a `KeyReference` parameter, so the key must come
        # from `signature.key`. The framework's own `SigningService`
        # round-trips the key through this field, so this is safe.
        key_id = self._resolve_transit_key(signature.key)
        mount = self._resolved.properties.transit_mount
        self._request_ids.clear()
        try:
            signature_str = signature.signature.decode("ascii")
        except UnicodeDecodeError as error:
            raise SecretCryptoException(
                "vault: signature is not valid ASCII",
            ) from error
        try:
            valid = self._retry.execute(
                lambda: self._hvac_client.secrets.transit.verify_signed_data(
                    name=key_id,
                    hash_input=_b64(payload),
                    signature=signature_str,
                    mount_point=mount,
                )["data"]["valid"],
            )
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._map_crypto_error("verify", signature.key, error) from error
        return bool(valid)

    # --- SecretBootstrapClient Protocol --------------------------------

    def bootstrap(
        self,
        request: SecretBootstrapRequest,
        context: SecretBootstrapContext,
    ) -> SecretBootstrapResult:
        self._ensure_open()
        started_at = context.now
        resolved: dict[str, SecretValue] = {}
        missing: list[str] = []
        request_ids: list[str] = []
        for binding in request.catalog.bindings:
            try:
                self._request_ids.clear()
                value = self.get(binding.reference)
                resolved[binding.name] = value
                rid = self._request_ids.consume()
                if rid is not None:
                    request_ids.append(rid)
            except SecretIntegrityException as error:
                if binding.required_when is RequiredWhen.STARTUP:
                    raise SecretException(
                        f"vault: bootstrap Secret binding "
                        f"{binding.name!r} is missing: {error}",
                    ) from error
                missing.append(binding.name)
                _logger.warning(
                    "vault: bootstrap binding %r missing (required_when=%s); continuing",
                    binding.name,
                    binding.required_when.value,
                )
                continue
        finished_at = context.now
        return SecretBootstrapResult(
            resolved=resolved,
            missing=tuple(missing),
            started_at=started_at,
            finished_at=finished_at,
        )

    # --- Internal helpers -----------------------------------------------

    def _read(
        self,
        reference: SecretReference,
        version_number: str,
    ) -> SecretValue:
        mount = self._resolved.properties.kv_mount
        try:
            response = self._retry.execute(
                lambda: self._hvac_client.secrets.kv.v2.read_secret_version(
                    path=reference.path,
                    mount_point=mount,
                    version=_coerce_version(version_number),
                ),
            )
        except hvac.exceptions.InvalidPath as error:
            raise SecretIntegrityException(
                f"vault: secret not found at {reference.path!r}",
            ) from error
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._map_provider_error("get", error) from error
        data = _extract_data(response)
        # hvac returns the actual version in the response metadata.
        # For LATEST selectors, surface the concrete version (e.g.
        # "2") instead of the "latest" sentinel, so callers can
        # pass it back as a STATIC selector for replay.
        actual_version = _response_version(response, fallback=version_number)
        created_at = _parse_created_at(response, actual_version)
        return SecretValue(
            plaintext=data,
            metadata=SecretMetadata(
                reference=reference,
                version=SecretVersion(number=actual_version, created_at=created_at),
                backend=SecretBackend.VAULT,
                created_at=created_at,
                expires_at=None,
                tags={
                    "provider": "vault",
                    "kv_mount": mount,
                },
            ),
        )

    def _resolve_version(self, reference: SecretReference) -> str:
        """Map `SecretVersionSelector` to a Vault KV v2 version int.

        - `LATEST` → returns the string ``"latest"`` (hvac's sentinel
          for "current"). We do not pre-resolve to a numeric version
          so concurrent rotates are immediately visible.
        - `STATIC` → returns the binding's `static_version.number`.
        - `PINNED_AT_TIME` is not supported (raises
          `SecretConfigurationException`); Vault KV v2 does not
          natively expose time-pinning.
        """
        kind = reference.version_selector.kind
        if kind is SecretVersionSelectorKind.LATEST:
            return "latest"
        if kind is SecretVersionSelectorKind.STATIC:
            static_version = reference.version_selector.static_version
            if static_version is None:
                raise SecretConfigurationException(
                    "vault: STATIC selector requires a static_version",
                )
            return static_version.number
        raise SecretConfigurationException(
            "vault: PINNED_AT_TIME is not supported by Vault KV v2; "
            "use LATEST or STATIC",
        )

    def _resolve_transit_key(self, reference: KeyReference) -> str:
        """Map `KeyReference` to a Vault Transit key name.

        The default convention is `KeyReference.key_id` IS the
        physical Transit key name. The framework populates
        `KeyReference.key_id` from `properties.transit_key_bindings`
        (if a mapping was configured) or from the caller's literal
        name. We require a non-empty string here so a misconfigured
        call surfaces as a clear `SecretConfigurationException`
        rather than an opaque hvac 400.
        """
        if not reference.key_id:
            raise SecretConfigurationException(
                f"vault: KeyReference {reference!r} has an empty key_id; "
                "cannot resolve a Vault Transit key",
            )
        return reference.key_id

    def _map_provider_error(
        self,
        operation: str,
        error: BaseException,
    ) -> SecretException:
        """Translate hvac exceptions to framework `SecretException`.

        Mirrors Java `mapProviderFailure` in `VaultSecretClient`. The
        Java side carries a structured error code; we embed it in the
        message prefix as ``[SEC-...]`` so logs and operators can
        grep for the same codes the Java side emits.
        """
        code = _classify_status(error, default="SEC-PROVIDER-001")
        return SecretException(
            f"vault [{code}]: {operation} request failed: {error}",
        )

    def _map_crypto_error(
        self,
        operation: str,
        key: KeyReference,
        error: BaseException,
    ) -> SecretCryptoException:
        code = _classify_status(error, default="SEC-CRYPTO-001")
        return SecretCryptoException(
            f"vault [{code}]: {operation} for key {key.key_id!r} failed: {error}",
        )


def _coerce_version(value: str | int) -> int:
    """Map `"latest"` → 0 (hvac sentinel for current version).

    hvac 2.4 treats `version=0` as "current" in `read_secret_version`;
    any positive int is a specific version.
    """
    if isinstance(value, int):
        return value
    if value == "latest" or value == "current":
        return 0
    try:
        coerced = int(value)
    except (TypeError, ValueError) as error:
        raise SecretConfigurationException(
            f"vault: invalid version selector {value!r}",
        ) from error
    if coerced < 0:
        raise SecretConfigurationException(
            f"vault: version must be a non-negative integer; got {coerced}",
        )
    return coerced


def _extract_data(response: Mapping[str, object]) -> bytes:
    """Extract the secret payload bytes from a KV v2 read response.

    Strategy (mirrors Java `selectValue`):
    1. If `data.data` has a single key, decode its value as bytes.
    2. If `data.data` has a `value` key, use that.
    3. Otherwise, JSON-encode the whole map so callers get a
       structured payload.

    Returning ``bytes`` matches the `SecretValue.plaintext` contract.
    """
    outer = response.get("data")
    if not isinstance(outer, Mapping):
        raise SecretIntegrityException(
            f"vault: KV v2 read response is missing 'data': {response!r}",
        )
    inner = outer.get("data")
    if not isinstance(inner, Mapping):
        raise SecretIntegrityException(
            f"vault: KV v2 read response is missing 'data.data': {response!r}",
        )
    if len(inner) == 1:
        only_value = next(iter(inner.values()))
        return _coerce_bytes(only_value)
    if "value" in inner:
        return _coerce_bytes(inner["value"])
    import json
    return json.dumps(dict(inner), sort_keys=True, ensure_ascii=False).encode("utf-8")


def _coerce_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (int, float, bool)):
        return str(value).encode("utf-8")
    import json
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _response_version(
    response: Mapping[str, object],
    *,
    fallback: str | int,
) -> str:
    """Extract the concrete version number from a KV v2 read response.

    Falls back to the selector string when the response does not
    carry a version metadata block (some hvac paths / proxied
    responses do not).
    """
    outer = response.get("data")
    if not isinstance(outer, Mapping):
        return str(fallback)
    metadata = outer.get("metadata")
    if not isinstance(metadata, Mapping):
        return str(fallback)
    version = metadata.get("version")
    if version is None:
        return str(fallback)
    return str(version)


def _latest_version(response: Mapping[str, object]) -> int:
    """Find the highest version in a KV v2 metadata response."""
    outer = response.get("data")
    if not isinstance(outer, Mapping):
        return 0
    versions = outer.get("versions")
    if not isinstance(versions, Mapping):
        return 0
    ints: list[int] = []
    for key in versions.keys():
        try:
            ints.append(int(key))
        except (TypeError, ValueError):
            continue
    return max(ints) if ints else 0


def _parse_created_at(
    response: Mapping[str, object],
    version_number: str | int,
) -> datetime:
    """Best-effort parse of the `created_time` from a KV v2 response.

    Returns the current UTC time when the field is missing or
    unparseable, so callers always get a usable timestamp.
    """
    outer = response.get("data")
    if not isinstance(outer, Mapping):
        return datetime.now(tz=timezone.utc)
    metadata = outer.get("metadata")
    if not isinstance(metadata, Mapping):
        return datetime.now(tz=timezone.utc)
    key = str(version_number) if version_number != "latest" else "current"
    candidate = metadata.get(f"version_{key}_created_time") or metadata.get("created_time")
    if not isinstance(candidate, str):
        return datetime.now(tz=timezone.utc)
    # Vault emits RFC 3339 / ISO 8601 with optional fractional seconds.
    cleaned = candidate.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return datetime.now(tz=timezone.utc)


def _classify_status(error: BaseException, *, default: str) -> str:
    """Best-effort hvac → framework error code translation.

    Mirrors the Java switch on `RestClientResponseException.getStatusCode()`.
    """
    status = getattr(error, "status_code", None)
    if status is None:
        response = getattr(error, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)
    if status is None:
        return default
    if status == _AUTH_STATUS_CODE:
        return "SEC-AUTH-001"
    if status == _AUTHZ_STATUS_CODE:
        return "SEC-AUTHZ-001"
    if status == _NOT_FOUND_STATUS_CODE:
        return "SEC-STORE-001"
    if isinstance(status, int) and 500 <= status < 600:
        return "SEC-PROVIDER-001"
    return default


__all__ = ["VaultSecretClient"]


_ = (Mapping, SecretBinding)
