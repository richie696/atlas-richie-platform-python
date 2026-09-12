"""Aliyun backend factory — `SecretProviderFactory` + 内部 `AliyunClientFactory`。

中文
----
对位 Java `cn.richie696.component.secret.provider.aliyun.AliyunSecretBootstrapProviderFactory`
+ 私有 `AliyunClientFactory`。Java 端一个类做 SDK 构造,另一个做
bootstrap;Python 端把两者合一放在 `factory.py`,framework 端只看到
`SecretProviderFactory` Protocol。

`AliyunClientFactory`(`create_gateway(properties)`):负责
- **import-safe**:不强制要求 `alibabacloud_kms20160120` 已安装;
  SDK 在 `create_gateway` 内 lazy import(对位 R-232 决定的 optional
  dependency 原则,跟 secret-vault / secret-aws-kms 一致)
- 构造 `alibabacloud_kms20160120.Client`,配置 region / endpoint /
  protocol / 超时 / retries
- 把 SDK client 适配成 `AliyunKmsGateway` Protocol(3 个方法),
  内部把 SDK 的 `GetSecretValueResponse` 转成
  `AliyunGetSecretValueResponse` 冻结 dataclass,SDK 类型不穿透

`AliyunSecretProviderFactory`(`SecretProviderFactory` Protocol 实现):
- `name` = `f"aliyun-{region}"`
- `backend` = `SecretBackend.ALIYUN`(framework `metadata.SecretBackend`
  枚举已包含 `ALIYUN = "aliyun"`)
- `capability` = 静态声明(`can_read=True / can_write=False /
  can_rotate=True / can_list=False / encrypts_at_rest=True /
  signs_values=False / cacheable=True`,对位 Java 4-SPI scope)
- `version` = `"0.2.0"`
- `create(configuration) -> SecretProviderSession`:
  1. 用 `AliyunClientFactory` 拿 `AliyunKmsGateway`
  2. 用 `AliyunConfigurationResolver` 拿 `ResolvedAliyunConfiguration`
  3. 构造 `AliyunSecretClient`
  4. `close_action` 不需要 — gateway adapter 自身在 `close()` 中处理

错误转译:
- SDK 缺失 / 不可导入 → `SecretConfigurationException("SEC-BOOT-003", ...)`
- SDK 初始化失败 → `SecretConfigurationException("SEC-PROVIDER-001", ...)`
- `client.get_secret_value` / `encrypt` / `decrypt` 失败 → 由 client.py
  转译为 `SecretException` / `SecretCryptoException`

English
--------
Combined factory for the Aliyun backend. Mirrors Java
`AliyunSecretBootstrapProviderFactory` + private
`AliyunClientFactory`. The Alibaba SDK is imported lazily
inside `create_gateway` so the wheel is import-safe even
without the SDK installed (matches the `optional-dependency`
convention from R-232).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret_aliyun_kms.client import (
    AliyunDecryptResponse,
    AliyunEncryptResponse,
    AliyunGetSecretValueResponse,
    AliyunKmsGateway,
    AliyunSecretClient,
)
from atlas_richie.secret_aliyun_kms.configuration import (
    AliyunConfigurationResolver,
    ResolvedAliyunConfiguration,
)
from atlas_richie.secret_aliyun_kms.properties import AliyunSecretProperties

_logger = logging.getLogger("atlas_richie.secret_aliyun_kms.factory")


@runtime_checkable
class _SdkClientFactory(Protocol):
    """Test seam: tests may inject a pre-built `AliyunKmsGateway`
    to skip the Alibaba SDK bootstrap path entirely.
    """

    def __call__(self, properties: AliyunSecretProperties) -> AliyunKmsGateway: ...


def _aliyun_capability() -> SecretCapability:
    """Static capability for the Aliyun backend (mirrors Java
    `Set<SecretCapability>` for `AliyunSecretClient`):
    - SECRET_READ (SM GetSecretValue)
    - SECRET_VERSIONING (SM VersionId + VersionStage)
    - KEY_WRAP / KEY_UNWRAP (KMS Encrypt / Decrypt)
    - encrypts_at_rest=True (SM encrypts at rest by default
      when backed by KMS)
    """
    return SecretCapability(
        can_read=True,
        can_write=False,  # 1:1 with Java: no SecretWriter SPI
        can_rotate=True,
        can_list=False,   # 1:1 with Java: Aliyun SDK 20160120 has no list
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


def _split_endpoint(endpoint: str) -> tuple[str, str]:
    """Split ``https://host[:port]`` into ``(scheme_upper, authority)``.

    Mirrors Java `AliyunClientFactory.endpoint` + `protocol`.
    """
    parsed = urlparse(endpoint)
    scheme = (parsed.scheme or "https").upper()
    host = parsed.hostname or ""
    if parsed.port:
        authority = f"{host}:{parsed.port}"
    else:
        authority = host
    return scheme, authority


class AliyunClientFactory:
    """Build an `AliyunKmsGateway` from `AliyunSecretProperties`.

    The Alibaba SDK is imported lazily inside `create_gateway`
    so the wheel remains import-safe without the SDK installed.
    The default factory tries the real `alibabacloud_kms20160120`
    SDK; tests inject a `FakeAliyunGateway` via the
    `_SdkClientFactory` parameter on `AliyunSecretProviderFactory`.
    """

    __slots__ = ()

    def create_gateway(self, properties: AliyunSecretProperties) -> AliyunKmsGateway:
        try:
            from alibabacloud_kms20160120.client import Client as KmsSdkClient  # type: ignore[import-not-found]
            from alibabacloud_tea_openapi import models as tea_models  # type: ignore[import-not-found]
        except ImportError as error:
            raise SecretConfigurationException(
                f"aliyun: SDK not installed ({error.name!r}); "
                f"pip install 'atlas-richie-secret-aliyun-kms[kms]' "
                f"(SEC-BOOT-003)",
            ) from error
        try:
            config = tea_models.Config()
            if properties.endpoint:
                protocol, authority = _split_endpoint(properties.endpoint)
                config.protocol = protocol
                config.endpoint = authority
            else:
                config.protocol = "HTTPS"
                config.endpoint = f"kms.{properties.region}.aliyuncs.com"
            sdk = KmsSdkClient(config)
            return _AliyunSdkAdapter(sdk)
        except SecretConfigurationException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretConfigurationException(
                f"aliyun: cannot initialize KMS SDK "
                f"(region={properties.region!r}): {error} (SEC-PROVIDER-001)",
            ) from error


def _default_client_factory(properties: AliyunSecretProperties) -> AliyunKmsGateway:
    return AliyunClientFactory().create_gateway(properties)


class _AliyunSdkAdapter:
    """Adapter from `alibabacloud_kms20160120.Client` to `AliyunKmsGateway`.

    Translates SDK request / response models to / from the
    framework's frozen dataclass responses. The SDK types
    never leave this class.
    """

    __slots__ = ("_sdk",)

    def __init__(self, sdk: object) -> None:
        self._sdk = sdk

    def get_secret_value(
        self,
        secret_name: str,
        version_id: str | None,
        version_stage: str | None,
    ) -> AliyunGetSecretValueResponse | None:
        models = _import_sdk_models()
        request = models.GetSecretValueRequest()
        request.secret_name = secret_name
        if version_id is not None:
            request.version_id = version_id
        if version_stage is not None:
            request.version_stage = version_stage
        try:
            response = self._sdk.get_secret_value_with_options(request, None)
        except Exception as error:  # noqa: BLE001
            if _is_not_found(error):
                return None
            raise
        body = getattr(response, "body", None) or response
        stages: tuple[str, ...] = ()
        stages_attr = getattr(body, "version_stages", None)
        if stages_attr is not None:
            inner = getattr(stages_attr, "version_stage", None) or []
            stages = tuple(str(s) for s in inner)
        return AliyunGetSecretValueResponse(
            secret_name=secret_name,
            secret_data=str(getattr(body, "secret_data", "") or ""),
            secret_data_type=str(getattr(body, "secret_data_type", "") or "text"),
            version_id=str(getattr(body, "version_id", "") or ""),
            version_stages=stages,
            create_time=getattr(body, "create_time", None),
            request_id=_extract_request_id(response),
        )

    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
        encryption_context: Mapping[str, str],
    ) -> AliyunEncryptResponse:
        models = _import_sdk_models()
        request = models.EncryptRequest()
        request.key_id = key_id
        request.plaintext = plaintext_b64
        if encryption_context:
            request.encryption_context = dict(encryption_context)
        response = self._sdk.encrypt_with_options(request, None)
        body = getattr(response, "body", None) or response
        return AliyunEncryptResponse(
            key_id=str(getattr(body, "key_id", "") or ""),
            ciphertext_blob=str(getattr(body, "ciphertext_blob", "") or ""),
            request_id=_extract_request_id(response),
        )

    def decrypt(
        self,
        ciphertext_blob: str,
        encryption_context: Mapping[str, str],
    ) -> AliyunDecryptResponse:
        models = _import_sdk_models()
        request = models.DecryptRequest()
        request.ciphertext_blob = ciphertext_blob
        if encryption_context:
            request.encryption_context = dict(encryption_context)
        response = self._sdk.decrypt_with_options(request, None)
        body = getattr(response, "body", None) or response
        return AliyunDecryptResponse(
            key_id=str(getattr(body, "key_id", "") or ""),
            plaintext=str(getattr(body, "plaintext", "") or ""),
            request_id=_extract_request_id(response),
        )

    def close(self) -> None:
        # The Alibaba SDK `Client` does not own sockets directly;
        # the underlying HTTP session is closed via gc.
        return None


def _import_sdk_models() -> object:
    try:
        from alibabacloud_kms20160120 import models  # type: ignore[import-not-found]
    except ImportError as error:
        raise SecretConfigurationException(
            f"aliyun: SDK not installed ({error.name!r}) (SEC-BOOT-003)",
        ) from error
    return models


def _extract_request_id(response: object) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    if isinstance(headers, Mapping):
        return headers.get("x-acs-request-id")
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    try:
        return getter("x-acs-request-id")
    except Exception:  # noqa: BLE001
        return None


def _is_not_found(error: BaseException) -> bool:
    """Heuristic detection of Aliyun's `TeaException` not-found variant.

    Java's `AliyunSecretClient` checks
    `SECRET_NOT_FOUND_CODES.contains(exception.getCode().trim())`
    where `SECRET_NOT_FOUND_CODES = {"Forbidden.ResourceNotFound"}`.
    The Python SDK's exception class is `TeaException`; we look at
    the `.code` attribute and fall back to scanning the message
    for robustness across SDK versions.
    """
    code = getattr(error, "code", None)
    if code and str(code).strip() == "Forbidden.ResourceNotFound":
        return True
    return "Forbidden.ResourceNotFound" in str(error)


class AliyunSecretProviderFactory:
    """`SecretProviderFactory` for the Aliyun backend."""

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
        properties: AliyunSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: _SdkClientFactory | None = None,
        configuration_resolver: AliyunConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.ALIYUN,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._client_factory = client_factory or _default_client_factory
        self._configuration_resolver = (
            configuration_resolver or AliyunConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> AliyunSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"aliyun-{self._properties.region}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return _aliyun_capability()

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
        gateway = self._client_factory(self._properties)
        resolved = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        return AliyunSecretClient(
            resolved=resolved,
            gateway=gateway,
            descriptor_backend=self._descriptor_backend,
        )


__all__ = [
    "AliyunClientFactory",
    "AliyunSecretProviderFactory",
]
