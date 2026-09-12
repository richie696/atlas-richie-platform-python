"""PKCS#11 / HSM properties — pydantic-settings env injection.

中文
----
对位 Java `cn.richie696.component.secret.provider.pkcs11.Pkcs11SecretProperties`。

字段:

- **HSM module**:`module_path`(PKCS#11 .so 路径,例如
  `/usr/lib/softhsm/libsofthsm2.so`)
- **Token**:`token_label`(HSM token label,必填)+ `user_pin`
- **Key bindings**:`key_bindings`(logical → 物理 key handle)
- **Sign**:`default_sign_mechanism`(默认 `CKM_SHA256_RSA_PKCS`,
  对位 Java 默认)

English
--------
Pydantic-settings env-injected configuration for PKCS#11.
Auth is delegated to the HSM via PIN; the framework does not
expose the choice of auth (HSM is the source of truth).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    pass


class Pkcs11SignMechanism(StrEnum):
    """PKCS#11 sign mechanism hints. The actual mechanism
    string is passed to `Session.sign(...)`; this enum
    captures the well-known subset. python-pkcs11 uses the
    bare mechanism name (e.g. `SHA256_RSA_PKCS`) without the
    `CKM_` prefix."""

    SHA256_RSA_PKCS = "SHA256_RSA_PKCS"
    ECDSA_SHA256 = "ECDSA_SHA256"
    SHA256_ECDSA = "SHA256_ECDSA"


class Pkcs11SecretProperties(BaseSettings):
    """Env-injected configuration for the PKCS#11 HSM backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_PKCS11_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    module_path: str = Field(...)
    token_label: str = Field(...)
    user_pin: str = Field(...)
    timeout_seconds: float = Field(default=30.0, gt=0)

    # Key bindings: logical → physical HSM key handle.
    key_bindings: dict[str, str] = Field(default_factory=dict)

    # Default sign mechanism (per-call override via
    # `sign(..., algorithm=...)` is also supported).
    default_sign_mechanism: Pkcs11SignMechanism = Field(
        default=Pkcs11SignMechanism.SHA256_RSA_PKCS,
    )

    @field_validator("module_path")
    @classmethod
    def _validate_module_path(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("module_path is required (.so file)")
        return value.strip()


__all__ = [
    "Pkcs11SignMechanism",
    "Pkcs11SecretProperties",
]
