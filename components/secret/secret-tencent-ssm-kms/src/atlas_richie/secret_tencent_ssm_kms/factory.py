"""Tencent backend factory — `SecretProviderFactory` 入口 + SDK 适配。

中文
----
对位 Java `cn.richie696.component.secret.provider.tencent.TencentSecretBootstrapProviderFactory`
(SDK 改造后只剩 ~10 行,因为 SDK 适配拆到了 `TencentSdkSecretTransport`)。

`TencentClientFactory.create_clients(properties)`:
- **import-safe**:不强制 `tencentcloud-sdk-python` 已安装;SDK 在
  方法内 lazy import(对位 R-232 决定,跟其他 secret wheel 一致)
- 构造 `Credential(access_key_id, access_key_secret, security_token)`
- 构造 `SsmClient(credential, region, profile)` +
  `KmsClient(credential, region, profile)`
- 把 SDK 客户端适配成 `SsmLike` / `KmsLike` Protocol(3 个方法),
  SDK 类型不穿透到 framework / public API 边界

`TencentSecretProviderFactory`(`SecretProviderFactory` Protocol
实现):
- `name` = `f"tencent-{region}"`
- `backend` = `SecretBackend.TENCENT`
- `capability` = 静态声明(`can_read=True / can_write=False /
  can_rotate=True / can_list=False / encrypts_at_rest=True /
  signs_values=False / cacheable=True`,对位 Java 3-SPI scope)
- `version` = `"0.2.0"`
- `create(configuration) -> SecretProviderSession`:
  1. 用 `TencentClientFactory` 拿 `SsmLike` + `KmsLike`
  2. 用 `TencentConfigurationResolver` 拿
     `ResolvedTencentConfiguration`
  3. 构造 `TencentSecretClient`

错误转译:
- SDK 缺失 / 不可导入 → `SecretConfigurationException("SEC-BOOT-003", ...)`
- SDK 初始化失败 → `SecretConfigurationException("SEC-PROVIDER-001", ...)`

English
--------
`SecretProviderFactory` for the Tencent backend. The
Alibaba SDK is imported lazily inside `create_clients`
so the wheel is import-safe even without the SDK
installed (matches the `optional-dependency` convention
from R-232).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret_tencent_ssm_kms.client import (
    KmsLike,
    SsmLike,
    TencentKmsDecryptResponse,
    TencentKmsEncryptResponse,
    TencentSecretClient,
    TencentSsmGetResponse,
)
from atlas_richie.secret_tencent_ssm_kms.configuration import (
    TencentConfigurationResolver,
    ResolvedTencentConfiguration,
)
from atlas_richie.secret_tencent_ssm_kms.properties import TencentSecretProperties

_logger = logging.getLogger("atlas_richie.secret_tencent_ssm_kms.factory")


@runtime_checkable
class _SdkClientFactory(Protocol):
    """Test seam: tests inject a pre-built `(SsmLike, KmsLike)`
    pair to skip the Tencent SDK bootstrap path entirely.
    """

    def __call__(
        self, properties: TencentSecretProperties,
    ) -> tuple[SsmLike, KmsLike]: ...


def _tencent_capability() -> SecretCapability:
    return SecretCapability(
        can_read=True,
        can_write=False,
        can_rotate=True,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


class _TencentSdkAdapter:
    """Adapter from `tencentcloud-sdk-python` Clients to
    `SsmLike` / `KmsLike` Protocols. SDK types never leave
    this class.
    """

    def __init__(self, ssm: object, kms: object) -> None:
        self._ssm = ssm
        self._kms = kms

    # SsmLike
    def get_secret_value(
        self, secret_name: str, version_id: str | None,
    ) -> TencentSsmGetResponse:
        request = self._ssm_models().GetSecretValueRequest()
        request.SecretName = secret_name
        if version_id is not None:
            request.VersionId = version_id
        response = self._ssm.GetSecretValue(request)
        body = getattr(response, "Response", None) or response
        return TencentSsmGetResponse(
            secret_name=str(getattr(body, "SecretName", secret_name)),
            version_id=str(getattr(body, "VersionId", "") or ""),
            secret_string=str(getattr(body, "SecretString", "") or ""),
            secret_binary=str(getattr(body, "SecretBinary", "") or ""),
            request_id=str(getattr(response, "RequestId", "") or "") or None,
        )

    # KmsLike
    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
        encryption_context: str | None,
    ) -> TencentKmsEncryptResponse:
        request = self._kms_models().EncryptRequest()
        request.KeyId = key_id
        request.Plaintext = plaintext_b64
        if encryption_context is not None:
            request.EncryptionContext = encryption_context
        response = self._kms.Encrypt(request)
        body = getattr(response, "Response", None) or response
        return TencentKmsEncryptResponse(
            ciphertext_blob=str(getattr(body, "CiphertextBlob", "") or ""),
            request_id=str(getattr(response, "RequestId", "") or "") or None,
        )

    def decrypt(
        self,
        ciphertext_blob: str,
        encryption_context: str | None,
    ) -> TencentKmsDecryptResponse:
        request = self._kms_models().DecryptRequest()
        request.CiphertextBlob = ciphertext_blob
        if encryption_context is not None:
            request.EncryptionContext = encryption_context
        response = self._kms.Decrypt(request)
        body = getattr(response, "Response", None) or response
        return TencentKmsDecryptResponse(
            plaintext=str(getattr(body, "Plaintext", "") or ""),
            request_id=str(getattr(response, "RequestId", "") or "") or None,
        )

    def _ssm_models(self) -> object:
        from tencentcloud.ssm.v20190923 import models  # type: ignore[import-not-found]
        return models

    def _kms_models(self) -> object:
        from tencentcloud.kms.v20190118 import models  # type: ignore[import-not-found]
        return models


def _default_client_factory(
    properties: TencentSecretProperties,
) -> tuple[SsmLike, KmsLike]:
    try:
        from tencentcloud.common import credential  # type: ignore[import-not-found]
        from tencentcloud.common.profile import client_profile  # type: ignore[import-not-found]
        from tencentcloud.kms.v20190118 import kms_client  # type: ignore[import-not-found]
        from tencentcloud.ssm.v20190923 import ssm_client  # type: ignore[import-not-found]
    except ImportError as error:
        raise SecretConfigurationException(
            f"tencent: SDK not installed ({error.name!r}); "
            f"pip install 'atlas-richie-secret-tencent-ssm-kms[sdk]' "
            f"(SEC-BOOT-003)",
        ) from error
    try:
        cred = credential.Credential(
            properties.access_key_id,
            properties.access_key_secret,
            properties.security_token or "",
        )
        profile = client_profile.ClientProfile()
        if properties.secret_endpoint:
            profile.httpProfile.endpoint = properties.secret_endpoint
        ssm = ssm_client.SsmClient(cred, properties.region, profile)
        profile_kms = client_profile.ClientProfile()
        if properties.kms_endpoint:
            profile_kms.httpProfile.endpoint = properties.kms_endpoint
        kms = kms_client.KmsClient(cred, properties.region, profile_kms)
        return _TencentSdkAdapter(ssm, kms), _TencentSdkAdapter(ssm, kms)  # noqa
    except SecretConfigurationException:
        raise
    except Exception as error:  # noqa: BLE001
        raise SecretConfigurationException(
            f"tencent: cannot initialize SDK clients "
            f"(region={properties.region!r}): {error} (SEC-PROVIDER-001)",
        ) from error


def _default_pair_factory(
    properties: TencentSecretProperties,
) -> tuple[SsmLike, KmsLike]:
    """Default factory: returns the SAME adapter for both SSM
    and KMS (the adapter holds both clients). Real SDK
    behavior: the two clients are different instances, but
    the Protocol surface is the same; one adapter per
    client is the cleanest design.
    """
    try:
        from tencentcloud.common import credential  # type: ignore[import-not-found]
        from tencentcloud.common.profile import client_profile  # type: ignore[import-not-found]
        from tencentcloud.kms.v20190118 import kms_client  # type: ignore[import-not-found]
        from tencentcloud.ssm.v20190923 import ssm_client  # type: ignore[import-not-found]
    except ImportError as error:
        raise SecretConfigurationException(
            f"tencent: SDK not installed ({error.name!r}); "
            f"pip install 'atlas-richie-secret-tencent-ssm-kms[sdk]' "
            f"(SEC-BOOT-003)",
        ) from error
    try:
        cred = credential.Credential(
            properties.access_key_id,
            properties.access_key_secret,
            properties.security_token or "",
        )
        profile_ssm = client_profile.ClientProfile()
        if properties.secret_endpoint:
            profile_ssm.httpProfile.endpoint = properties.secret_endpoint
        ssm_sdk = ssm_client.SsmClient(cred, properties.region, profile_ssm)
        profile_kms = client_profile.ClientProfile()
        if properties.kms_endpoint:
            profile_kms.httpProfile.endpoint = properties.kms_endpoint
        kms_sdk = kms_client.KmsClient(cred, properties.region, profile_kms)
        return _TencentSdkAdapter(ssm_sdk, kms_sdk), _TencentSdkAdapter(ssm_sdk, kms_sdk)
    except SecretConfigurationException:
        raise
    except Exception as error:  # noqa: BLE001
        raise SecretConfigurationException(
            f"tencent: cannot initialize SDK clients "
            f"(region={properties.region!r}): {error} (SEC-PROVIDER-001)",
        ) from error


class TencentClientFactory:
    """Build `(SsmLike, KmsLike)` from `TencentSecretProperties`."""

    __slots__ = ()

    def create_clients(
        self, properties: TencentSecretProperties,
    ) -> tuple[SsmLike, KmsLike]:
        return _default_pair_factory(properties)


class TencentSecretProviderFactory:
    """`SecretProviderFactory` for the Tencent backend."""

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
        properties: TencentSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: Callable[[TencentSecretProperties], tuple[SsmLike, KmsLike]] | None = None,
        configuration_resolver: TencentConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.TENCENT,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._client_factory = client_factory or _default_pair_factory
        self._configuration_resolver = (
            configuration_resolver or TencentConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> TencentSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"tencent-{self._properties.region}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return _tencent_capability()

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
        ssm, kms = self._client_factory(self._properties)
        resolved: ResolvedTencentConfiguration = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        return TencentSecretClient(
            resolved=resolved,
            ssm=ssm,
            kms=kms,
            descriptor_backend=self._descriptor_backend,
        )


__all__ = [
    "TencentClientFactory",
    "TencentSecretProviderFactory",
]
