"""`AzureSecretClient` — 4-SPI composite over Azure Key Vault SDKs.

中文
----
对位 Java `cn.richie696.component.secret.provider.azure.AzureSecretClient`
(具体类 Java 端在 `AbstractRemoteProviderFactory` 公共类里,
Python 端按 Azure SDK 实际能力拆开):

- `SecretOperations` — `azure-keyvault-secrets.SecretClient.get_secret`
- `KeyWrappingBackend` — `azure-keyvault-keys.KeyClient.wrap_key` /
  `unwrap_key`(local-cryptographic ops,不需要远端调用)
- `SecretBootstrapClient` — 批量 `SecretClient.get_secret`
- `SecretProviderSession` — lifecycle

**不**实现:
- `SigningBackend`(Java Azure 不暴露;session 的 `signing` 返回 `None`)
- `SecretWriter` / `SecretDeletable`(Java 端同)
- `SecretListable`(`can_list=False`)

错误映射:
- `azure.core.exceptions.ResourceNotFoundError` →
  `SecretIntegrityException`(404 等价)
- `azure.core.exceptions.ClientAuthenticationError` →
  `SecretException("SEC-AUTH-001")`
- `azure.core.exceptions.HttpResponseError` 5xx → 重试后 →
  `SecretException("SEC-PROVIDER-001")`

English
--------
Composite client over Azure SDKs. Mirrors Java's narrower 4-SPI
scope (no signing / no listing). boto3-style retry is delegated
to the SDK's built-in pipeline; the client only maps final
exceptions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)

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
from atlas_richie.secret_azure_keyvault.configuration import ResolvedAzureConfiguration

if TYPE_CHECKING:
    pass

_logger = logging.getLogger("atlas_richie.secret_azure_keyvault.client")

# 1:1 with Java wrap algorithm constant
_WRAPPING_ALGORITHM = "azure-keyvault-local-wrap"


class AzureSecretClient(
    SecretOperations,
    SecretBootstrapClient,
    SecretProviderSession,
):
    """Composite client for Azure Key Vault (Secrets + Keys).

    Implements 4 SPI roles: `SecretOperations`,
    `KeyWrappingBackend` (duck-typed), `SecretBootstrapClient`,
    `SecretProviderSession`. The session's `signing` /
    `writer` / `deletable` properties all return `None` —
    matching Java's narrower 4-SPI surface.

    Constructor parameters:

    - `resolved`: immutable `ResolvedAzureConfiguration`
    - `secret_client`: a `SecretClient` (from
      `azure-keyvault-secrets`)
    - `key_client`: a `KeyClient` (from `azure-keyvault-keys`)
    - `snapshot_manager`: optional `SecretSnapshotManager`
    - `close_action`: optional callable invoked from `close()`
    """

    __slots__ = (
        "_closed",
        "_close_action",
        "_descriptor_backend",
        "_key_client",
        "_resolved",
        "_secret_client",
        "_snapshot_manager",
    )

    def __init__(
        self,
        resolved: ResolvedAzureConfiguration,
        secret_client,
        key_client,
        *,
        snapshot_manager: SecretSnapshotManager | None = None,
        close_action: Callable[[], None] | None = None,
        descriptor_backend: SecretBackend = SecretBackend.AZURE,
    ) -> None:
        self._resolved = resolved
        self._secret_client = secret_client
        self._key_client = key_client
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
            namespace=self._resolved.properties.vault_url,
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
        # Mirrors Java: Azure backend does not expose sign /
        # verify. Returning `None` makes the capability
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
        if self._close_action is None:
            return
        try:
            self._close_action()
        except Exception:  # noqa: BLE001
            _logger.exception(
                "azure: error during close_action for provider %r",
                self._resolved.provider_id,
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException(
                f"azure: provider session {self._resolved.provider_id!r} is closed",
            )

    # --- SecretOperations Protocol --------------------------------------

    def get(self, reference: SecretReference) -> SecretValue:
        self._ensure_open()
        # Resolve the reference's version_selector to a concrete
        # Azure `version` argument. STATIC → pass the version
        # number; LATEST (or anything else) → omit, which makes
        # `SecretClient.get_secret` return the current version.
        version = self._resolve_version_id(reference)
        return self._read(reference, version=version)

    def get_version(
        self,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        self._ensure_open()
        return self._read(reference, version=version.number)

    def get_metadata(self, reference: SecretReference) -> SecretMetadata:
        self._ensure_open()
        from azure.keyvault.secrets import SecretProperties
        try:
            props: SecretProperties = self._secret_client.get_secret(reference.path).properties
        except ResourceNotFoundError as error:
            raise SecretIntegrityException(
                f"azure: secret not found at {reference.path!r}",
            ) from error
        except HttpResponseError as error:
            raise self._map_http_error("get_metadata", error) from error
        created_at = props.created_on or datetime.now(tz=timezone.utc)
        return SecretMetadata(
            reference=reference,
            version=SecretVersion(number=props.version or "current", created_at=created_at),
            backend=self._descriptor_backend,
            created_at=created_at,
            expires_at=props.expires_on,
            tags={"provider": "azure", "vault": self._resolved.properties.vault_url},
        )

    def exists(self, reference: SecretReference) -> bool:
        self._ensure_open()
        try:
            self._secret_client.get_secret(reference.path)
            return True
        except ResourceNotFoundError:
            return False
        except HttpResponseError as error:
            raise self._map_http_error("exists", error) from error

    # --- KeyWrappingBackend (duck-typed) --------------------------------

    def wrap_key(
        self,
        dek: bytes,
        kek: KeyReference,
        *,
        algorithm: str | None = None,
    ) -> WrappedKey:
        self._ensure_open()
        if not dek:
            raise SecretCryptoException(
                "azure: wrap_key requires a non-empty DEK",
            )
        key_name = self._resolve_key_name(kek)
        wrap_algorithm = (
            algorithm
            or self._resolved.properties.default_key_wrap_algorithm.value
        )
        try:
            from azure.keyvault.keys.crypto import KeyWrapAlgorithm
            result = self._key_client.wrap_key(
                key_name,
                algorithm=KeyWrapAlgorithm.wrap_algorithm_id_to_wrapped_algorithm(
                    key_name, wrap_algorithm,
                ) if hasattr(
                    KeyWrapAlgorithm, "wrap_algorithm_id_to_wrapped_algorithm",
                ) else wrap_algorithm,
                value=dek,
            )
        except HttpResponseError as error:
            raise self._map_crypto_error("wrap_key", kek, error) from error
        return WrappedKey(
            kek_reference=kek,
            ciphertext=result.encrypted_key,
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
                f"azure: cannot unwrap a key with algorithm "
                f"{wrapped.algorithm!r}; expected {_WRAPPING_ALGORITHM!r}",
            )
        if not wrapped.ciphertext:
            raise SecretCryptoException(
                "azure: wrapped ciphertext is empty",
            )
        key_name = self._resolve_key_name(context.primary_key)
        try:
            result = self._key_client.unwrap_key(key_name, value=wrapped.ciphertext)
        except HttpResponseError as error:
            raise self._map_crypto_error(
                "unwrap_key", context.primary_key, error,
            ) from error
        return result.key

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
                        f"azure: bootstrap Secret binding "
                        f"{binding.name!r} is missing: {error}",
                    ) from error
                missing.append(binding.name)
                _logger.warning(
                    "azure: bootstrap binding %r missing (required_when=%s); continuing",
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
        version: str | None,
    ) -> SecretValue:
        try:
            from azure.keyvault.secrets import KeyVaultSecret
            secret: KeyVaultSecret = self._secret_client.get_secret(
                reference.path, version=version,
            )
        except ResourceNotFoundError as error:
            raise SecretIntegrityException(
                f"azure: secret not found at {reference.path!r}",
            ) from error
        except HttpResponseError as error:
            raise self._map_http_error("get", error) from error
        properties = secret.properties
        created_at = properties.created_on or datetime.now(tz=timezone.utc)
        return SecretValue(
            plaintext=secret.value.encode("utf-8"),
            metadata=SecretMetadata(
                reference=reference,
                version=SecretVersion(
                    number=properties.version or "current",
                    created_at=created_at,
                ),
                backend=self._descriptor_backend,
                created_at=created_at,
                expires_at=properties.expires_on,
                tags={
                    "provider": "azure",
                    "vault": self._resolved.properties.vault_url,
                },
            ),
        )

    def _resolve_version_id(self, reference: SecretReference) -> str | None:
        """Map `SecretReference.version_selector` to an Azure
        `version` argument.

        - `LATEST` → returns `None` (Azure `SecretClient` omits
          `version`, returning the current version).
        - `STATIC` → returns the binding's
          `static_version.number` (the AKV-assigned GUID).
        - `PINNED_AT_TIME` → not supported (raises
          `SecretConfigurationException`).
        """
        kind = reference.version_selector.kind
        if kind is SecretVersionSelectorKind.LATEST:
            return None
        if kind is SecretVersionSelectorKind.STATIC:
            static = reference.version_selector.static_version
            if static is None:
                raise SecretConfigurationException(
                    "azure: STATIC selector requires a static_version",
                )
            return static.number
        raise SecretConfigurationException(
            "azure: PINNED_AT_TIME is not supported by Azure Key Vault; "
            "use LATEST or STATIC",
        )

    def _resolve_key_name(self, reference: KeyReference) -> str:
        """Map `KeyReference.key_id` to a physical Key Vault key
        name. Mirrors the vault / AWS `key_bindings` pattern:
        `key_bindings[logical]` → physical name, else use
        `key_id` directly.
        """
        if not reference.key_id:
            raise SecretConfigurationException(
                f"azure [SEC-KEY-001]: KeyReference {reference!r} "
                "has an empty key_id",
            )
        bindings = self._resolved.properties.key_bindings
        if bindings and reference.key_id in bindings:
            physical = bindings[reference.key_id]
            if not physical:
                raise SecretConfigurationException(
                    f"azure [SEC-KEY-001]: key binding for "
                    f"{reference.key_id!r} is empty",
                )
            return physical
        return reference.key_id

    def _map_http_error(
        self,
        operation: str,
        error: HttpResponseError,
    ) -> SecretException:
        status = getattr(error, "status_code", None)
        if status == 401:
            return SecretException(
                f"azure [SEC-AUTH-001]: {operation} was rejected: {error}",
            )
        if status == 403:
            return SecretException(
                f"azure [SEC-AUTHZ-001]: {operation} was rejected: {error}",
            )
        if status == 404:
            return SecretIntegrityException(
                f"azure: {operation} not found: {error}",
            )
        if isinstance(status, int) and 500 <= status < 600:
            return SecretException(
                f"azure [SEC-PROVIDER-001]: {operation} failed: {error}",
            )
        return SecretException(
            f"azure [SEC-PROVIDER-001]: {operation} failed: {error}",
        )

    def _map_crypto_error(
        self,
        operation: str,
        key: KeyReference,
        error: HttpResponseError,
    ) -> SecretCryptoException:
        status = getattr(error, "status_code", None)
        if status == 401:
            return SecretCryptoException(
                f"azure [SEC-AUTH-001]: {operation} for key "
                f"{key.key_id!r} was rejected: {error}",
            )
        if status == 403:
            return SecretCryptoException(
                f"azure [SEC-AUTHZ-001]: {operation} for key "
                f"{key.key_id!r} was rejected: {error}",
            )
        if status == 404:
            return SecretCryptoException(
                f"azure [SEC-KEY-001]: {operation} for key "
                f"{key.key_id!r} not found: {error}",
            )
        if isinstance(status, int) and 500 <= status < 600:
            return SecretCryptoException(
                f"azure [SEC-PROVIDER-001]: {operation} for key "
                f"{key.key_id!r} failed: {error}",
            )
        return SecretCryptoException(
            f"azure [SEC-CRYPTO-001]: {operation} for key "
            f"{key.key_id!r} failed: {error}",
        )


__all__ = ["AzureSecretClient"]
