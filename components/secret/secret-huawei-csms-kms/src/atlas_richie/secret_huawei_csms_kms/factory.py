"""Huawei backend factory — `SecretProviderFactory` 入口 + SDK 适配。

中文
----
对位 Java `cn.richie696.component.secret.provider.huawei.HuaweiSecretBootstrapProviderFactory`
(SDK 改造后只剩 ~10 行,因为 SDK 适配拆到了 `HuaweiSdkSecretTransport`)。

`HuaweiClientFactory.create_clients(properties)`:
- **import-safe**:不强制 `huaweicloud-sdk-python` 已安装;SDK 在
  方法内 lazy import(对位 R-232 决定)
- 构造 `BasicCredentials().with_ak(...).with_sk(...).with_project_id(...)`
- 构造 `CsmsClient.new_builder().with_credentials(...).with_endpoint(...).build()`
  + `KmsClient.new_builder()...build()`
- 把 SDK 客户端适配成 `CsmsLike` / `KmsLike` Protocol(3 个方法)

`HuaweiSecretProviderFactory`(`SecretProviderFactory`
Protocol 实现):
- `name` = `f"huawei-{region}"`
- `backend` = `SecretBackend.HUAWEI`
- `capability` = 静态声明(`can_read=True / can_write=False /
  can_rotate=True / can_list=False / encrypts_at_rest=True /
  signs_values=False / cacheable=True`,对位 Java 3-SPI scope)
- `version` = `"0.2.0"`
- `create(configuration) -> SecretProviderSession`:
  1. 用 `HuaweiClientFactory` 拿 `CsmsLike` + `KmsLike`
  2. 用 `HuaweiConfigurationResolver` 拿
     `ResolvedHuaweiConfiguration`
  3. 构造 `HuaweiSecretClient`

错误转译:
- SDK 缺失 / 不可导入 → `SecretConfigurationException("SEC-BOOT-003", ...)`
- SDK 初始化失败 → `SecretConfigurationException("SEC-PROVIDER-001", ...)`

English
--------
`SecretProviderFactory` for the Huawei backend. The
Huawei SDK is imported lazily inside `create_clients`
so the wheel is import-safe even without the SDK
installed (matches the `optional-dependency` convention
from R-232).
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
from atlas_richie.secret_huawei_csms_kms.client import (
    CsmsLike,
    HuaweiCsmsGetResponse,
    HuaweiKmsDecryptResponse,
    HuaweiKmsEncryptResponse,
    HuaweiSecretClient,
    KmsLike,
)
from atlas_richie.secret_huawei_csms_kms.configuration import (
    HuaweiConfigurationResolver,
    ResolvedHuaweiConfiguration,
)
from atlas_richie.secret_huawei_csms_kms.properties import HuaweiSecretProperties

_logger = logging.getLogger("atlas_richie.secret_huawei_csms_kms.factory")


@runtime_checkable
class _SdkClientFactory(Protocol):
    """Test seam: tests inject a pre-built `(CsmsLike, KmsLike)` pair."""

    def __call__(
        self, properties: HuaweiSecretProperties,
    ) -> tuple[CsmsLike, KmsLike]: ...


def _huawei_capability() -> SecretCapability:
    return SecretCapability(
        can_read=True,
        can_write=False,
        can_rotate=True,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


class _HuaweiSdkAdapter:
    """Adapter from `huaweicloud-sdk-python` Clients to
    `CsmsLike` / `KmsLike` Protocols. SDK types never leave
    this class.
    """

    def __init__(self, csms: object, kms: object) -> None:
        self._csms = csms
        self._kms = kms

    # CsmsLike
    def show_secret_version(
        self, secret_name: str, version_id: str | None,
    ) -> HuaweiCsmsGetResponse:
        request = self._csms_models().ShowSecretVersionRequest()
        request.secret_name = secret_name
        if version_id is not None:
            request.version_id = version_id
        response = self._csms.show_secret_version(request)
        version = getattr(response, "version", None)
        metadata = getattr(version, "version_metadata", None) if version else None
        return HuaweiCsmsGetResponse(
            secret_name=str(getattr(response, "secret_name", secret_name)),
            version_id=str(getattr(metadata, "id", "") or "") if metadata else "",
            secret_string=str(getattr(version, "secret_string", "") or "") if version else "",
            secret_binary=str(getattr(version, "secret_binary", "") or "") if version else "",
            create_time=getattr(metadata, "create_time", None) if metadata else None,
        )

    # KmsLike
    def encrypt_data(
        self,
        key_id: str,
        plain_text_b64: str,
        aad_b64: str | None,
    ) -> HuaweiKmsEncryptResponse:
        body = self._kms_models().EncryptDataRequestBody()
        body.key_id = key_id
        body.plain_text = plain_text_b64
        if aad_b64 is not None:
            body.additional_authenticated_data = aad_b64
        request = self._kms_models().EncryptDataRequest()
        request.body = body
        response = self._kms.encrypt_data(request)
        return HuaweiKmsEncryptResponse(
            cipher_text=str(getattr(response, "cipher_text", "") or ""),
        )

    def decrypt_data(
        self,
        cipher_text: str,
        aad_b64: str | None,
    ) -> HuaweiKmsDecryptResponse:
        body = self._kms_models().DecryptDataRequestBody()
        body.cipher_text = cipher_text
        if aad_b64 is not None:
            body.additional_authenticated_data = aad_b64
        request = self._kms_models().DecryptDataRequest()
        request.body = body
        response = self._kms.decrypt_data(request)
        return HuaweiKmsDecryptResponse(
            plain_text=str(getattr(response, "plain_text", "") or ""),
            plain_text_base64=str(getattr(response, "plain_text_base64", "") or ""),
        )

    def _csms_models(self) -> object:
        from huaweicloudsdkcsms.v1 import (  # type: ignore[import-not-found]
            model,
        )
        return model

    def _kms_models(self) -> object:
        from huaweicloudsdkkms.v2 import (  # type: ignore[import-not-found]
            model,
        )
        return model


def _default_pair_factory(
    properties: HuaweiSecretProperties,
) -> tuple[CsmsLike, KmsLike]:
    try:
        from huaweicloudsdkcore.auth.basic_credentials import (  # type: ignore[import-not-found]
            BasicCredentials,
        )
        from huaweicloudsdkcsms.v1.csms_client import (  # type: ignore[import-not-found]
            CsmsClient,
        )
        from huaweicloudsdkkms.v2.kms_client import (  # type: ignore[import-not-found]
            KmsClient,
        )
    except ImportError as error:
        raise SecretConfigurationException(
            f"huawei: SDK not installed ({error.name!r}); "
            f"pip install 'atlas-richie-secret-huawei-csms-kms[sdk]' "
            f"(SEC-BOOT-003)",
        ) from error
    try:
        credentials = (
            BasicCredentials(
                properties.access_key_id,
                properties.access_key_secret,
                properties.project_id,
                properties.security_token or None,
            )
        )
        csms_endpoint = (
            properties.secret_endpoint
            or f"https://csms.{properties.region}.myhuaweicloud.com"
        )
        kms_endpoint = (
            properties.kms_endpoint
            or f"https://kms.{properties.region}.myhuaweicloud.com"
        )
        csms = CsmsClient.new_builder() \
            .with_credentials(credentials) \
            .with_endpoint(csms_endpoint) \
            .build()
        kms = KmsClient.new_builder() \
            .with_credentials(credentials) \
            .with_endpoint(kms_endpoint) \
            .build()
        return _HuaweiSdkAdapter(csms, kms), _HuaweiSdkAdapter(csms, kms)
    except SecretConfigurationException:
        raise
    except Exception as error:  # noqa: BLE001
        raise SecretConfigurationException(
            f"huawei: cannot initialize SDK clients "
            f"(region={properties.region!r}): {error} (SEC-PROVIDER-001)",
        ) from error


class HuaweiClientFactory:
    """Build `(CsmsLike, KmsLike)` from `HuaweiSecretProperties`."""

    __slots__ = ()

    def create_clients(
        self, properties: HuaweiSecretProperties,
    ) -> tuple[CsmsLike, KmsLike]:
        return _default_pair_factory(properties)


class HuaweiSecretProviderFactory:
    """`SecretProviderFactory` for the Huawei backend."""

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
        properties: HuaweiSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: Callable[[HuaweiSecretProperties], tuple[CsmsLike, KmsLike]] | None = None,
        configuration_resolver: HuaweiConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.HUAWEI,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._client_factory = client_factory or _default_pair_factory
        self._configuration_resolver = (
            configuration_resolver or HuaweiConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> HuaweiSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"huawei-{self._properties.region}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return _huawei_capability()

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
        csms, kms = self._client_factory(self._properties)
        resolved: ResolvedHuaweiConfiguration = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        return HuaweiSecretClient(
            resolved=resolved,
            csms=csms,
            kms=kms,
            descriptor_backend=self._descriptor_backend,
        )


__all__ = [
    "HuaweiClientFactory",
    "HuaweiSecretProviderFactory",
]
