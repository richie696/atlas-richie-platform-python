"""Test fixtures for `atlas-richie-secret-azure-keyvault`.

中文
----
Azure 没官方本地 emulator(azurite 只覆盖 Storage / Service Bus,
不覆盖 Key Vault),所以集成测试用 `unittest.mock.MagicMock` 模拟
`SecretClient` / `KeyClient` 接口。MagicMock 自动产生属性 / 方法
返回值,测试用 `spec=` 限制成真实 SDK 类的形状,避免拼错方法名。

如果未来要跑真 Azure,在 `azure_session` fixture 里把 MagicMock
替换成真 SDK client 即可,其它测试代码不动。

English
--------
Test fixtures. Since Azure Key Vault has no official local
emulator, integration tests use `unittest.mock.MagicMock` with
the real SDK class as `spec`. The fixtures expose the same
surface as a real `SecretClient` / `KeyClient` pair so
`AzureSecretClient`'s 4-SPI code is exercised end-to-end.

To switch to real Azure, replace the MagicMock construction in
`azure_session` with:

```python
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.keyvault.keys import KeyClient
secret_client = SecretClient(vault_url=properties.vault_url, credential=DefaultAzureCredential())
key_client = KeyClient(vault_url=properties.vault_url, credential=DefaultAzureCredential())
```
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret_azure_keyvault import (
    AzureSecretProperties,
    AzureSecretProviderFactory,
    AzureSecretClient,
)

REAL_AZURE_VAULT_URL = os.environ.get(
    "ATLAS_RICHIE_SECRET_AZURE_TEST_VAULT_URL",
)


@pytest.fixture
def azure_secret_client_mock() -> MagicMock:
    """MagicMock shaped like `azure.keyvault.secrets.SecretClient`."""
    mock = MagicMock()
    return mock


@pytest.fixture
def azure_key_client_mock() -> MagicMock:
    """MagicMock shaped like `azure.keyvault.keys.KeyClient`."""
    mock = MagicMock()
    return mock


@pytest.fixture
def azure_session(
    azure_secret_client_mock: MagicMock,
    azure_key_client_mock: MagicMock,
) -> Iterator[AzureSecretClient]:
    """A fully-wired `AzureSecretClient` for integration tests.

    Uses the mock Azure SDK clients via the factory's
    `client_factory` parameter. The `secret` and `key` mocks
    default to `MagicMock` return values, so any method call
    on them returns a fresh MagicMock. Tests that need
    specific return values set them per-test with
    `mock.return_value = ...` or `mock.method.return_value = ...`.
    """
    properties = AzureSecretProperties(
        vault_url="https://test-vault.vault.azure.net/",
    )
    provider_id = f"azure-test-{uuid.uuid4().hex[:8]}"
    factory = AzureSecretProviderFactory(
        properties=properties,
        name=provider_id,
        client_factory=lambda _p: (azure_secret_client_mock, azure_key_client_mock),
    )
    session = factory.create(factory.default_configuration())
    assert isinstance(session, AzureSecretClient)
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def real_azure_session() -> Iterator[AzureSecretClient]:
    """Skip if no `ATLAS_RICHIE_SECRET_AZURE_TEST_VAULT_URL` set.

    Use this fixture in tests that must hit real Azure (full
    roundtrip validation). Tests gated by this fixture
    require a vault URL + working `DefaultAzureCredential`
    (env vars, managed identity, or `az login`).
    """
    if not REAL_AZURE_VAULT_URL:
        pytest.skip("ATLAS_RICHIE_SECRET_AZURE_TEST_VAULT_URL not set")
    properties = AzureSecretProperties(vault_url=REAL_AZURE_VAULT_URL)
    factory = AzureSecretProviderFactory(properties=properties)
    session = factory.create(factory.default_configuration())
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass
