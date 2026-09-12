"""Integration fixtures for `atlas-richie-secret-openbao`.

中文
----
OpenBao API 100% 兼容 Vault(KV v2 + Transit),所以本仓的集成测试
**复用**本地 `vault-dev` 容器(127.0.0.1:8200)做底层 HTTP 通信。
如果本机有真正的 OpenBao 实例,改 `OPENBAO_TEST_URL` env var 即可。

fixtures:
- `openbao_hvac_client` — 已 auth 过的 hvac.Client
- `openbao_session` — 完整的 `OpenBaoSecretProviderFactory.create()`
  输出,带 `descriptor.backend == SecretBackend.OPENBAO` 校验

如果 server 不可达,整个 test module 跳过(不阻塞没 OpenBao 的 CI)。

English
--------
Integration fixtures. OpenBao is API-compatible with Vault, so
this module reuses the same `vault-dev` container on
`127.0.0.1:8200` for HTTP traffic. Set `OPENBAO_TEST_URL` env
var to point at a real OpenBao instance.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator

import hvac
import pytest

from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret_openbao import (
    OpenBaoSecretProperties,
    OpenBaoSecretProviderFactory,
    VaultSecretClient,
)

OPENBAO_URL = os.environ.get(
    "OPENBAO_TEST_URL",
    "http://127.0.0.1:8200",
)
OPENBAO_TOKEN = os.environ.get(
    "OPENBAO_TEST_TOKEN",
    "root-token-dev",
)
KV_MOUNT = "secret"
TRANSIT_MOUNT = "transit"
TRANSIT_KEY_AES = "test-key"
TRANSIT_KEY_ECDSA = "ecdsa-test"


def _openbao_reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/v1/sys/health", timeout=2) as response:  # noqa: S310 - dev only
            return response.status in (200, 429, 472, 473)
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _ensure_mounts(client: hvac.Client) -> None:
    try:
        client.sys.mount.kv_v2(KV_MOUNT)
    except hvac.exceptions.InvalidRequest:
        pass
    except Exception:
        mounts = client.sys.list_mounted_secrets_engines()["data"]
        if f"{KV_MOUNT}/" in mounts:
            return
        raise
    try:
        client.sys.mount.transit(TRANSIT_MOUNT)
    except hvac.exceptions.InvalidRequest:
        pass
    except Exception:
        mounts = client.sys.list_mounted_secrets_engines()["data"]
        if f"{TRANSIT_MOUNT}/" in mounts:
            return
        raise


def _ensure_transit_keys(client: hvac.Client) -> None:
    try:
        client.secrets.transit.create_key(
            name=TRANSIT_KEY_AES, key_type="aes256-gcm96", mount_point=TRANSIT_MOUNT,
        )
    except hvac.exceptions.InvalidRequest as error:
        if "key already exists" not in str(error).lower():
            raise
    try:
        client.secrets.transit.create_key(
            name=TRANSIT_KEY_ECDSA, key_type="ecdsa-p256", mount_point=TRANSIT_MOUNT,
        )
    except hvac.exceptions.InvalidRequest as error:
        if "key already exists" not in str(error).lower():
            raise


@pytest.fixture
def openbao_hvac_client() -> Iterator[hvac.Client]:
    if not _openbao_reachable(OPENBAO_URL):
        pytest.skip(f"OpenBao (or Vault) not reachable at {OPENBAO_URL}")
    client = hvac.Client(url=OPENBAO_URL, token=OPENBAO_TOKEN, timeout=10)
    _ensure_mounts(client)
    _ensure_transit_keys(client)
    try:
        yield client
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def openbao_session(
    openbao_hvac_client: hvac.Client,
) -> Iterator[VaultSecretClient]:
    properties = OpenBaoSecretProperties(
        url=OPENBAO_URL,
        token=OPENBAO_TOKEN,
        kv_mount=KV_MOUNT,
        transit_mount=TRANSIT_MOUNT,
    )
    provider_id = f"openbao-test-{uuid.uuid4().hex[:8]}"
    factory = OpenBaoSecretProviderFactory(
        properties=properties,
        name=provider_id,
        client_factory=lambda _p: openbao_hvac_client,
    )
    session = factory.create(factory.default_configuration())
    # The whole point of the OpenBao wheel: descriptor.backend
    # must be OPENBAO, not VAULT.
    assert session.descriptor.backend is SecretBackend.OPENBAO, (
        f"expected SecretBackend.OPENBAO, got {session.descriptor.backend!r}"
    )
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass
