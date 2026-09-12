"""OCI backend factory — `SecretProviderFactory` entry + SDK 适配。

中文
----
对位 Java `cn.richie696.component.secret.provider.oci.OciSecretBootstrapProviderFactory`
(SDK 改造后只剩 ~10 行)。

`OciClientFactory`:
- `create_vault(properties) -> VaultLike` — 构造
  `oci.secrets.SecretsClient` (endpoint 来自 `secret_endpoint`,
  走 `InstancePrincipalsAuthenticationDetailsProvider` 或
  `ResourcePrincipalAuthenticationDetailsProvider`)
- `create_kms(properties) -> KmsLike` — 构造
  `oci.keymanagement.KmsCryptoClient` (endpoint 来自
  `kms_endpoint`)

`OciSecretProviderFactory`(`SecretProviderFactory` Protocol):
- `name` = `f"oci-{region}"`
- `backend` = `SecretBackend.OCI`
- `capability` = 静态声明
  (`can_read=True / can_write=False / can_rotate=True /
  can_list=False / encrypts_at_rest=True / signs_values=False /
  cacheable=True`)
- `version` = `"0.2.0"`
- `create(configuration) -> SecretProviderSession`:
  1. 用 `OciClientFactory` 拿 `VaultLike` + `KmsLike`
  2. 用 `OciConfigurationResolver` 拿
     `ResolvedOciConfiguration`
  3. 构造 `OciSecretClient`

错误转译:
- SDK 缺失 → `SecretConfigurationException("SEC-BOOT-003", ...)`
- 不支持的 auth_type → `SecretConfigurationException("SEC-BOOT-003", ...)`
- SDK 构造任意错误 → `SecretConfigurationException("SEC-PROVIDER-001", ...)`

English
--------
`SecretProviderFactory` for the OCI Vault + KMS backend.
SDK is imported lazily inside `create_vault` / `create_kms`
so the wheel is import-safe without the SDK installed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret_oci_vault_kms.client import (
    KmsLike,
    OciKmsDecryptResponse,
    OciKmsEncryptResponse,
    OciSecretClient,
    OciVaultSecret,
    VaultLike,
)
from atlas_richie.secret_oci_vault_kms.configuration import (
    OciConfigurationResolver,
    ResolvedOciConfiguration,
)
from atlas_richie.secret_oci_vault_kms.properties import (
    AuthType,
    OciSecretProperties,
)

_logger = logging.getLogger("atlas_richie.secret_oci_vault_kms.factory")


@runtime_checkable
class _SdkClientFactory(Protocol):
    """Test seam: tests inject pre-built `VaultLike` + `KmsLike`."""

    def __call__(  # type: ignore[no-untyped-def]
        self,
        properties: OciSecretProperties,
    ) -> tuple[VaultLike, KmsLike]: ...


def _oci_capability() -> SecretCapability:
    return SecretCapability(
        can_read=True,
        can_write=False,
        can_rotate=True,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


# ---------------------------------------------------------------------------
# SDK adapters (translate OCI SDK request / response model fields to Protocol)
# ---------------------------------------------------------------------------


class _OciVaultAdapter:
    """Adapter from `oci.secrets.SecretsClient` to `VaultLike` Protocol."""

    def __init__(self, secrets: object) -> None:
        self._secrets = secrets

    def get_secret_bundle(
        self,
        secret_id: str,
        version_number: int | None,
        stage: str | None,
        secret_version_name: str | None,
    ) -> OciVaultSecret | None:
        request = self._models().GetSecretBundleRequest()
        request.secret_id = secret_id
        if version_number is not None:
            request.version_number = version_number
        if stage is not None and stage.strip():
            request.stage = self._stage_enum(stage)
        if secret_version_name is not None and secret_version_name.strip():
            request.secret_version_name = secret_version_name
        try:
            response = self._secrets.get_secret_bundle(request)
        except Exception as error:  # noqa: BLE001
            # Bubble up — `_is_not_found` is in the client.
            raise error
        bundle = getattr(response, "data", None)
        if bundle is None:
            return None
        raw_content_obj = getattr(bundle, "secret_bundle_content", None)
        if raw_content_obj is None:
            return None
        encoded = getattr(raw_content_obj, "content", None)
        if not isinstance(encoded, str) or not encoded:
            return None
        import base64 as _b64

        try:
            decoded = _b64.b64decode(encoded, validate=False)
        except Exception:  # noqa: BLE001
            return None
        return OciVaultSecret(
            secret_id=secret_id,
            version_name=str(getattr(bundle, "version_name", "") or ""),
            content=decoded,
            create_time=getattr(bundle, "time_created", None),
        )

    @staticmethod
    def _stage_enum(stage_value: str) -> object:
        models = _OciVaultAdapter._models()
        stage_cls = getattr(models, "GetSecretBundleRequestDetails", None)
        if stage_cls is None:
            return stage_value.upper()
        stage_member = getattr(stage_cls, "STAGE", None)
        if stage_member is None:
            return stage_value.upper()
        # OCI SDK exposes Stage enum (CURRENT / PENDING / PREVIOUS / LATEST / DEPRECATED)
        for name in (stage_value.upper(), "CURRENT", "PENDING", "LATEST"):
            member = getattr(stage_member, name, None)
            if member is not None:
                return member
        return stage_value.upper()

    @staticmethod
    def _models() -> object:
        from oci.secrets import models  # type: ignore[import-not-found]
        return models


class _OciKmsAdapter:
    """Adapter from `oci.key_management.KmsCryptoClient` to `KmsLike`."""

    def __init__(self, kms: object) -> None:
        self._kms = kms

    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
        associated_data: dict[str, str] | None,
    ) -> OciKmsEncryptResponse:
        models = self._models()
        details = models.EncryptDataDetails()
        details.key_id = key_id
        details.plaintext = plaintext_b64
        if associated_data:
            details.associated_data = dict(associated_data)
        request = models.EncryptRequest()
        request.encrypt_data_details = details
        response = self._kms.encrypt(request)
        encrypted = getattr(response, "data", None) or getattr(
            response, "encrypted_data", None,
        )
        ciphertext = getattr(encrypted, "ciphertext", "") if encrypted else ""
        return OciKmsEncryptResponse(ciphertext=str(ciphertext or ""))

    def decrypt(
        self,
        key_id: str,
        ciphertext: str,
        associated_data: dict[str, str] | None,
    ) -> OciKmsDecryptResponse:
        models = self._models()
        details = models.DecryptDataDetails()
        details.key_id = key_id
        details.ciphertext = ciphertext
        if associated_data:
            details.associated_data = dict(associated_data)
        request = models.DecryptRequest()
        request.decrypt_data_details = details
        response = self._kms.decrypt(request)
        decrypted = getattr(response, "data", None) or getattr(
            response, "decrypted_data", None,
        )
        plaintext = getattr(decrypted, "plaintext", "") if decrypted else ""
        return OciKmsDecryptResponse(plaintext=str(plaintext or ""))

    @staticmethod
    def _models() -> object:
        from oci.key_management import models  # type: ignore[import-not-found]
        return models


# ---------------------------------------------------------------------------
# Default SDK factory (lazy imports)
# ---------------------------------------------------------------------------


def _import_oci_sdk() -> tuple[object, object, object, object]:
    """Lazy import of OCI SDK. Returns
    (SecretsClient, KmsCryptoClient, InstancePrincipalsADP,
    ResourcePrincipalADP).
    """
    try:
        from oci.secrets import SecretsClient  # type: ignore[import-not-found]
        from oci.key_management import KmsCryptoClient  # type: ignore[import-not-found]
        from oci.auth import (  # type: ignore[import-not-found]
            InstancePrincipalsAuthenticationDetailsProvider,
            ResourcePrincipalAuthenticationDetailsProvider,
        )
    except ImportError as error:
        raise SecretConfigurationException(
            f"oci: SDK not installed ({error.name!r}); "
            f"pip install 'atlas-richie-secret-oci-vault-kms[sdk]' "
            f"(SEC-BOOT-003)",
        ) from error
    return (
        SecretsClient,
        KmsCryptoClient,
        InstancePrincipalsAuthenticationDetailsProvider,
        ResourcePrincipalAuthenticationDetailsProvider,
    )


def _build_principal(
    auth_type: AuthType,
    instance_cls: object,
    resource_cls: object,
):
    if auth_type is AuthType.NONE:
        return instance_cls()  # type: ignore[call-arg]
    if auth_type is AuthType.WORKLOAD_IDENTITY_TOKEN_FILE:
        return resource_cls()  # type: ignore[call-arg]
    raise SecretConfigurationException(
        f"oci: auth_type must be NONE or WORKLOAD_IDENTITY_TOKEN_FILE; "
        f"got {auth_type!r} (SEC-BOOT-003)",
    )


def _default_client_factory(properties: OciSecretProperties) -> tuple[VaultLike, KmsLike]:
    SecretsClient, KmsCryptoClient, InstancePrincipalsADP, ResourcePrincipalADP = _import_oci_sdk()
    if properties.secret_endpoint is None or not properties.secret_endpoint.strip():
        raise SecretConfigurationException(
            "oci: secret_endpoint is required for SDK construction (SEC-BOOT-003)",
        )
    if properties.kms_endpoint is None or not properties.kms_endpoint.strip():
        raise SecretConfigurationException(
            "oci: kms_endpoint is required for SDK construction (SEC-BOOT-003)",
        )
    try:
        principal = _build_principal(
            properties.auth_type,
            InstancePrincipalsADP,
            ResourcePrincipalADP,
        )
        secrets = SecretsClient(
            principal=principal,
            endpoint=properties.secret_endpoint,
        )
        kms = KmsCryptoClient(
            principal=principal,
            endpoint=properties.kms_endpoint,
        )
    except SecretConfigurationException:
        raise
    except Exception as error:  # noqa: BLE001
        raise SecretConfigurationException(
            f"oci: cannot initialize SDK "
            f"(region={properties.region!r}, auth={properties.auth_type.value!r}): "
            f"{error} (SEC-PROVIDER-001)",
        ) from error
    return _OciVaultAdapter(secrets), _OciKmsAdapter(kms)


# ---------------------------------------------------------------------------
# Public factories
# ---------------------------------------------------------------------------


class OciClientFactory:
    """Build a `VaultLike` + `KmsLike` from `OciSecretProperties`."""

    __slots__ = ()

    def create(
        self,
        properties: OciSecretProperties,
    ) -> tuple[VaultLike, KmsLike]:
        return _default_client_factory(properties)


class OciSecretProviderFactory:
    """`SecretProviderFactory` for the OCI Vault + KMS backend."""

    __slots__ = (
        "_client_factory",
        "_configuration_resolver",
        "_descriptor_backend",
        "_name_override",
        "_properties",
        "_version",
    )

    def __init__(
        self,
        properties: OciSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: Callable[[OciSecretProperties], tuple[VaultLike, KmsLike]] | None = None,
        configuration_resolver: OciConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.OCI,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._client_factory = client_factory or _default_client_factory
        self._configuration_resolver = (
            configuration_resolver or OciConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> OciSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"oci-{self._properties.region}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return _oci_capability()

    @property
    def version(self) -> str:
        return self._version

    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self.name,
            backend=self.backend,
            capability=self.capability,
            version=self._version,
        )

    def default_configuration(self) -> SecretProviderConfiguration:
        return SecretProviderConfiguration(
            name=self.name,
            parameters={},
            timeout_seconds=self._properties.read_timeout_seconds,
            retries=self._properties.max_attempts,
            namespace=self._properties.region,
        )

    def create(
        self,
        configuration: SecretProviderConfiguration,
    ) -> SecretProviderSession:
        vault, kms = self._client_factory(self._properties)
        resolved: ResolvedOciConfiguration = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        return OciSecretClient(
            resolved=resolved,
            vault=vault,
            kms=kms,
            descriptor_backend=self._descriptor_backend,
        )


__all__ = [
    "OciClientFactory",
    "OciSecretProviderFactory",
]
