"""Encrypted runtime database locator on a deployment-owned POSIX mount."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ...application.runtime_database_locator import (
    RuntimeDatabaseLocator,
    RuntimeDatabaseLocatorConflict,
    RuntimeDatabaseLocatorError,
    RuntimeDatabaseTarget,
)
from ..security.secret_cipher import (
    AesGcmSecretCipher,
    EncryptedSecret,
    SecretCipherError,
    SecretCipherFormat,
    SecretContext,
)
from .local_atomic_file_store import (
    LocalAtomicFileConflict,
    LocalAtomicFileStore,
    LocalAtomicFileStoreError,
)

_SCHEMA_VERSION = 2
_LEGACY_SCHEMA_VERSION = 1
_MAX_FILE_BYTES = 16_384
_OWNER_KIND = "sentinel-console-runtime"
_OWNER_ID = "target-database"
_FIELD_NAME = "database-url"


class RuntimeDatabaseLocatorFileStore:
    """Persist the URL outside its database using encryption and revision CAS.

    The deployment must provision a durable directory on a local POSIX
    filesystem that supports advisory locks and atomic same-directory replace.
    """

    def __init__(self, path: Path, cipher: AesGcmSecretCipher) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("runtime database locator path must be absolute")
        if not isinstance(cipher, AesGcmSecretCipher):
            raise TypeError("runtime database locator cipher is required")
        self._path = path
        self._cipher = cipher
        self._files = LocalAtomicFileStore(path, maximum_bytes=_MAX_FILE_BYTES)

    async def read(self) -> RuntimeDatabaseLocator | None:
        """Read a locator; return None only when its file is absent."""
        try:
            raw = await self._files.read()
            return None if raw is None else self._decode(raw)
        except LocalAtomicFileStoreError:
            raise RuntimeDatabaseLocatorError(
                "runtime database locator is unavailable"
            ) from None

    async def write(
        self,
        database_url: str,
        *,
        expected_revision: str | None,
        target: RuntimeDatabaseTarget | None = None,
    ) -> RuntimeDatabaseLocator:
        """Create or compare-and-swap the encrypted locator under a file lock."""
        if expected_revision is not None:
            try:
                parsed_revision = UUID(expected_revision)
            except (AttributeError, TypeError, ValueError):
                raise ValueError(
                    "expected runtime database revision is invalid"
                ) from None
            if str(parsed_revision) != expected_revision:
                raise ValueError("expected runtime database revision is invalid")
        candidate = RuntimeDatabaseLocator(database_url, str(uuid4()), target)
        try:
            existing = await self._files.read()
            current = None if existing is None else self._decode(existing)
            actual_revision = current.revision if current is not None else None
            if actual_revision != expected_revision:
                raise RuntimeDatabaseLocatorConflict(
                    "runtime database locator revision changed"
                )
            await self._files.compare_and_swap(existing, self._encode(candidate))
            return candidate
        except LocalAtomicFileConflict:
            raise RuntimeDatabaseLocatorConflict(
                "runtime database locator revision changed"
            ) from None
        except LocalAtomicFileStoreError:
            raise RuntimeDatabaseLocatorError(
                "runtime database locator is unavailable"
            ) from None

    def _decode(self, raw: bytes) -> RuntimeDatabaseLocator:
        try:
            document = json.loads(raw, object_pairs_hook=_unique_object)
            base_fields = {
                "schema_version",
                "revision",
                "format",
                "key_id",
                "payload",
            }
            if not isinstance(document, dict) or set(document) != base_fields:
                raise ValueError("schema")
            revision = document["revision"]
            if not isinstance(revision, str):
                raise ValueError("revision")
            payload = base64.b64decode(document["payload"], validate=True)
            envelope = EncryptedSecret(
                format=SecretCipherFormat(document["format"]),
                key_id=document["key_id"],
                payload=payload,
            )
            plaintext = self._cipher.decrypt(envelope, _context(revision))
            schema_version = document["schema_version"]
            if type(schema_version) is not int:
                raise ValueError("schema")
            if schema_version == _LEGACY_SCHEMA_VERSION:
                return RuntimeDatabaseLocator(plaintext, revision)
            if schema_version != _SCHEMA_VERSION:
                raise ValueError("schema")
            payload_document = json.loads(
                plaintext, object_pairs_hook=_unique_object
            )
            if not isinstance(payload_document, dict) or set(payload_document) != {
                "database_url",
                "target",
            }:
                raise ValueError("schema")
            target_document = payload_document["target"]
            target = (
                None
                if target_document is None
                else RuntimeDatabaseTarget(
                    hostname=target_document["hostname"],
                    addresses=tuple(target_document["addresses"]),
                )
            )
            return RuntimeDatabaseLocator(
                payload_document["database_url"], revision, target
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeDecodeError,
            binascii.Error,
            SecretCipherError,
        ):
            raise RuntimeDatabaseLocatorError(
                "runtime database locator cannot be decrypted"
            ) from None

    def _encode(self, locator: RuntimeDatabaseLocator) -> bytes:
        plaintext = json.dumps(
            {
                "database_url": locator.database_url,
                "target": (
                    None
                    if locator.target is None
                    else {
                        "hostname": locator.target.hostname,
                        "addresses": locator.target.addresses,
                    }
                ),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        envelope = self._cipher.encrypt(plaintext, _context(locator.revision))
        document = {
            "schema_version": _SCHEMA_VERSION,
            "revision": locator.revision,
            "format": envelope.format.value,
            "key_id": envelope.key_id,
            "payload": base64.b64encode(envelope.payload).decode("ascii"),
        }
        raw = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
        if len(raw) > _MAX_FILE_BYTES:
            raise RuntimeDatabaseLocatorError(
                "runtime database locator exceeds its storage limit"
            )
        return raw

def _context(revision: str) -> SecretContext:
    return SecretContext(
        owner_kind=_OWNER_KIND,
        owner_id=f"{_OWNER_ID}:{revision}",
        field_name=_FIELD_NAME,
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
