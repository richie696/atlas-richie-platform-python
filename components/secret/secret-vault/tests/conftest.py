"""Integration test fixtures for `atlas-richie-secret-vault`.

中文
----
提供 `vault_client` / `vault_session` fixture,连真 Vault on
`127.0.0.1:8200`(env `ATLAS_RICHIE_SECRET_VAULT_TEST_URL` / `_TOKEN`
可覆盖)。每个 test 启动前:

1. 确认 KV v2 mount `secret/` + Transit mount `transit/` 存在
   (缺则通过 `client.sys.mount` 创建,幂等)
2. 在 `transit/` 下创建/复用 test key(`test-key` AES-256-GCM96 +
   `ecdsa-test` ECDSA-P256),因为 hvac 2.4 报"key type aes256-gcm96
   does not support signing"
3. test 结束后用 `client.secrets.kv.v2.delete_metadata_and_all_versions`
   清掉 test 写入的 KV v2 path;Transit keys 保留(便宜,跨 test 复用)

如果 `127.0.0.1:8200` 不可达,所有 test 自动 skip(`pytest.skip`),
不阻塞没 Vault 的 CI。

English
--------
Integration fixtures. Connects to real Vault on
`127.0.0.1:8200`; if the server is unreachable, tests are
skipped. Idempotently creates the `secret/` and `transit/`
mounts and the `test-key` / `ecdsa-test` Transit keys at
session start; cleans up KV v2 paths on teardown.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import hvac
import pytest

from atlas_richie.secret import SecretProviderConfiguration
from atlas_richie.secret_vault import (
    VaultSecretClient,
    VaultSecretProperties,
    VaultSecretProviderFactory,
)

VAULT_URL = os.environ.get(
    "ATLAS_RICHIE_SECRET_VAULT_TEST_URL",
    "http://127.0.0.1:8200",
)
VAULT_TOKEN = os.environ.get(
    "ATLAS_RICHIE_SECRET_VAULT_TEST_TOKEN",
    "root-token-dev",
)
KV_MOUNT = "secret"
TRANSIT_MOUNT = "transit"
TRANSIT_KEY_AES = "test-key"
TRANSIT_KEY_ECDSA = "ecdsa-test"


def _vault_reachable(url: str) -> bool:
    """Cheap health check: GET /v1/sys/health should return 200 / 429."""
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(f"{url}/v1/sys/health", timeout=2) as response:  # noqa: S310 - dev only
            return response.status in (200, 429, 472, 473)
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _ensure_mounts(client: hvac.Client) -> None:
    """Idempotently enable the KV v2 and Transit mounts we test against.

    `client.sys.mount` raises on duplicate; we treat that as success.
    """
    try:
        client.sys.mount.kv_v2(KV_MOUNT)
    except hvac.exceptions.InvalidRequest:
        # Already mounted — fine.
        pass
    except Exception:
        # Some hvac versions raise a generic `VaultError`. Probe by
        # listing mounts.
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
    """Idempotently create the two Transit keys we test against."""
    try:
        client.secrets.transit.create_key(
            name=TRANSIT_KEY_AES,
            key_type="aes256-gcm96",
            mount_point=TRANSIT_MOUNT,
        )
    except hvac.exceptions.InvalidRequest as error:
        if "key already exists" not in str(error).lower():
            raise
    try:
        client.secrets.transit.create_key(
            name=TRANSIT_KEY_ECDSA,
            key_type="ecdsa-p256",
            mount_point=TRANSIT_MOUNT,
        )
    except hvac.exceptions.InvalidRequest as error:
        if "key already exists" not in str(error).lower():
            raise


@pytest.fixture
def vault_client() -> Iterator[hvac.Client]:
    """Yield a fresh, authenticated `hvac.Client` against the test Vault.

    Skips the entire test module if the server is unreachable. The
    client is `logout()`-ed on teardown so the next test gets a
    new token (dev-mode auto-roots, so this is mostly cosmetic).
    """
    if not _vault_reachable(VAULT_URL):
        pytest.skip(f"Vault not reachable at {VAULT_URL}")
    client = hvac.Client(url=VAULT_URL, token=VAULT_TOKEN, timeout=10)
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
def vault_session(
    vault_client: hvac.Client,
) -> Iterator[VaultSecretClient]:
    """Yield a fully-wired `VaultSecretClient` for integration tests.

    Each test gets a fresh `VaultSecretClient` bound to a unique
    `provider_id` so descriptor / configuration lookups don't
    collide if a test leaves state behind. The underlying
    `hvac.Client` is the shared `vault_client` fixture, so mounts
    and keys are created once per session.
    """
    properties = VaultSecretProperties(
        url=VAULT_URL,
        token=VAULT_TOKEN,
        kv_mount=KV_MOUNT,
        transit_mount=TRANSIT_MOUNT,
    )
    provider_id = f"vault-test-{uuid.uuid4().hex[:8]}"
    factory = VaultSecretProviderFactory(
        properties=properties,
        name=provider_id,
        client_factory=lambda _props: vault_client,
    )
    session = factory.create(factory.default_configuration())
    assert isinstance(session, VaultSecretClient)
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def kv_path_factory(vault_client: hvac.Client) -> Iterator[str]:
    """Yield a function that returns a fresh KV v2 path for the test.

    Each path is recorded; on teardown all paths are deleted via
    `delete_metadata_and_all_versions`, so tests stay isolated
    even when the same Vault instance is reused.
    """
    written: list[str] = []

    def _make(prefix: str = "test") -> str:
        path = f"{prefix}/{uuid.uuid4().hex[:10]}"
        written.append(path)
        return path

    yield _make
    for path in written:
        try:
            vault_client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path,
                mount_point=KV_MOUNT,
            )
        except hvac.exceptions.InvalidPath:
            pass
        except Exception:  # noqa: BLE001
            pass
