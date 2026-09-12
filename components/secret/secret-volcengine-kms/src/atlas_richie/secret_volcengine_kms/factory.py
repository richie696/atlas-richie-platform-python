"""Volcengine backend factory — `SecretProviderFactory` 入口 + SDK 适配。

中文
----
对位 Java `cn.richie696.component.secret.provider.volcengine.VolcengineSecretBootstrapProviderFactory`
(SDK 改造后只剩 ~10 行)。

`VolcengineClientFactory.create_kms(properties)`:
- **import-safe**:不强制 `volcengine-python-sdk` 已安装;SDK 在
  方法内 lazy import
- 构造 `ApiClient` with `set_endpoint` / `set_region` /
  `set_credential_provider(StaticCredentialProvider(ak, sk, token))`
- 构造 `KmsApi(api_client)`
- 把 SDK 客户端适配成 `KmsLike` Protocol(2 个方法)

`VolcengineSecretProviderFactory`(`SecretProviderFactory`
Protocol 实现):
- `name` = `f"volcengine-{namespace}-{region}"`
- `backend` = `SecretBackend.VOLCENGINE`
- `capability` = 静态声明(`can_read=False / can_write=False /
  can_rotate=False / can_list=False / encrypts_at_rest=True /
  signs_values=False / cacheable=False`,KMS-only)
- `version` = `"0.2.0"`
- `create(configuration) -> SecretProviderSession`:
  1. 用 `VolcengineClientFactory` 拿 `KmsLike`
  2. 用 `VolcengineConfigurationResolver` 拿
     `ResolvedVolcengineConfiguration`
  3. 构造 `VolcengineSecretClient`

错误转译:
- SDK 缺失 → `SecretConfigurationException("SEC-BOOT-003", ...)`

English
--------
`SecretProviderFactory` for the Volcengine backend. SDK
is imported lazily inside `create_kms` so the wheel is
import-safe without the SDK installed.
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
from atlas_richie.secret_volcengine_kms.client import (
    KmsLike,
    VolcengineKmsDecryptResponse,
    VolcengineKmsEncryptResponse,
    VolcengineSecretClient,
)
from atlas_richie.secret_volcengine_kms.configuration import (
    ResolvedVolcengineConfiguration,
    VolcengineConfigurationResolver,
)
from atlas_richie.secret_volcengine_kms.properties import VolcengineSecretProperties

_logger = logging.getLogger("atlas_richie.secret_volcengine_kms.factory")


@runtime_checkable
class _SdkClientFactory(Protocol):
    """Test seam: tests inject a pre-built `KmsLike`."""

    def __call__(self, properties: VolcengineSecretProperties) -> KmsLike: ...


def _volcengine_capability() -> SecretCapability:
    return SecretCapability(
        can_read=False,
        can_write=False,
        can_rotate=False,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=False,
    )


class _VolcengineSdkAdapter:
    """Adapter from `volcengine-python-sdk` KmsApi to `KmsLike` Protocol."""

    def __init__(self, kms: object) -> None:
        self._kms = kms

    def encrypt(
        self,
        keyring_name: str,
        key_name: str,
        plaintext_b64: str,
        encryption_context,
    ) -> VolcengineKmsEncryptResponse:
        request = self._models().EncryptRequest()
        request.keyring_name = keyring_name
        request.key_name = key_name
        request.plaintext = plaintext_b64
        request.encryption_context = dict(encryption_context)
        response = self._kms.encrypt(request)
        return VolcengineKmsEncryptResponse(
            ciphertext_blob=str(getattr(response, "ciphertext_blob", "") or ""),
        )

    def decrypt(
        self,
        ciphertext_blob: str,
        encryption_context,
    ) -> VolcengineKmsDecryptResponse:
        request = self._models().DecryptRequest()
        request.ciphertext_blob = ciphertext_blob
        request.encryption_context = dict(encryption_context)
        response = self._kms.decrypt(request)
        return VolcengineKmsDecryptResponse(
            plaintext=str(getattr(response, "plaintext", "") or ""),
        )

    def _models(self) -> object:
        from volcengine.kms import model  # type: ignore[import-not-found]
        return model


def _default_kms_factory(properties: VolcengineSecretProperties) -> KmsLike:
    try:
        from volcengine.ApiClient import ApiClient  # type: ignore[import-not-found]
        from volcengine.auth import StaticCredentialProvider  # type: ignore[import-not-found]
        from volcengine.kms.KmsApi import KmsApi  # type: ignore[import-not-found]
    except ImportError as error:
        raise SecretConfigurationException(
            f"volcengine: SDK not installed ({error.name!r}); "
            f"pip install 'atlas-richie-secret-volcengine-kms[sdk]' "
            f"(SEC-BOOT-003)",
        ) from error
    try:
        client = ApiClient()
        endpoint = properties.kms_endpoint or f"https://kms.{properties.region}.volcengineapi.com"
        client.endpoint = endpoint
        client.region = properties.region
        creds = StaticCredentialProvider(
            ak=properties.access_key_id,
            sk=properties.access_key_secret,
            security_token=properties.security_token or "",
        )
        client.credential_provider = creds
        return _VolcengineSdkAdapter(KmsApi(client))
    except SecretConfigurationException:
        raise
    except Exception as error:  # noqa: BLE001
        raise SecretConfigurationException(
            f"volcengine: cannot initialize KMS SDK "
            f"(region={properties.region!r}): {error} (SEC-PROVIDER-001)",
        ) from error


class VolcengineClientFactory:
    """Build a `KmsLike` from `VolcengineSecretProperties`."""

    __slots__ = ()

    def create_kms(self, properties: VolcengineSecretProperties) -> KmsLike:
        return _default_kms_factory(properties)


class VolcengineSecretProviderFactory:
    """`SecretProviderFactory` for the Volcengine backend."""

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
        properties: VolcengineSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: Callable[[VolcengineSecretProperties], KmsLike] | None = None,
        configuration_resolver: VolcengineConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.VOLCENGINE,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._client_factory = client_factory or _default_kms_factory
        self._configuration_resolver = (
            configuration_resolver or VolcengineConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> VolcengineSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"volcengine-{self._properties.namespace}-{self._properties.region}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return _volcengine_capability()

    @property
    def version(self) -> str:
        return self._version

    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self.name,
            backend=self.backend,
            capability=self.capability,
            version=self.version,
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
        kms = self._client_factory(self._properties)
        resolved: ResolvedVolcengineConfiguration = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        return VolcengineSecretClient(
            resolved=resolved,
            kms=kms,
            descriptor_backend=self._descriptor_backend,
        )


__all__ = [
    "VolcengineClientFactory",
    "VolcengineSecretProviderFactory",
]
