"""Baidu Cloud KMS backend factory — `SecretProviderFactory` entry + SDK 适配。

中文
----
对位 Java
`cn.richie696.component.secret.provider.baidu.BaiduSecretBootstrapProviderFactory`
(SDK 改造后只剩 ~10 行)。

`BaiduClientFactory.create_kms(properties)`:
- **import-safe**:不强制 `bce-python-sdk` 已安装;SDK 在方法
  内 lazy import
- 构造 `KmsClientConfiguration` with `endpoint=host[:port]` +
  `protocol=Protocol.HTTPS|HTTP` + `credentials=
  DefaultBceCredentials(ak, sk)`
- 构造 `KmsClient(configuration)`
- 把 SDK 客户端适配成 `KmsLike` Protocol(2 个方法)

`BaiduSecretProviderFactory`(`SecretProviderFactory` Protocol):
- `name` = `f"baidu-kms-{region}"`
- `backend` = `SecretBackend.BAIDU`
- `capability` = 静态声明(`can_read=False / can_write=False /
  can_rotate=False / can_list=False / encrypts_at_rest=True /
  signs_values=False / cacheable=False`,KMS-only)
- `version` = `"0.2.0"`
- `create(configuration) -> SecretProviderSession`:
  1. 用 `BaiduClientFactory` 拿 `KmsLike`
  2. 用 `BaiduConfigurationResolver` 拿
     `ResolvedBaiduConfiguration`
  3. 构造 `BaiduSecretClient`

错误转译:
- SDK 缺失 → `SecretConfigurationException("SEC-BOOT-003", ...)`

English
--------
`SecretProviderFactory` for the Baidu Cloud KMS backend.
SDK is imported lazily inside `create_kms` so the wheel
is import-safe without the SDK installed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret_baidu_kms.client import (
    BaiduKmsDecryptResponse,
    BaiduKmsEncryptResponse,
    BaiduSecretClient,
    KmsLike,
)
from atlas_richie.secret_baidu_kms.configuration import (
    BaiduConfigurationResolver,
    ResolvedBaiduConfiguration,
)
from atlas_richie.secret_baidu_kms.properties import BaiduSecretProperties

_logger = logging.getLogger("atlas_richie.secret_baidu_kms.factory")


@runtime_checkable
class _SdkClientFactory(Protocol):
    """Test seam: tests inject a pre-built `KmsLike`."""

    def __call__(self, properties: BaiduSecretProperties) -> KmsLike: ...


# ---------------------------------------------------------------------------
# SDK adapter (translate BCE SDK request / response to Protocol)
# ---------------------------------------------------------------------------


class _BceKmsAdapter:
    """Adapter from `baidubce.services.kms.KmsClient` to `KmsLike` Protocol."""

    def __init__(self, kms: object) -> None:
        self._kms = kms

    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
    ) -> BaiduKmsEncryptResponse:
        request = self._models().EncryptRequest()
        request.set_key_id(key_id)
        request.set_plaintext(plaintext_b64)
        try:
            response = self._kms.encrypt(request)
        except Exception as error:  # noqa: BLE001
            raise SecretConfigurationException(
                f"baidu-kms: encrypt failed (key_id={key_id!r}): {error} "
                f"(SEC-PROVIDER-001)",
            ) from error
        ciphertext = getattr(response, "ciphertext", None) or getattr(
            response, "get_ciphertext", lambda: None,
        )()
        if callable(ciphertext):
            ciphertext = ciphertext()
        if not ciphertext:
            raise SecretConfigurationException(
                f"baidu-kms: encrypt response missing 'ciphertext': "
                f"{response!r} (SEC-PROVIDER-001)",
            )
        return BaiduKmsEncryptResponse(ciphertext=str(ciphertext))

    def decrypt(
        self,
        key_id: str,
        ciphertext: str,
    ) -> BaiduKmsDecryptResponse:
        request = self._models().DecryptRequest()
        request.set_key_id(key_id)
        request.set_ciphertext(ciphertext)
        try:
            response = self._kms.decrypt(request)
        except Exception as error:  # noqa: BLE001
            raise SecretConfigurationException(
                f"baidu-kms: decrypt failed (key_id={key_id!r}): {error} "
                f"(SEC-PROVIDER-001)",
            ) from error
        plaintext = getattr(response, "plaintext", None) or getattr(
            response, "get_plaintext", lambda: None,
        )()
        if callable(plaintext):
            plaintext = plaintext()
        if not plaintext:
            raise SecretConfigurationException(
                f"baidu-kms: decrypt response missing 'plaintext': "
                f"{response!r} (SEC-PROVIDER-001)",
            )
        return BaiduKmsDecryptResponse(plaintext=str(plaintext))

    @staticmethod
    def _models() -> object:
        from baidubce.services.kms import model  # type: ignore[import-not-found]
        return model


# ---------------------------------------------------------------------------
# Default SDK factory (lazy imports)
# ---------------------------------------------------------------------------


def _default_kms_factory(properties: BaiduSecretProperties) -> KmsLike:
    try:
        from baidubce.auth import (  # type: ignore[import-not-found]
            DefaultBceCredentials,
        )
        from baidubce.services.kms import KmsClient  # type: ignore[import-not-found]
        from baidubce.services.kms.kms_client import (  # type: ignore[import-not-found]
            KmsClientConfiguration,
        )
        from baidubce import Protocol  # type: ignore[import-not-found]
    except ImportError as error:
        raise SecretConfigurationException(
            f"baidu-kms: SDK not installed ({error.name!r}); "
            f"pip install 'atlas-richie-secret-baidu-kms[sdk]' "
            f"(SEC-BOOT-003)",
        ) from error
    parsed = urlparse(properties.kms_endpoint)
    host = parsed.hostname
    if not host:
        raise SecretConfigurationException(
            f"baidu-kms: kms_endpoint host is required: "
            f"{properties.kms_endpoint!r} (SEC-BOOT-003)",
        )
    # Java: endpoint.getHost() + (port < 0 ? "" : ":" + port)
    port = parsed.port
    endpoint = host if port is None else f"{host}:{port}"
    scheme = (parsed.scheme or "http").lower()
    try:
        configuration = KmsClientConfiguration(
            endpoint=endpoint,
            protocol=Protocol.HTTPS if scheme == "https" else Protocol.HTTP,
            credentials=DefaultBceCredentials(
                properties.access_key_id,
                properties.access_key_secret,
            ),
        )
        return _BceKmsAdapter(KmsClient(configuration))
    except SecretConfigurationException:
        raise
    except Exception as error:  # noqa: BLE001
        raise SecretConfigurationException(
            f"baidu-kms: cannot initialize BCE KMS SDK "
            f"(endpoint={endpoint!r}): {error} (SEC-PROVIDER-001)",
        ) from error


# ---------------------------------------------------------------------------
# Public factories
# ---------------------------------------------------------------------------


class BaiduClientFactory:
    """Build a `KmsLike` from `BaiduSecretProperties`."""

    __slots__ = ()

    def create_kms(self, properties: BaiduSecretProperties) -> KmsLike:
        return _default_kms_factory(properties)


class BaiduSecretProviderFactory:
    """`SecretProviderFactory` for the Baidu Cloud KMS backend."""

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
        properties: BaiduSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: Callable[[BaiduSecretProperties], KmsLike] | None = None,
        configuration_resolver: BaiduConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.BAIDU,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._client_factory = client_factory or _default_kms_factory
        self._configuration_resolver = (
            configuration_resolver or BaiduConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> BaiduSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"baidu-kms-{self._properties.region}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return _baidu_kms_capability()

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
        kms = self._client_factory(self._properties)
        resolved: ResolvedBaiduConfiguration = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        return BaiduSecretClient(
            resolved=resolved,
            kms=kms,
            descriptor_backend=self._descriptor_backend,
        )


def _baidu_kms_capability() -> SecretCapability:
    return SecretCapability(
        can_read=False,
        can_write=False,
        can_rotate=False,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=False,
    )


__all__ = [
    "BaiduClientFactory",
    "BaiduSecretProviderFactory",
]
