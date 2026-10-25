"""Deployment configuration for encrypted runtime database locator storage."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from ..security.key_ring import KEY_ID_PATTERN, parse_base64_key_ring
from ..security.secret_cipher import AesGcmSecretCipher
from .runtime_database_locator_file_store import RuntimeDatabaseLocatorFileStore

_PATH_ENV = "SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH"
_ACTIVE_KEY_ID_ENV = "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_ACTIVE_KEY_ID"
_KEY_RING_ENV = "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_KEY_RING"


class RuntimeDatabaseLocatorConfigurationError(ValueError):
    """The deployment-owned locator path or encryption key ring is invalid."""


@dataclass(frozen=True, slots=True)
class RuntimeDatabaseLocatorConfiguration:
    """Absolute locator path and independent retained encryption key ring."""

    path: Path
    active_key_id: str
    keys: Mapping[str, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        immutable_keys = MappingProxyType(dict(self.keys))
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise RuntimeDatabaseLocatorConfigurationError(
                "runtime database locator path must be absolute"
            )
        if (
            not isinstance(self.active_key_id, str)
            or KEY_ID_PATTERN.fullmatch(self.active_key_id) is None
            or self.active_key_id not in immutable_keys
            or any(len(key) != 32 for key in immutable_keys.values())
        ):
            raise RuntimeDatabaseLocatorConfigurationError(
                "runtime database locator encryption key configuration is invalid"
            )
        object.__setattr__(self, "keys", immutable_keys)

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> RuntimeDatabaseLocatorConfiguration:
        """Load an explicitly provisioned path and AES-256-GCM key ring."""
        values = os.environ if environment is None else environment
        try:
            path_text = values[_PATH_ENV]
            if not isinstance(path_text, str) or not path_text:
                raise RuntimeDatabaseLocatorConfigurationError(
                    "runtime database locator path must be absolute"
                )
            active_key_id = values[_ACTIVE_KEY_ID_ENV]
            keys = parse_base64_key_ring(
                values[_KEY_RING_ENV],
                invalid_message=(
                    "runtime database locator encryption key ring is invalid"
                ),
                minimum_key_bytes=32,
            )
            if any(len(key) != 32 for key in keys.values()):
                raise RuntimeDatabaseLocatorConfigurationError(
                    "runtime database locator encryption keys must be 32 bytes"
                )
            return cls(Path(path_text), active_key_id, keys)
        except KeyError:
            raise RuntimeDatabaseLocatorConfigurationError(
                "runtime database locator deployment configuration is incomplete"
            ) from None
        except ValueError as error:
            if isinstance(error, RuntimeDatabaseLocatorConfigurationError):
                raise
            raise RuntimeDatabaseLocatorConfigurationError(
                "runtime database locator deployment configuration is invalid"
            ) from None

    def create_store(self) -> RuntimeDatabaseLocatorFileStore:
        """Build the file Adapter with the configured active/retained keys."""
        cipher = AesGcmSecretCipher(self.active_key_id, self.keys)
        return RuntimeDatabaseLocatorFileStore(self.path, cipher)
