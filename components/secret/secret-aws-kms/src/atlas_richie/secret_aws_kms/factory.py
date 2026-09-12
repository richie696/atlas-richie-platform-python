"""AWS backend factory — `SecretProviderFactory` + 内部 `AwsClientFactory`。

中文
----
对位 Java `cn.richie696.component.secret.provider.aws.AwsSecretBootstrapProviderFactory`
+ 私有 `AwsClientFactory`。Java 端一个类做 SDK 构造,另一个做
bootstrap;Python 端把两者合一放在 `factory.py`,framework 端
只看到 `SecretProviderFactory` Protocol。

`AwsClientFactory`(`create_clients(properties)`):负责
- 构造 boto3 `kms` client(`boto3.client("kms", **kwargs)`)
- 构造 boto3 `secretsmanager` client(`boto3.client("secretsmanager", **kwargs)`)
- boto3 的 default credential chain 处理 env / IAM role / profile

`AwsSecretProviderFactory`(`SecretProviderFactory` Protocol 实现):
- `name` = `f"aws-{region}"`
- `backend` = `SecretBackend.AWS`
- `capability` = 静态声明
- `version` = `"0.2.0"`
- `create(configuration) -> SecretProviderSession`:
  1. 用 `AwsClientFactory` 拿 (kms_client, sm_client)
  2. 用 `AwsConfigurationResolver` 拿 `ResolvedAwsConfiguration`
  3. 构造 `AwsSecretClient`
  4. `close_action` 不需要 — boto3 client 不持有 socket

错误转译:
- `boto3.client("kms", **kwargs)` 失败 → `SecretConfigurationException`
- `kms.generate_data_key` / `sm.get_secret_value` 失败 → 由 client.py
  转译为 `SecretException` / `SecretCryptoException` /
  `SecretIntegrityException`

English
--------
Combined factory for the AWS backend. Mirrors Java
`AwsSecretBootstrapProviderFactory` + private `AwsClientFactory`.
boto3 handles credential chain resolution; the factory just
constructs the two named clients and wires them into the
5-SPI composite.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol, runtime_checkable

import boto3
import botocore.exceptions

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret_aws_kms.client import AwsSecretClient
from atlas_richie.secret_aws_kms.configuration import AwsConfigurationResolver
from atlas_richie.secret_aws_kms.properties import AwsSecretProperties

_logger = logging.getLogger("atlas_richie.secret_aws_kms.factory")


@runtime_checkable
class _BotoClientFactory(Protocol):
    """Test seam: tests may inject a pre-built (kms, sm) client
    pair to skip the boto3 bootstrap path."""

    def __call__(
        self,
        properties: AwsSecretProperties,
    ) -> tuple[object, object]: ...


class AwsClientFactory:
    """Build (kms_client, sm_client) from `AwsSecretProperties`."""

    __slots__ = ()

    def create_clients(
        self,
        properties: AwsSecretProperties,
    ) -> tuple[object, object]:
        try:
            kms = boto3.client("kms", **properties.to_kms_client_kwargs())
            sm = boto3.client("secretsmanager", **properties.to_sm_client_kwargs())
        except botocore.exceptions.BotoCoreError as error:
            raise SecretConfigurationException(
                f"aws: failed to construct boto3 clients "
                f"(region={properties.region!r}): {error}",
            ) from error
        return kms, sm


def _default_client_factory(
    properties: AwsSecretProperties,
) -> tuple[object, object]:
    return AwsClientFactory().create_clients(properties)


class AwsSecretProviderFactory:
    """`SecretProviderFactory` for the AWS backend."""

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
        properties: AwsSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: _BotoClientFactory | None = None,
        configuration_resolver: AwsConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.AWS,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._client_factory = client_factory or _default_client_factory
        self._configuration_resolver = (
            configuration_resolver or AwsConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> AwsSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"aws-{self._properties.region}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return SecretCapability(
            can_read=True,
            can_write=False,
            can_rotate=True,
            can_list=True,
            encrypts_at_rest=True,
            signs_values=False,
            cacheable=True,
        )

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
            timeout_seconds=self._properties.timeout_seconds,
            retries=3,
            namespace=self._properties.region,
        )

    def create(
        self,
        configuration: SecretProviderConfiguration,
    ) -> SecretProviderSession:
        kms_client, sm_client = self._client_factory(self._properties)
        resolved = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        return AwsSecretClient(
            resolved=resolved,
            kms_client=kms_client,
            sm_client=sm_client,
            close_action=None,  # boto3 clients don't need explicit close
            descriptor_backend=self._descriptor_backend,
        )


__all__ = [
    "AwsClientFactory",
    "AwsSecretProviderFactory",
]
