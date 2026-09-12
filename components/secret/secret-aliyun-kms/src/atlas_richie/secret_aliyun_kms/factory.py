"""`AliyunSecretProviderFactory` — 框架入口 + 内部 `AliyunClientFactory` SDK 适配。

中文
----
对位 Java `cn.richie696.component.secret.provider.aliyun.AliyunSecretBootstrapProviderFactory`
+ `AliyunClientFactory`。两个 factory 分工:

- `AliyunClientFactory` — 内部 SDK 适配器;`create_gateway(properties)`
  懒加载 `alibabacloud_kms20160120.client.Client` + 必要的
  `alibabacloud_tea_openapi` / `alibabacloud_credentials` 依赖,
  包成 `AliyunKmsGateway` Protocol 实例。SDK 缺失时抛
  `SecretConfigurationException("SEC-BOOT-003", ...)`。
- `AliyunSecretProviderFactory` — `SecretProviderFactory` Protocol
  实现;`name` 形如 `aliyun-{region}`(无 region 时 `aliyun-default`),
  `backend = SecretBackend.ALIYUN`,`capabilities` 静态固定
  (`SECRET_READ` / `SECRET_VERSIONING` / `KEY_WRAP` / `KEY_UNWRAP`),
  `version = "0.2.0"`。`create(configuration) -> SecretProviderSession`
  三步走:resolve → build gateway → construct `AliyunSecretClient`。

**Import-safe**:模块顶层不 import 任何 `alibabacloud_*` 包;
`import atlas_richie.secret_aliyun_kms` 永远不会触发 SDK 加载。
SDK 只在 `AliyunClientFactory.create_gateway(properties)` 调用栈中
被 `import` (用 `try/except ImportError` 守护)。

English
--------
Framework entry. Two factories split responsibility: the internal
`AliyunClientFactory` lazily loads the Alibaba SDK and adapts it to
the `AliyunKmsGateway` Protocol; the public
`AliyunSecretProviderFactory` is a `SecretProviderFactory` Protocol
implementation that owns the resolve → build gateway → construct
client pipeline.

The module is import-safe: top-level imports do NOT touch
`alibabacloud_*`. The SDK is only loaded inside
`AliyunClientFactory.create_gateway(...)`, which is itself called
only from `AliyunSecretProviderFactory.create(...)`. Developers
without Alibaba credentials can still `import
atlas_richie.secret_aliyun_kms` to exercise properties /
configuration / unit tests driven by `FakeAliyunGateway`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession

from atlas_richie.secret_aliyun_kms.client import (
    AliyunKmsGateway,
    AliyunSecretClient,
)
from atlas_richie.secret_aliyun_kms.configuration import (
    AliyunConfigurationResolver,
    ResolvedAliyunConfiguration,
)
from atlas_richie.secret_aliyun_kms.properties import AliyunSecretProperties

if TYPE_CHECKING:
    pass

_logger = logging.getLogger("atlas_richie.secret_aliyun_kms.factory")

# Aliyun Secrets Manager 2016-01-20 SDK entry point (the Python
# equivalent of Java `com.aliyun.kms20160120.Client`). We deliberately
# do NOT import it at module top level so this wheel is import-safe
# on machines that never call `create(...)`.
_KMS_SDK_CLIENT = "alibabacloud_kms20160120.client:Client"
_KMS_SDK_MODELS = "alibabacloud_kms20160120.models"
_TEA_OPENAPI_CLIENT = "alibabacloud_tea_openapi.client:Client"
_CREDENTIALS_CLIENT = "alibabacloud_credentials.client:Client"

# Default provider id when the caller does not configure one. Mirrors
# Java's `AliyunSecretBootstrapProviderFactory` default.
_DEFAULT_PROVIDER_ID = "aliyun-default"

# Stable, non-Protocol exports re-exposed for `from factory import X`
# convenience.
_ = (SecretCapability,)


def _aliyun_provider_capability() -> SecretCapability:
    """Static capability declared by the Alibaba Cloud backend.

    Mirrors the framework's view of the aliyun backend: same
    capability as `ResolvedAliyunConfiguration.capability` (so
    `factory.capability` and `session.descriptor.capability` are
    consistent across the lifetime of a session).
    """
    return SecretCapability(
        can_read=True,
        can_write=False,
        can_rotate=True,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


class AliyunClientFactory:
    """Internal SDK adapter. Lazily imports the Alibaba SDK.

    `create_gateway(properties)` returns an `AliyunKmsGateway` that
    wraps `alibabacloud_kms20160120.client.Client`. The adapter
    translates the SDK's mutable model classes into the frozen
    response dataclasses defined in `client.py`, so the public
    surface of this wheel never references SDK types.

    Import failures are translated to
    `SecretConfigurationException("SEC-BOOT-003", ...)` so callers
    can install the `[kms]` extra to recover.
    """

    __slots__ = ()

    def create_gateway(self, properties: AliyunSecretProperties) -> AliyunKmsGateway:
        """Build an `AliyunKmsGateway` for `properties`.

        Args:
            properties: Validated `AliyunSecretProperties` (typically
                produced by `AliyunConfigurationResolver.resolve(...)`).

        Raises:
            SecretConfigurationException: When the Alibaba SDK is not
                installed, the user has not provided the required
                region, or the SDK raises a configuration error
                during client construction.
        """
        try:
            return self._build_gateway(properties)
        except SecretConfigurationException:
            raise
        except ImportError as error:
            raise SecretConfigurationException(
                "SEC-BOOT-003 aliyun: Aliyun KMS SDK not installed; "
                "pip install 'atlas-richie-secret-aliyun-kms[kms]'",
            ) from error
        except Exception as error:  # noqa: BLE001
            raise SecretConfigurationException(
                f"SEC-BOOT-003 aliyun: failed to build SDK client: {error}",
            ) from error

    @staticmethod
    def _build_gateway(properties: AliyunSecretProperties) -> AliyunKmsGateway:
        # Lazy imports — see module docstring.
        from alibabacloud_credentials.client import Client as CredentialsClient  # type: ignore[import-not-found]
        from alibabacloud_kms20160120.client import Client as KmsClient  # type: ignore[import-not-found]
        from alibabacloud_tea_openapi import models as open_api_models  # type: ignore[import-not-found]
        from alibabacloud_tea_openapi.client import Client as TeaClient  # type: ignore[import-not-found]

        endpoint = properties.endpoint or f"kms.{properties.region}.aliyuncs.com"
        credentials_client = CredentialsClient()
        config = open_api_models.Config(
            credential=credentials_client,
            endpoint=endpoint,
            connect_timeout=properties.connect_timeout_seconds * 1000,
            read_timeout=properties.read_timeout_seconds * 1000,
        )
        if properties.ca_file:
            config.ca_cert_path = properties.ca_file
        kms_client = KmsClient(config)
        return _AliyunSdkGateway(
            kms_client=kms_client,
            tea_client=TeaClient,
            max_attempts=properties.max_attempts,
        )


class _AliyunSdkGateway:
    """Adapter that translates the Alibaba SDK's mutable models into
    the frozen response dataclasses.

    This class is private to the `factory` module; tests use
    `FakeAliyunGateway` from `tests/conftest.py` instead.
    """

    __slots__ = ("_kms_client", "_max_attempts", "_tea_client")

    def __init__(self, kms_client, tea_client, *, max_attempts: int) -> None:
        self._kms_client = kms_client
        self._tea_client = tea_client
        self._max_attempts = max_attempts

    def get_secret_value(
        self,
        secret_name: str,
        version_id: str | None,
        version_stage: str | None,
    ):
        # Lazy import so the SDK is only loaded when this method
        # actually runs (not at adapter construction time).
        from alibabacloud_kms20160120 import models as kms_models  # type: ignore[import-not-found]

        request = kms_models.GetSecretValueRequest(
            secret_name=secret_name,
        )
        if version_id:
            request.version_id = version_id
        if version_stage:
            request.version_stage = version_stage
        runtime = self._runtime_options()
        try:
            response = self._kms_client.get_secret_value_with_options(request, runtime)
        except Exception as error:  # noqa: BLE001
            code = _extract_vendor_code(error)
            if code == "Forbidden.ResourceNotFound":
                return None
            raise
        from atlas_richie.secret_aliyun_kms.client import AliyunGetSecretValueResponse
        from datetime import datetime as _dt, timezone as _tz

        body = getattr(response, "body", response)
        create_time = getattr(body, "create_time", None)
        if create_time is not None and not isinstance(create_time, _dt):
            create_time = _dt.now(tz=_tz.utc)
        stages = getattr(body, "version_stages", None) or ()
        return AliyunGetSecretValueResponse(
            secret_name=getattr(body, "secret_name", secret_name),
            secret_data=getattr(body, "secret_data", "") or "",
            secret_data_type=getattr(body, "secret_data_type", "Text") or "Text",
            version_id=getattr(body, "version_id", "") or "",
            version_stages=tuple(stages),
            create_time=create_time,
            request_id=getattr(response, "request_id", "") or getattr(body, "request_id", "") or "",
        )

    def encrypt(self, key_id, plaintext_b64, encryption_context):
        from alibabacloud_kms20160120 import models as kms_models  # type: ignore[import-not-found]
        from atlas_richie.secret_aliyun_kms.client import AliyunEncryptResponse

        request = kms_models.EncryptRequest(
            key_id=key_id,
            plaintext=plaintext_b64,
        )
        if encryption_context:
            request.encryption_context = dict(encryption_context)
        runtime = self._runtime_options()
        response = self._kms_client.encrypt_with_options(request, runtime)
        body = getattr(response, "body", response)
        return AliyunEncryptResponse(
            ciphertext_blob=getattr(body, "ciphertext_blob", "") or "",
            key_id=getattr(body, "key_id", key_id) or key_id,
            request_id=getattr(response, "request_id", "") or getattr(body, "request_id", "") or "",
        )

    def decrypt(self, ciphertext_blob, encryption_context):
        from alibabacloud_kms20160120 import models as kms_models  # type: ignore[import-not-found]
        from atlas_richie.secret_aliyun_kms.client import AliyunDecryptResponse

        request = kms_models.DecryptRequest(ciphertext_blob=ciphertext_blob)
        if encryption_context:
            request.encryption_context = dict(encryption_context)
        runtime = self._runtime_options()
        response = self._kms_client.decrypt_with_options(request, runtime)
        body = getattr(response, "body", response)
        return AliyunDecryptResponse(
            plaintext=getattr(body, "plaintext", "") or "",
            key_id=getattr(body, "key_id", "") or "",
            request_id=getattr(response, "request_id", "") or getattr(body, "request_id", "") or "",
        )

    def close(self) -> None:
        close = getattr(self._kms_client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                _logger.exception("aliyun: error during SDK client close")

    def _runtime_options(self):
        from alibabacloud_tea_openapi import models as open_api_models  # type: ignore[import-not-found]

        return open_api_models.RuntimeOptions(
            autoretry=True,
            max_attempts=self._max_attempts,
        )


def _extract_vendor_code(error: BaseException) -> str:
    """Best-effort vendor code extraction for the Alibaba SDK.

    Mirrors the client-side `_extract_sdk_code`; kept private to the
    factory module so the public surface does not re-expose it.
    """
    for attr in ("code", "errorCode", "Code"):
        value = getattr(error, attr, None)
        if isinstance(value, str) and value:
            return value
    return ""


class AliyunSecretProviderFactory:
    """Framework entry point. Implements `SecretProviderFactory`.

    Construct with no arguments; the factory loads
    `AliyunSecretProperties` lazily from environment variables on
    `create(...)`. Callers may also pass an explicit
    `AliyunSecretProperties` instance to `create(configuration)`,
    or pre-build a `ResolvedAliyunConfiguration` for advanced
    scenarios (e.g. in-process reuse of a resolved configuration
    across multiple sessions).
    """

    __slots__ = (
        "_default_properties",
        "_provider_id_template",
        "_resolver",
    )

    def __init__(
        self,
        properties: AliyunSecretProperties | None = None,
        *,
        provider_id: str | None = None,
    ) -> None:
        self._default_properties = properties
        self._provider_id_template = provider_id or _DEFAULT_PROVIDER_ID
        self._resolver = AliyunConfigurationResolver()

    @property
    def name(self) -> str:
        """Stable identifier for this backend.

        Computed as `aliyun-{region}` when a region is configured,
        falling back to `aliyun-default` when no region is set in
        the default properties. The framework uses this as
        `SecretProviderDescriptor.name`.
        """
        region = (self._default_properties.region if self._default_properties else None) or ""
        if not region:
            return _DEFAULT_PROVIDER_ID
        return f"aliyun-{region}"

    @property
    def backend(self) -> SecretBackend:
        return SecretBackend.ALIYUN

    @property
    def capability(self) -> SecretCapability:
        return _aliyun_provider_capability()

    @property
    def version(self) -> str:
        return "0.2.0"

    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self.name,
            backend=self.backend,
            capability=self.capability,
            version=self.version,
        )

    def default_configuration(self) -> SecretProviderConfiguration:
        """Return a `SecretProviderConfiguration` derived from the
        default properties (or from environment variables when no
        properties were passed to the constructor).
        """
        properties = self._load_default_properties()
        return SecretProviderConfiguration(
            name=self._compute_provider_id(properties),
            parameters={
                "region": properties.region,
            },
            timeout_seconds=properties.read_timeout_seconds,
            retries=properties.max_attempts,
            namespace=properties.region,
        )

    def create(
        self,
        configuration: SecretProviderConfiguration,
    ) -> SecretProviderSession:
        """Build a fresh `AliyunSecretClient` for `configuration`.

        Loads the default `AliyunSecretProperties` (env-driven when
        none was supplied to the constructor), resolves it through
        `AliyunConfigurationResolver`, builds the gateway via
        `AliyunClientFactory.create_gateway(...)`, and constructs
        the client. The client is configured to close the gateway
        when `session.close()` is called.
        """
        properties = self._load_default_properties()
        provider_id = configuration.name or self._compute_provider_id(properties)
        resolved = self._resolver.resolve(
            properties,
            provider_id=provider_id,
        )
        gateway_factory = AliyunClientFactory()
        gateway = gateway_factory.create_gateway(resolved.properties)
        # Wrap the gateway so the session's `close()` triggers the
        # SDK's cleanup without leaking references.
        session = AliyunSecretClient(
            resolved=resolved,
            gateway=gateway,
            close_action=None,
        )
        return session

    # --- helpers --------------------------------------------------------

    def _load_default_properties(self) -> AliyunSecretProperties:
        if self._default_properties is not None:
            return self._default_properties
        # Pydantic-settings resolves from environment + `.env` on
        # construction; we just instantiate it.
        return AliyunSecretProperties()

    def _compute_provider_id(self, properties: AliyunSecretProperties) -> str:
        if self._provider_id_template and self._provider_id_template != _DEFAULT_PROVIDER_ID:
            return self._provider_id_template
        if properties.region:
            return f"aliyun-{properties.region}"
        return _DEFAULT_PROVIDER_ID


__all__ = [
    "AliyunClientFactory",
    "AliyunSecretProviderFactory",
    "ResolvedAliyunConfiguration",
]
