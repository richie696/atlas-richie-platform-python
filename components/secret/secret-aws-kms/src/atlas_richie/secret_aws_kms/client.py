"""`AwsSecretClient` — 5 个 SPI 角色的复合实现,跑在 boto3 KMS + SecretsManager 上。

中文
----
对位 Java `cn.richie696.component.secret.provider.aws.AwsSecretClient`,
后者 extends `SecretBootstrapClient, SecretBackend, KeyWrappingBackend,
SigningBackend, SecretProviderSession`。Python 端用两个 boto3 client:

- `boto3.client("kms")` — wrap / unwrap (GenerateDataKey + Decrypt) +
  sign / verify (Sign + Verify on asymmetric CMK)
- `boto3.client("secretsmanager")` — get / get_version / get_metadata /
  exists / list,以及 bootstrap batch read

`SecretBackend` → `SecretOperations` 名字对位 Python protocol 体系。

读 / 写边界:对位 Java `AwsSecretClient` **不**实现
`SecretWriter` / `SecretDeletable` / `SecretListable`(Java 用
`Set<SecretCapability>` 描述了 LIST 能力但没有 `SecretListable`
SPI;Python 端 `SecretOperations` Protocol 也不含 list,但我们
额外实现了 `list(prefix) → list[SecretReference]`,因为 framework
的 `SecretProviderSession` 协议不强制 list 必须来自
`SecretOperations`,只需 duck-typing)。

boto3 的 retry 走 SDK 自带的 standard mode(默认 3 次);不需要
单独的 retry 包装器。

错误映射:

- SM `ResourceNotFoundException` → `SecretIntegrityException`(404
  等价)
- SM `AccessDeniedException` → `SecretException("SEC-AUTHZ-001")`
- KMS `AccessDeniedException` → `SecretCryptoException("SEC-AUTHZ-001")`
- KMS `InvalidKeyId` / `NotFoundException` →
  `SecretConfigurationException` 或 `SecretIntegrityException`
- 5xx / throttling → 由 boto3 standard mode retry 处理,逃出
  来的转译为 `SecretException("SEC-PROVIDER-001")`

English
--------
Composite implementation of 5 SPI roles on top of two boto3
clients. Mirrors Java `AwsSecretClient` 1:1. boto3's built-in
standard retry handles 5xx / throttling; the client only
classifies the final error.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import boto3
import botocore.exceptions

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
from atlas_richie.secret.bootstrap.spi import (
    SecretBootstrapClient,
    SecretBootstrapContext,
    SecretBootstrapRequest,
    SecretBootstrapResult,
)
from atlas_richie.secret.bootstrap.catalog import RequiredWhen
from atlas_richie.secret_aws_kms.configuration import ResolvedAwsConfiguration

if TYPE_CHECKING:
    pass

_logger = logging.getLogger("atlas_richie.secret_aws_kms.client")

# 1:1 with Java `WRAPPING_ALGORITHM = "aws-kms-symmetric-default"`
_WRAPPING_ALGORITHM = "aws-kms-symmetric-default"

# Default signing algorithm — read from `properties.kms_signing_algorithm`,
# which defaults to "RSASSA_PSS_SHA_256" (mirrors Java default).
_DEFAULT_SIGNING_ALGORITHM = "RSASSA_PSS_SHA_256"

# AWS Secrets Manager version id prefix (SM returns e.g.
# "aaaa-bbbb-cccc-dddd"). We treat the string as opaque and
# surface it via `SecretVersion.number`.
_SM_VERSION_LATEST = "AWSCURRENT"

# boto3 error codes
_ERR_NOT_FOUND = "ResourceNotFoundException"
_ERR_ACCESS_DENIED = "AccessDeniedException"
_ERR_INVALID_KEY = "InvalidKeyId"
_ERR_KEY_NOT_FOUND = "NotFoundException"
_ERR_THROTTLING = "ThrottlingException"
_ERR_LIMIT_EXCEEDED = "LimitExceededException"


class AwsSecretClient(
    SecretOperations,
    SecretBootstrapClient,
    SecretProviderSession,
):
    """Composite secret client for AWS (Secrets Manager + KMS).

    Implements 5 SPI roles:

    - `SecretOperations` — Secrets Manager reads
    - `KeyWrappingBackend` (duck-typed) — KMS GenerateDataKey / Decrypt
    - `SigningBackend` (duck-typed) — KMS Sign / Verify
    - `SecretBootstrapClient` — startup-time batch read
    - `SecretProviderSession` — provider lifecycle

    The class does **not** implement `SecretWriter` /
    `SecretDeletable` — the framework's `writer` / `deletable`
    properties return `None`, matching Java's
    `AwsSecretClient`.

    Constructor parameters:

    - `resolved`: immutable `ResolvedAwsConfiguration`
    - `kms_client`: a `boto3.client("kms")` instance
    - `sm_client`: a `boto3.client("secretsmanager")` instance
    - `snapshot_manager`: optional `SecretSnapshotManager`
    - `close_action`: optional callable invoked from `close()`
    """

    __slots__ = (
        "_closed",
        "_close_action",
        "_descriptor_backend",
        "_kms_client",
        "_resolved",
        "_sm_client",
        "_snapshot_manager",
    )

    def __init__(
        self,
        resolved: ResolvedAwsConfiguration,
        kms_client,
        sm_client,
        *,
        snapshot_manager: SecretSnapshotManager | None = None,
        close_action: Callable[[], None] | None = None,
        descriptor_backend: SecretBackend = SecretBackend.AWS,
    ) -> None:
        self._resolved = resolved
        self._kms_client = kms_client
        self._sm_client = sm_client
        self._snapshot_manager = snapshot_manager or SecretSnapshotManager()
        self._close_action = close_action
        self._closed = False
        # Defaults to `SecretBackend.AWS`. The vault wheel sets
        # the equivalent field; AWS-only deployments never
        # override it.
        self._descriptor_backend = descriptor_backend

    # --- SecretProviderSession Protocol ---------------------------------

    @property
    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self._resolved.provider_id,
            backend=self._descriptor_backend,
            capability=self._resolved.capability,
            version="0.2.0",
        )

    @property
    def configuration(self) -> SecretProviderConfiguration:
        return SecretProviderConfiguration(
            name=self._resolved.provider_id,
            parameters={},
            timeout_seconds=self._resolved.properties.timeout_seconds,
            retries=3,  # boto3 standard mode
            namespace=self._resolved.properties.region,
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
            _logger.exception(
                "aws: error during close_action for provider %r",
                self._resolved.provider_id,
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException(
                f"aws: provider session {self._resolved.provider_id!r} is closed",
            )

    # --- SecretOperations Protocol --------------------------------------

    def get(self, reference: SecretReference) -> SecretValue:
        self._ensure_open()
        # The reference's `version_selector` may carry a
        # STATIC or LATEST hint. STATIC → pass the static
        # version's id explicitly; LATEST (or anything else)
        # → omit VersionId so boto3 returns the current stage.
        version_id = self._resolve_version_id(reference)
        return self._read(reference, version_id=version_id)

    def get_version(
        self,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        self._ensure_open()
        return self._read(reference, version_id=version.number)

    def get_metadata(self, reference: SecretReference) -> SecretMetadata:
        self._ensure_open()
        try:
            response = self._sm_client.describe_secret(
                SecretId=reference.path,
            )
        except botocore.exceptions.ClientError as error:
            raise self._map_sm_error("get_metadata", error) from error
        created_at = response.get("CreatedDate")
        if not isinstance(created_at, datetime):
            created_at = datetime.now(tz=timezone.utc)
        return SecretMetadata(
            reference=reference,
            version=SecretVersion(number=_SM_VERSION_LATEST, created_at=created_at),
            backend=self._descriptor_backend,
            created_at=created_at,
            expires_at=response.get("LastChangedDate"),
            tags={"provider": "aws", "region": self._resolved.properties.region},
        )

    def exists(self, reference: SecretReference) -> bool:
        self._ensure_open()
        try:
            self._sm_client.describe_secret(SecretId=reference.path)
            return True
        except botocore.exceptions.ClientError as error:
            code = _error_code(error)
            if code == _ERR_NOT_FOUND:
                return False
            raise self._map_sm_error("exists", error) from error

    def list(self, prefix: str | None = None) -> list[SecretReference]:
        """List secrets in the configured region (and optional prefix).

        Not part of the Python `SecretOperations` Protocol, but
        duck-typed for the framework's `list_capability(session)`
        probe. Mirrors Java's `can_list=True` capability.
        """
        self._ensure_open()
        kwargs: dict[str, object] = {}
        if prefix:
            kwargs["Filters"] = [{"Key": "name", "Values": [prefix]}]
        try:
            response = self._sm_client.list_secrets(**kwargs)
        except botocore.exceptions.ClientError as error:
            raise self._map_sm_error("list", error) from error
        return [
            SecretReference(provider=self.descriptor.name, path=item["Name"])
            for item in response.get("SecretList", [])
        ]

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
                "aws: wrap_key requires a non-empty DEK",
            )
        cmk = self._resolve_cmk(kek)
        # Use `kms.encrypt` (input plaintext → ciphertext) rather
        # than `kms.generate_data_key` (which generates a fresh
        # DEK). The framework's `wrap_key` is **importing** the
        # caller's DEK as a wrapped blob so it can be persisted
        # and later unwrapped; the caller owns the DEK bytes, so
        # we must return a ciphertext that decrypts back to those
        # exact bytes. `kms.encrypt` is the right tool for that
        # (up to 4 KB of plaintext per call; sufficient for AES
        # 128/192/256 DEKs).
        try:
            response = self._kms_client.encrypt(
                KeyId=cmk,
                Plaintext=dek,
            )
        except botocore.exceptions.ClientError as error:
            raise self._map_kms_error("wrap_key", kek, error) from error
        return WrappedKey(
            kek_reference=kek,
            ciphertext=response["CiphertextBlob"],
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
                f"aws: cannot unwrap a key with algorithm "
                f"{wrapped.algorithm!r}; expected {_WRAPPING_ALGORITHM!r}",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "aws: wrapped ciphertext is empty",
            )
        cmk = self._resolve_cmk(context.primary_key)
        try:
            response = self._kms_client.decrypt(
                CiphertextBlob=wrapped.ciphertext,
                KeyId=cmk,
            )
        except botocore.exceptions.ClientError as error:
            raise self._map_kms_error("unwrap_key", context.primary_key, error) from error
        return response["Plaintext"]

    # --- SigningBackend (duck-typed) ------------------------------------

    def sign(
        self,
        payload: bytes,
        key: KeyReference,
        *,
        algorithm: str | None = None,
    ) -> SignatureValue:
        self._ensure_open()
        if not payload:
            raise SecretCryptoException(
                "aws: sign requires non-empty payload",
            )
        cmk = self._resolve_cmk(key)
        signing_algorithm = (
            algorithm
            or self._resolved.properties.kms_signing_algorithm
            or _DEFAULT_SIGNING_ALGORITHM
        )
        try:
            response = self._kms_client.sign(
                KeyId=cmk,
                Message=payload,
                SigningAlgorithm=signing_algorithm,
            )
        except botocore.exceptions.ClientError as error:
            raise self._map_kms_error("sign", key, error) from error
        return SignatureValue(
            algorithm=signing_algorithm,
            signature=response["Signature"],
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
                "aws: verify requires non-empty payload",
            )
        if signature is None:
            raise SecretCryptoException(
                "aws: verify requires a SignatureValue",
            )
        cmk = self._resolve_cmk(signature.key)
        try:
            response = self._kms_client.verify(
                KeyId=cmk,
                Message=payload,
                Signature=signature.signature,
                SigningAlgorithm=signature.algorithm,
            )
        except botocore.exceptions.ClientError as error:
            # AWS KMS raises `KMSInvalidSignatureException` for
            # signature mismatch (rather than returning
            # `SignatureValid=False`). The framework's verify
            # contract is "return False on tampered payload",
            # so we translate the exception to `False`.
            if _error_code(error) == "KMSInvalidSignatureException":
                return False
            raise self._map_kms_error("verify", signature.key, error) from error
        return bool(response.get("SignatureValid", False))

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
        for binding in request.catalog.bindings:
            try:
                value = self.get(binding.reference)
                resolved[binding.name] = value
            except SecretIntegrityException as error:
                if binding.required_when is RequiredWhen.STARTUP:
                    raise SecretException(
                        f"aws: bootstrap Secret binding "
                        f"{binding.name!r} is missing: {error}",
                    ) from error
                missing.append(binding.name)
                _logger.warning(
                    "aws: bootstrap binding %r missing (required_when=%s); continuing",
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
        *,
        version_id: str | None,
    ) -> SecretValue:
        kwargs: dict[str, object] = {"SecretId": reference.path}
        if version_id and version_id != _SM_VERSION_LATEST:
            kwargs["VersionId"] = version_id
        try:
            response = self._sm_client.get_secret_value(**kwargs)
        except botocore.exceptions.ClientError as error:
            raise self._map_sm_error("get", error) from error
        secret_string = response.get("SecretString")
        if secret_string is None:
            binary = response.get("SecretBinary")
            plaintext = bytes(binary) if binary is not None else b""
        else:
            plaintext = secret_string.encode("utf-8")
        actual_version = response.get("VersionId", _SM_VERSION_LATEST)
        created_at = response.get("CreatedDate")
        if not isinstance(created_at, datetime):
            created_at = datetime.now(tz=timezone.utc)
        return SecretValue(
            plaintext=plaintext,
            metadata=SecretMetadata(
                reference=reference,
                version=SecretVersion(number=actual_version, created_at=created_at),
                backend=self._descriptor_backend,
                created_at=created_at,
                expires_at=response.get("VersionStages"),
                tags={
                    "provider": "aws",
                    "region": self._resolved.properties.region,
                },
            ),
        )

    def _resolve_version_id(self, reference: SecretReference) -> str | None:
        """Map `SecretReference.version_selector` to a Secrets
        Manager `VersionId` string.

        - `LATEST` → returns `None` (boto3 omits `VersionId`,
          which makes SM return the current staged version).
        - `STATIC` → returns the binding's
          `static_version.number` (the SM-assigned UUID).
        - `PINNED_AT_TIME` → not supported by SM (raises
          `SecretConfigurationException`).
        """
        kind = reference.version_selector.kind
        if kind is SecretVersionSelectorKind.LATEST:
            return None
        if kind is SecretVersionSelectorKind.STATIC:
            static = reference.version_selector.static_version
            if static is None:
                raise SecretConfigurationException(
                    "aws: STATIC selector requires a static_version",
                )
            return static.number
        raise SecretConfigurationException(
            "aws: PINNED_AT_TIME is not supported by Secrets Manager; "
            "use LATEST or STATIC",
        )

    def _resolve_cmk(self, reference: KeyReference) -> str:
        """Map `KeyReference` to a KMS CMK ARN.

        Same logical-to-physical indirection as the vault
        wheel's R-233.3 `transit_key_bindings`:
        1. If `key_id` is in `properties.kms_key_bindings`,
           use the mapped physical CMK ARN.
        2. Otherwise, use `key_id` as the physical CMK ARN
           directly.
        3. Empty `key_id` always raises
           `SecretConfigurationException`.
        """
        if not reference.key_id:
            raise SecretConfigurationException(
                f"aws [SEC-KEY-001]: KeyReference {reference!r} "
                "has an empty key_id; cannot resolve a KMS CMK",
            )
        bindings = self._resolved.properties.kms_key_bindings
        if bindings and reference.key_id in bindings:
            physical = bindings[reference.key_id]
            if not physical:
                raise SecretConfigurationException(
                    f"aws [SEC-KEY-001]: KMS key binding for "
                    f"{reference.key_id!r} is empty",
                )
            return physical
        return reference.key_id

    def _map_sm_error(
        self,
        operation: str,
        error: botocore.exceptions.ClientError,
    ) -> SecretException:
        """Map a Secrets Manager `ClientError` to a framework
        `SecretException` / `SecretIntegrityException`.
        """
        code = _error_code(error)
        if code == _ERR_NOT_FOUND:
            return SecretIntegrityException(
                f"aws: {operation} request failed (not found): {error}",
            )
        if code == _ERR_ACCESS_DENIED:
            return SecretException(
                f"aws [SEC-AUTHZ-001]: {operation} request was rejected: {error}",
            )
        if code in (_ERR_THROTTLING, _ERR_LIMIT_EXCEEDED):
            return SecretException(
                f"aws [SEC-PROVIDER-001]: {operation} was throttled: {error}",
            )
        return SecretException(
            f"aws [SEC-PROVIDER-001]: {operation} request failed: {error}",
        )

    def _map_kms_error(
        self,
        operation: str,
        key: KeyReference,
        error: botocore.exceptions.ClientError,
    ) -> SecretCryptoException:
        code = _error_code(error)
        if code == _ERR_ACCESS_DENIED:
            return SecretCryptoException(
                f"aws [SEC-AUTHZ-001]: {operation} was rejected: {error}",
            )
        if code in (_ERR_INVALID_KEY, _ERR_KEY_NOT_FOUND):
            return SecretCryptoException(
                f"aws [SEC-KEY-001]: {operation} for key "
                f"{key.key_id!r} failed (key not found / invalid): {error}",
            )
        if code in (_ERR_THROTTLING, _ERR_LIMIT_EXCEEDED):
            return SecretCryptoException(
                f"aws [SEC-PROVIDER-001]: {operation} for key "
                f"{key.key_id!r} was throttled: {error}",
            )
        return SecretCryptoException(
            f"aws [SEC-CRYPTO-001]: {operation} for key "
            f"{key.key_id!r} failed: {error}",
        )


def _error_code(error: botocore.exceptions.ClientError) -> str:
    """Extract the AWS error code from a boto3 `ClientError`."""
    response = getattr(error, "response", None) or {}
    error_block = response.get("Error") if isinstance(response, dict) else None
    if isinstance(error_block, dict):
        code = error_block.get("Code")
        if isinstance(code, str):
            return code
    return ""


__all__ = ["AwsSecretClient"]
