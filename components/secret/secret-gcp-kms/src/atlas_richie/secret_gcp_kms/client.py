"""`GcpSecretClient` — 4-SPI composite over GCP Secret Manager + KMS SDKs.

中文
----
对位 Java `cn.richie696.component.secret.provider.gcp.GcpSecretClient`
(Java 端是 `AbstractRemoteProviderFactory` 抽象,Python 端按 GCP SDK
实际能力拆开):

- `SecretOperations` — `SecretManagerServiceClient.access_secret_version`
- `KeyWrappingBackend` — `KeyManagementServiceClient.encrypt` /
  `decrypt`
- `SecretBootstrapClient` — 批量 `access_secret_version`
- `SecretProviderSession` — lifecycle

**不**实现 `SigningBackend`(Java 端不暴露;session 的 `signing` 返回
`None`)。

GCP KMS API 跟 AWS 类似:用 `kms.encrypt(Plaintext=dek, Name=...)` 把
caller 的 DEK 包起来,`kms.decrypt(Ciphertext=blob, Name=...)` 解出来。
`Ciphertext` 是 byte string(类似 AWS 的 `CiphertextBlob`)。

错误映射:
- `google.api_core.exceptions.NotFound` →
  `SecretIntegrityException`(404 等价)
- `google.api_core.exceptions.Unauthorized` →
  `SecretException("SEC-AUTH-001")`
- `google.api_core.exceptions.PermissionDenied` →
  `SecretException("SEC-AUTHZ-001")`
- 5xx / ResourceExhausted → 重试后转译为
  `SecretException("SEC-PROVIDER-001")`(SDK 内置 retry)

English
--------
Composite client over GCP SDKs. Mirrors Java's 4-SPI scope
(no signing / no listing). SDK handles retries internally.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from google.api_core import exceptions as gapi_exceptions

from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyReference,
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
from atlas_richie.secret_gcp_kms.configuration import ResolvedGcpConfiguration

if TYPE_CHECKING:
    pass

_logger = logging.getLogger("atlas_richie.secret_gcp_kms.client")

_WRAPPING_ALGORITHM = "gcp-kms-symmetric"

_VERSION_LATEST = "latest"


class GcpSecretClient(
    SecretOperations,
    SecretBootstrapClient,
    SecretProviderSession,
):
    """Composite client for GCP Secret Manager + KMS.

    Implements 4 SPI roles: `SecretOperations`,
    `KeyWrappingBackend` (duck-typed), `SecretBootstrapClient`,
    `SecretProviderSession`. The session's `signing` /
    `writer` / `deletable` properties all return `None`.
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
        resolved: ResolvedGcpConfiguration,
        sm_client,
        kms_client,
        *,
        snapshot_manager: SecretSnapshotManager | None = None,
        close_action: Callable[[], None] | None = None,
        descriptor_backend: SecretBackend = SecretBackend.GCP,
    ) -> None:
        self._resolved = resolved
        self._sm_client = sm_client
        self._kms_client = kms_client
        self._snapshot_manager = snapshot_manager or SecretSnapshotManager()
        self._close_action = close_action
        self._closed = False
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
            retries=3,
            namespace=self._resolved.properties.project_id,
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
                "gcp: error during close_action for provider %r",
                self._resolved.provider_id,
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException(
                f"gcp: provider session {self._resolved.provider_id!r} is closed",
            )

    # --- SecretOperations Protocol --------------------------------------

    def get(self, reference: SecretReference) -> SecretValue:
        self._ensure_open()
        version = self._resolve_version_id(reference)
        return self._read(reference, version_id=version)

    def get_version(
        self,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        self._ensure_open()
        return self._read(reference, version_id=version.number)

    def get_metadata(self, reference: SecretReference) -> SecretMetadata:
        self._ensure_open()
        # `SecretManagerServiceClient` has no `describe_secret`
        # method distinct from `access_secret_version`; the
        # `Secret.payload` of the response carries the metadata
        # we need.
        version = self._resolve_version_id(reference)
        return self._read(reference, version_id=version).metadata

    def exists(self, reference: SecretReference) -> bool:
        self._ensure_open()
        try:
            self._read(reference, version_id=_VERSION_LATEST)
            return True
        except SecretIntegrityException:
            return False

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
                "gcp: wrap_key requires a non-empty DEK",
            )
        key_name = self._resolve_kms_key(kek)
        try:
            response = self._kms_client.encrypt(
                name=key_name,
                plaintext=dek,
            )
        except gapi_exceptions.GoogleAPIError as error:
            raise self._map_crypto_error("wrap_key", kek, error) from error
        return WrappedKey(
            kek_reference=kek,
            ciphertext=response.ciphertext,
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
                f"gcp: cannot unwrap a key with algorithm "
                f"{wrapped.algorithm!r}; expected {_WRAPPING_ALGORITHM!r}",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "gcp: wrapped ciphertext is empty",
            )
        key_name = self._resolve_kms_key(context.primary_key)
        try:
            response = self._kms_client.decrypt(
                name=key_name,
                ciphertext=wrapped.ciphertext,
            )
        except gapi_exceptions.GoogleAPIError as error:
            raise self._map_crypto_error(
                "unwrap_key", context.primary_key, error,
            ) from error
        return response.plaintext

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
                        f"gcp: bootstrap Secret binding "
                        f"{binding.name!r} is missing: {error}",
                    ) from error
                missing.append(binding.name)
                _logger.warning(
                    "gcp: bootstrap binding %r missing (required_when=%s); continuing",
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
        version_id: str,
    ) -> SecretValue:
        from google.cloud.secretmanager_v1 import AccessSecretVersionRequest
        # GCP secret name format: projects/{p}/secrets/{n}/versions/{v}
        if "/" in reference.path and "projects/" in reference.path:
            name = f"{reference.path}/versions/{version_id}"
        else:
            project = self._resolved.properties.project_id
            name = f"projects/{project}/secrets/{reference.path}/versions/{version_id}"
        try:
            request = AccessSecretVersionRequest(name=name)
            response = self._sm_client.access_secret_version(request=request)
        except gapi_exceptions.NotFound as error:
            raise SecretIntegrityException(
                f"gcp: secret not found at {reference.path!r}",
            ) from error
        except gapi_exceptions.GoogleAPIError as error:
            raise self._map_sm_error("get", error) from error
        secret_value = response.payload.data.decode("utf-8")
        actual_version = response.name.rsplit("/", 1)[-1]
        created_at = datetime.now(tz=timezone.utc)
        return SecretValue(
            plaintext=secret_value.encode("utf-8"),
            metadata=SecretMetadata(
                reference=reference,
                version=SecretVersion(
                    number=actual_version, created_at=created_at,
                ),
                backend=self._descriptor_backend,
                created_at=created_at,
                expires_at=None,
                tags={
                    "provider": "gcp",
                    "project": self._resolved.properties.project_id,
                },
            ),
        )

    def _resolve_version_id(self, reference: SecretReference) -> str:
        kind = reference.version_selector.kind
        if kind is SecretVersionSelectorKind.LATEST:
            return _VERSION_LATEST
        if kind is SecretVersionSelectorKind.STATIC:
            static = reference.version_selector.static_version
            if static is None:
                raise SecretConfigurationException(
                    "gcp: STATIC selector requires a static_version",
                )
            return static.number
        raise SecretConfigurationException(
            "gcp: PINNED_AT_TIME is not supported by Secret Manager; "
            "use LATEST or STATIC",
        )

    def _resolve_kms_key(self, reference: KeyReference) -> str:
        """Map `KeyReference.key_id` to a physical KMS key
        resource name (e.g. `projects/p/locations/L/keyRings/R/cryptoKeys/K`).
        """
        if not reference.key_id:
            raise SecretConfigurationException(
                f"gcp [SEC-KEY-001]: KeyReference {reference!r} has an empty key_id",
            )
        bindings = self._resolved.properties.kms_key_bindings
        if bindings and reference.key_id in bindings:
            physical = bindings[reference.key_id]
            if not physical:
                raise SecretConfigurationException(
                    f"gcp [SEC-KEY-001]: KMS key binding for "
                    f"{reference.key_id!r} is empty",
                )
            return physical
        return reference.key_id

    def _map_sm_error(
        self,
        operation: str,
        error: gapi_exceptions.GoogleAPIError,
    ) -> SecretException:
        if isinstance(error, gapi_exceptions.Unauthorized):
            return SecretException(
                f"gcp [SEC-AUTH-001]: {operation} was rejected: {error}",
            )
        if isinstance(error, gapi_exceptions.PermissionDenied):
            return SecretException(
                f"gcp [SEC-AUTHZ-001]: {operation} was rejected: {error}",
            )
        if isinstance(error, gapi_exceptions.ResourceExhausted):
            return SecretException(
                f"gcp [SEC-PROVIDER-001]: {operation} was throttled: {error}",
            )
        return SecretException(
            f"gcp [SEC-PROVIDER-001]: {operation} failed: {error}",
        )

    def _map_crypto_error(
        self,
        operation: str,
        key: KeyReference,
        error: gapi_exceptions.GoogleAPIError,
    ) -> SecretCryptoException:
        if isinstance(error, gapi_exceptions.Unauthorized):
            return SecretCryptoException(
                f"gcp [SEC-AUTH-001]: {operation} for key "
                f"{key.key_id!r} was rejected: {error}",
            )
        if isinstance(error, gapi_exceptions.PermissionDenied):
            return SecretCryptoException(
                f"gcp [SEC-AUTHZ-001]: {operation} for key "
                f"{key.key_id!r} was rejected: {error}",
            )
        if isinstance(error, gapi_exceptions.NotFound):
            return SecretCryptoException(
                f"gcp [SEC-KEY-001]: {operation} for key "
                f"{key.key_id!r} not found: {error}",
            )
        if isinstance(error, gapi_exceptions.ResourceExhausted):
            return SecretCryptoException(
                f"gcp [SEC-PROVIDER-001]: {operation} for key "
                f"{key.key_id!r} was throttled: {error}",
            )
        return SecretCryptoException(
            f"gcp [SEC-CRYPTO-001]: {operation} for key "
            f"{key.key_id!r} failed: {error}",
        )


__all__ = ["GcpSecretClient"]
