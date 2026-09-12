"""Unit tests for `Pkcs11SecretProperties`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret_pkcs11 import Pkcs11SecretProperties, Pkcs11SignMechanism

pytestmark = pytest.mark.unit


def test_module_path_required() -> None:
    with pytest.raises(ValidationError):
        Pkcs11SecretProperties(token_label="x", user_pin="x")


def test_token_label_required() -> None:
    with pytest.raises(ValidationError):
        Pkcs11SecretProperties(module_path="/usr/lib/x.so", user_pin="x")


def test_user_pin_required() -> None:
    with pytest.raises(ValidationError):
        Pkcs11SecretProperties(module_path="/usr/lib/x.so", token_label="x")


def test_defaults() -> None:
    p = Pkcs11SecretProperties(
        module_path="/usr/lib/x.so",
        token_label="t",
        user_pin="p",
    )
    assert p.default_sign_mechanism is Pkcs11SignMechanism.SHA256_RSA_PKCS
    assert p.key_bindings == {}


def test_key_bindings_explicit() -> None:
    p = Pkcs11SecretProperties(
        module_path="/usr/lib/x.so",
        token_label="t",
        user_pin="p",
        key_bindings={"tenant-master": "prod-rsa-2048"},
    )
    assert p.key_bindings == {"tenant-master": "prod-rsa-2048"}


def test_env_prefix_drives_field_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_RICHIE_SECRET_PKCS11_MODULE_PATH", "/env/lib.so")
    monkeypatch.setenv("ATLAS_RICHIE_SECRET_PKCS11_TOKEN_LABEL", "env-tok")
    monkeypatch.setenv("ATLAS_RICHIE_SECRET_PKCS11_USER_PIN", "env-pin")
    p = Pkcs11SecretProperties()
    assert p.module_path == "/env/lib.so"
    assert p.token_label == "env-tok"
    assert p.user_pin == "env-pin"
