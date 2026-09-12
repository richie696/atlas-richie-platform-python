"""Integration test fixtures for `atlas-richie-secret-pkcs11`.

中文
----
集成测试连真 SoftHSM(token `atlas-test`,PIN `1234`),通过
`SOFTHSM2_CONF` env var 配置。每个 test 启动前会重新生成 RSA-2048
keypair(label `test-rsa`),test 结束后 destroy 清理。

如果 `SOFTHSM2_CONF` 没设 / token 不可达,整个 module skip。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pkcs11
import pytest

from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret_pkcs11 import (
    Pkcs11ClientFactory,
    Pkcs11SecretProperties,
    Pkcs11SecretProviderFactory,
    Pkcs11SecretClient,
)

SOFTHSM2_CONF_PATH = os.environ.get(
    "SOFTHSM2_CONF",
    "/tmp/softhsm/softhsm2.conf",
)
TOKEN_LABEL = "atlas-test"
USER_PIN = "1234"
KEY_LABEL = "test-rsa"
MODULE_PATH = os.environ.get(
    "ATLAS_RICHIE_SECRET_PKCS11_TEST_MODULE",
    "/opt/homebrew/lib/softhsm/libsofthsm2.so",
)


def _softhsm_reachable() -> bool:
    if not os.environ.get("SOFTHSM2_CONF"):
        return False
    try:
        lib = pkcs11.lib(MODULE_PATH)
        tokens = [t.label for t in lib.get_tokens()]
        return TOKEN_LABEL in tokens
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture
def pkcs11_lib_token() -> Iterator[tuple[object, object]]:
    if not _softhsm_reachable():
        pytest.skip(
            f"SoftHSM2 not reachable: SOFTHSM2_CONF={os.environ.get('SOFTHSM2_CONF')!r}",
        )
    properties = Pkcs11SecretProperties(
        module_path=MODULE_PATH,
        token_label=TOKEN_LABEL,
        user_pin=USER_PIN,
    )
    lib, token = Pkcs11ClientFactory().load_token(properties)
    yield lib, token


@pytest.fixture
def pkcs11_session(pkcs11_lib_token) -> Iterator[object]:
    """A fresh `pkcs11.Session` opened against the test token.

    The session is closed automatically on `with` exit. Tests
    that need the keypair should use the
    `pkcs11_rsa_keypair` fixture instead.
    """
    lib, token = pkcs11_lib_token
    session = token.open(user_pin=USER_PIN)
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def pkcs11_rsa_keypair(pkcs11_lib_token) -> Iterator[str]:
    """Generate an RSA-2048 keypair labeled `KEY_LABEL`; clean
    up on teardown so the next test starts fresh.

    SoftHSM creates **session-scoped** objects by default — the
    key would vanish the moment the session is closed. We
    pass `store=True` to make the keypair persistent on the
    token, and the initial creation requires a read-write
    session. The teardown then opens a fresh RW session to
    destroy the persisted objects.
    """
    _, token = pkcs11_lib_token
    # Clean up any prior test-rsa key (so the test is
    # idempotent across multiple runs).
    cleanup_session = token.open(rw=True, user_pin=USER_PIN)
    with cleanup_session:
        for obj in list(cleanup_session.get_objects()):
            try:
                if getattr(obj, "label", None) == KEY_LABEL:
                    obj.destroy()
            except pkcs11.exceptions.PKCS11Error:
                pass
    # Generate the persistent keypair on a fresh RW session.
    rw_session = token.open(rw=True, user_pin=USER_PIN)
    with rw_session:
        pub, priv = rw_session.generate_keypair(
            pkcs11.KeyType.RSA, 2048,
            label=KEY_LABEL,
            store=True,
        )
    try:
        yield KEY_LABEL
    finally:
        # Destroy on a fresh RW session.
        cleanup_session = token.open(rw=True, user_pin=USER_PIN)
        with cleanup_session:
            for obj in list(cleanup_session.get_objects()):
                try:
                    if getattr(obj, "label", None) == KEY_LABEL:
                        obj.destroy()
                except pkcs11.exceptions.PKCS11Error:
                    pass


@pytest.fixture
def pkcs11_session_client(
    pkcs11_rsa_keypair,
) -> Iterator[Pkcs11SecretClient]:
    """A fully-wired `Pkcs11SecretClient` against SoftHSM."""
    properties = Pkcs11SecretProperties(
        module_path=MODULE_PATH,
        token_label=TOKEN_LABEL,
        user_pin=USER_PIN,
        key_bindings={"test-rsa-logical": "test-rsa"},
    )
    factory = Pkcs11SecretProviderFactory(
        properties=properties,
        name=f"pkcs11-test-{uuid.uuid4().hex[:8]}",
    )
    session = factory.create(factory.default_configuration())
    assert isinstance(session, Pkcs11SecretClient)
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass
