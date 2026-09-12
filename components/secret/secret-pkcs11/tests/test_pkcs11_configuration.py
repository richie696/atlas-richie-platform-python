"""Unit tests for `Pkcs11ConfigurationResolver`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret_pkcs11 import Pkcs11SecretProperties
from atlas_richie.secret_pkcs11.configuration import Pkcs11ConfigurationResolver


def _props(**kwargs):
    base = dict(
        module_path="/usr/lib/softhsm.so",
        token_label="t",
        user_pin="p",
    )
    base.update(kwargs)
    return Pkcs11SecretProperties(**base)


def test_resolve_happy_path() -> None:
    p = _props()
    resolved = Pkcs11ConfigurationResolver().resolve(p, provider_id="pkcs11-main")
    assert resolved.provider_id == "pkcs11-main"
    assert resolved.properties is p
    assert len(resolved.configuration_hash) == 64
    assert resolved.capability.can_read is False
    assert resolved.capability.can_list is False
    assert resolved.capability.signs_values is True
    assert resolved.capability.encrypts_at_rest is True


def test_resolve_rejects_empty_module_path() -> None:
    # Pydantic catches the empty module_path first; the resolver
    # itself never sees an invalid value through normal use.
    with pytest.raises(ValidationError):
        Pkcs11SecretProperties(
            module_path="", token_label="t", user_pin="p",
        )


def test_resolve_rejects_empty_token_label() -> None:
    # If we somehow bypass the pydantic validator (e.g. by
    # passing an already-validated object), the resolver
    # itself rejects an empty token label.
    p = _props()
    object.__setattr__(p, "token_label", "")
    with pytest.raises(SecretConfigurationException) as exc:
        Pkcs11ConfigurationResolver().resolve(p)
    assert "token_label" in str(exc.value)


def test_configuration_hash_changes_with_module() -> None:
    p1 = _props(module_path="/lib/a.so")
    p2 = _props(module_path="/lib/b.so")
    h1 = Pkcs11ConfigurationResolver().resolve(p1).configuration_hash
    h2 = Pkcs11ConfigurationResolver().resolve(p2).configuration_hash
    assert h1 != h2


def test_configuration_hash_changes_with_key_bindings() -> None:
    p1 = _props()
    p2 = _props(key_bindings={"logical": "physical"})
    h1 = Pkcs11ConfigurationResolver().resolve(p1).configuration_hash
    h2 = Pkcs11ConfigurationResolver().resolve(p2).configuration_hash
    assert h1 != h2


def test_capability_backend_is_pkcs11() -> None:
    assert SecretBackend.PKCS11.value == "pkcs11"
