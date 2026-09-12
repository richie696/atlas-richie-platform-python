"""IBM Key Protect backend factory — `SecretProviderFactory` entry + HTTP 适配。

中文
----
对位 Java
`cn.richie696.component.secret.provider.ibm.IBMKeyProtectSecretBootstrapProviderFactory`
(SDK 改造后只剩 ~10 行)。

`IbmKeyProtectClientFactory.create_kms(properties)`:
- **import-safe**:不强制 `ibm-cloud-sdk-core` 已安装;SDK 在
  方法内 lazy import(只用于构造
  `BearerTokenAuthenticator` 给 `httpx.Auth` 复用)
- 构造 `httpx.Client` with `base_url=kms_endpoint` +
  `auth=BearerTokenAuthenticator(token)`(把
  `authenticate(req)` 转写到 `Authorization: Bearer <token>`
  header)
- 构造 adapter `_IbmKeyProtectKmsAdapter` 把 `httpx` + JSON
  请求体适配成 `KmsLike` Protocol(2 个方法)
- REST 端点:
  - `POST /api/v2/keys/{key_id}/wrap`,body
    `{"plaintext": "<b64>"}` → `{"ciphertext": "..."}`
  - `POST /api/v2/keys/{key_id}/unwrap`,body
    `{"ciphertext": "<b64>"}` → `{"plaintext": "..."}`
- Headers:`x-kms-key-ring: <key_ring>` +
  `bluemix-instance: <instance_id>`

`IbmKeyProtectSecretProviderFactory`(`SecretProviderFactory`
Protocol):
- `name` = `f"ibm-key-protect-{region}"`
- `backend` = `SecretBackend.IBM_KEY_PROTECT`
- `capability` = 静态声明(`can_read=False / can_write=False /
  can_rotate=False / can_list=False / encrypts_at_rest=True /
  signs_values=False / cacheable=False`,KMS-only)
- `version` = `"0.2.0"`
- `create(configuration) -> SecretProviderSession`:
  1. 用 `IbmKeyProtectClientFactory` 拿 `KmsLike`
  2. 用 `IbmKeyProtectConfigurationResolver` 拿
     `ResolvedIbmKeyProtectConfiguration`
  3. 构造 `IbmKeyProtectSecretClient`

错误转译:
- SDK / 第三方包缺失 →
  `SecretConfigurationException("SEC-BOOT-003", ...)`
- HTTP 非 2xx → wrap / unwrap 内部 raise
  `SecretCryptoException`

English
--------
`SecretProviderFactory` for the IBM Key Protect backend.
The wheel is import-safe without the
`ibm-cloud-sdk-core` SDK; the SDK is used only inside
`create_kms` to construct a `BearerTokenAuthenticator`
that attaches the IAM token to each `httpx` request.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

import httpx

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret_ibm_key_protect.client import (
    IbmKeyProtectSecretClient,
    IbmKeyProtectUnwrapResponse,
    IbmKeyProtectWrapResponse,
    KmsLike,
)
from atlas_richie.secret_ibm_key_protect.configuration import (
    IbmKeyProtectConfigurationResolver,
    ResolvedIbmKeyProtectConfiguration,
)
from atlas_richie.secret_ibm_key_protect.properties import IbmKeyProtectProperties

_logger = logging.getLogger("atlas_richie.secret_ibm_key_protect.factory")


@runtime_checkable
class _SdkClientFactory(Protocol):
    """Test seam: tests inject a pre-built `KmsLike`."""

    def __call__(self, properties: IbmKeyProtectProperties) -> KmsLike: ...


# ---------------------------------------------------------------------------
# HTTP adapter (Key Protect REST + Bearer token auth)
# ---------------------------------------------------------------------------


class _BearerTokenHttpxAuth(httpx.Auth):
    """Adapter: `ibm-cloud-sdk-core` `BearerTokenAuthenticator` → `httpx.Auth`."""

    def __init__(self, bearer_token: str) -> None:
        self._token = bearer_token

    def auth_flow(self, request):  # type: ignore[no-untyped-def]
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


class _IbmKeyProtectKmsAdapter:
    """Adapter from `httpx.Client` + Key Protect REST to `KmsLike` Protocol.

    Mirrors Java `IbmKeyProtectSdkSecretTransport.wrap` /
    `unwrap`:
    - Java `body("plaintext", encoded)` → POST `/api/v2/keys/{id}/wrap`
      with `{"plaintext": "<b64>"}`
    - Java `body("ciphertext", ciphertext)` → POST
      `/api/v2/keys/{id}/unwrap` with `{"ciphertext": "<b64>"}`
    - Java `xKmsKeyRing(keyRing)` header → `x-kms-key-ring`
    - Java `IbmKeyProtectApi("ibm-key-protect", BearerTokenAuthenticator)`
      implicit instance header → `bluemix-instance: <instance_id>`
    """

    def __init__(
        self,
        client: httpx.Client,
        instance_id: str,
        key_ring: str,
    ) -> None:
        self._client = client
        self._instance_id = instance_id
        self._key_ring = key_ring

    def _common_headers(self) -> dict[str, str]:
        return {
            "bluemix-instance": self._instance_id,
            "x-kms-key-ring": self._key_ring,
            "Accept": "application/json",
        }

    def wrap(
        self,
        key_id: str,
        plaintext_b64: str,
    ) -> IbmKeyProtectWrapResponse:
        url = f"/api/v2/keys/{key_id}/wrap"
        body = {"plaintext": plaintext_b64}
        try:
            response = self._client.post(
                url,
                json=body,
                headers=self._common_headers(),
            )
        except Exception as error:  # noqa: BLE001
            raise SecretConfigurationException(
                f"ibm-key-protect: wrap HTTP request failed "
                f"(key_id={key_id!r}): {error} (SEC-PROVIDER-001)",
            ) from error
        if response.status_code >= 400:
            raise SecretConfigurationException(
                f"ibm-key-protect: wrap returned HTTP "
                f"{response.status_code}: {response.text!r} (SEC-PROVIDER-001)",
            )
        data = response.json()
        ciphertext = data.get("ciphertext", "")
        if not isinstance(ciphertext, str) or not ciphertext:
            raise SecretConfigurationException(
                f"ibm-key-protect: wrap response missing 'ciphertext' field: "
                f"{data!r} (SEC-PROVIDER-001)",
            )
        return IbmKeyProtectWrapResponse(ciphertext=ciphertext)

    def unwrap(
        self,
        key_id: str,
        ciphertext: str,
    ) -> IbmKeyProtectUnwrapResponse:
        url = f"/api/v2/keys/{key_id}/unwrap"
        body = {"ciphertext": ciphertext}
        try:
            response = self._client.post(
                url,
                json=body,
                headers=self._common_headers(),
            )
        except Exception as error:  # noqa: BLE001
            raise SecretConfigurationException(
                f"ibm-key-protect: unwrap HTTP request failed "
                f"(key_id={key_id!r}): {error} (SEC-PROVIDER-001)",
            ) from error
        if response.status_code >= 400:
            raise SecretConfigurationException(
                f"ibm-key-protect: unwrap returned HTTP "
                f"{response.status_code}: {response.text!r} (SEC-PROVIDER-001)",
            )
        data = response.json()
        plaintext = data.get("plaintext", "")
        if not isinstance(plaintext, str) or not plaintext:
            raise SecretConfigurationException(
                f"ibm-key-protect: unwrap response missing 'plaintext' field: "
                f"{data!r} (SEC-PROVIDER-001)",
            )
        return IbmKeyProtectUnwrapResponse(plaintext=plaintext)

    def close(self) -> None:  # pragma: no cover - cleanup hook
        try:
            self._client.close()
        except Exception:  # noqa: BLE001, S110
            pass


# ---------------------------------------------------------------------------
# Default SDK factory (lazy imports)
# ---------------------------------------------------------------------------


def _default_kms_factory(properties: IbmKeyProtectProperties) -> KmsLike:
    bearer_token = properties.bearer_token
    if not bearer_token:
        raise SecretConfigurationException(
            "ibm-key-protect: bearer_token is required (SEC-BOOT-003)",
        )
    if properties.kms_endpoint is None or not properties.kms_endpoint.strip():
        raise SecretConfigurationException(
            "ibm-key-protect: kms_endpoint is required (SEC-BOOT-003)",
        )
    # ibm-cloud-sdk-core is opt-in; lazy import.
    try:
        from ibm_cloud_sdk_core import (  # type: ignore[import-not-found]
            BearerTokenAuthenticator,
        )
    except ImportError as error:
        raise SecretConfigurationException(
            f"ibm-key-protect: ibm-cloud-sdk-core not installed "
            f"({error.name!r}); pip install "
            f"'atlas-richie-secret-ibm-key-protect[sdk]' (SEC-BOOT-003)",
        ) from error
    # We use BearerTokenAuthenticator purely for symmetry with the Java
    # SDK; the actual header attachment is done by our
    # `_BearerTokenHttpxAuth` so we don't need its request
    # preparation pipeline.
    try:
        # Probe SDK to confirm it works
        BearerTokenAuthenticator(bearer_token=bearer_token)
    except Exception as error:  # noqa: BLE001
        raise SecretConfigurationException(
            f"ibm-key-protect: cannot initialize BearerTokenAuthenticator: "
            f"{error} (SEC-BOOT-003)",
        ) from error
    try:
        client = httpx.Client(
            base_url=properties.kms_endpoint,
            auth=_BearerTokenHttpxAuth(bearer_token),
            timeout=httpx.Timeout(
                connect=properties.connect_timeout_seconds,
                read=properties.read_timeout_seconds,
                write=properties.read_timeout_seconds,
                pool=properties.connect_timeout_seconds,
            ),
        )
    except Exception as error:  # noqa: BLE001
        raise SecretConfigurationException(
            f"ibm-key-protect: cannot build httpx.Client "
            f"(endpoint={properties.kms_endpoint!r}): {error} "
            f"(SEC-PROVIDER-001)",
        ) from error
    return _IbmKeyProtectKmsAdapter(
        client=client,
        instance_id=properties.instance_id,
        key_ring=properties.key_ring or "default",
    )


# ---------------------------------------------------------------------------
# Public factories
# ---------------------------------------------------------------------------


class IbmKeyProtectClientFactory:
    """Build a `KmsLike` from `IbmKeyProtectProperties`."""

    __slots__ = ()

    def create_kms(self, properties: IbmKeyProtectProperties) -> KmsLike:
        return _default_kms_factory(properties)


class IbmKeyProtectSecretProviderFactory:
    """`SecretProviderFactory` for the IBM Key Protect backend."""

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
        properties: IbmKeyProtectProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: Callable[[IbmKeyProtectProperties], KmsLike] | None = None,
        configuration_resolver: IbmKeyProtectConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.IBM_KEY_PROTECT,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._client_factory = client_factory or _default_kms_factory
        self._configuration_resolver = (
            configuration_resolver or IbmKeyProtectConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> IbmKeyProtectProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"ibm-key-protect-{self._properties.region}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return _ibm_kms_capability()

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
        resolved: ResolvedIbmKeyProtectConfiguration = (
            self._configuration_resolver.resolve(
                self._properties,
                provider_id=configuration.name or self.name,
            )
        )
        return IbmKeyProtectSecretClient(
            resolved=resolved,
            kms=kms,
            descriptor_backend=self._descriptor_backend,
        )


def _ibm_kms_capability() -> SecretCapability:
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
    "IbmKeyProtectClientFactory",
    "IbmKeyProtectSecretProviderFactory",
]
