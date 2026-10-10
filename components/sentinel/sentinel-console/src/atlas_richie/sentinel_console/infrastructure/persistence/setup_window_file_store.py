"""Deployment-owned setup-window state on the shared local atomic-file store."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ...application.bootstrap_ports import SetupWindowController, SetupWindowReader
from ...application.errors import BootstrapAuthorityUnavailable
from .local_atomic_file_store import (
    LocalAtomicFileConflict,
    LocalAtomicFileStore,
    LocalAtomicFileStoreError,
)

_SCHEMA_VERSION = 1
_MAX_FILE_BYTES = 1024
_MAX_CLOSE_ATTEMPTS = 4


class SetupWindowRevisionConflict(RuntimeError):
    """The deployment setup-window state changed before the requested write."""


@dataclass(frozen=True, slots=True)
class _SetupWindowState:
    is_open: bool
    revision: str

    def __post_init__(self) -> None:
        if type(self.is_open) is not bool:
            raise ValueError("setup-window state is invalid")
        try:
            parsed_revision = UUID(self.revision)
        except (AttributeError, TypeError, ValueError):
            raise ValueError("setup-window revision is invalid") from None
        if str(parsed_revision) != self.revision:
            raise ValueError("setup-window revision is invalid")


@dataclass(frozen=True, slots=True)
class SetupWindowSnapshot:
    """One consistent read of setup availability and its CAS revision."""

    is_open: bool
    revision: str | None


class SetupWindowFileStore(SetupWindowReader, SetupWindowController):
    """Read and CAS-write explicit setup availability across local workers.

    A missing data file is closed. Parent-directory, lock, or data corruption
    errors are unavailable and never become implicit authorization to set up.
    """

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("setup-window path must be absolute")
        self._files = LocalAtomicFileStore(path, maximum_bytes=_MAX_FILE_BYTES)

    async def is_setup_window_open(self) -> bool:
        """Return false only for the explicit missing-file closed state."""
        raw = await self._read_raw()
        return False if raw is None else self._decode(raw).is_open

    async def read_snapshot(self) -> SetupWindowSnapshot:
        """Read setup state and its compare-and-set token atomically."""
        raw = await self._read_raw()
        if raw is None:
            return SetupWindowSnapshot(is_open=False, revision=None)
        state = self._decode(raw)
        return SetupWindowSnapshot(state.is_open, state.revision)

    async def set_setup_window_open(
        self, is_open: bool, *, expected_revision: str | None
    ) -> str:
        """Write an explicit state if the caller's expected revision is current."""
        if type(is_open) is not bool:
            raise ValueError("setup-window value must be boolean")
        _validate_optional_revision(expected_revision)
        raw = await self._read_raw()
        current = None if raw is None else self._decode(raw)
        actual_revision = current.revision if current is not None else None
        if actual_revision != expected_revision:
            raise SetupWindowRevisionConflict(
                "setup-window revision changed"
            )
        candidate = _SetupWindowState(is_open=is_open, revision=str(uuid4()))
        try:
            await self._files.compare_and_swap(raw, self._encode(candidate))
        except LocalAtomicFileConflict:
            raise SetupWindowRevisionConflict(
                "setup-window revision changed"
            ) from None
        except LocalAtomicFileStoreError:
            raise BootstrapAuthorityUnavailable(
                "setup-window authority is unavailable"
            ) from None
        return candidate.revision

    async def close_setup_window_if_open(self) -> None:
        """Close the durable grant window idempotently with bounded CAS retry."""
        for _attempt in range(_MAX_CLOSE_ATTEMPTS):
            raw = await self._read_raw()
            if raw is None:
                return
            current = self._decode(raw)
            if not current.is_open:
                return
            candidate = _SetupWindowState(
                is_open=False, revision=str(uuid4())
            )
            try:
                await self._files.compare_and_swap(raw, self._encode(candidate))
                return
            except LocalAtomicFileConflict:
                continue
            except LocalAtomicFileStoreError:
                raise BootstrapAuthorityUnavailable(
                    "setup-window authority is unavailable"
                ) from None
        raise SetupWindowRevisionConflict("setup-window kept changing")

    async def _read_raw(self) -> bytes | None:
        try:
            return await self._files.read()
        except LocalAtomicFileStoreError:
            raise BootstrapAuthorityUnavailable(
                "setup-window authority is unavailable"
            ) from None

    def _decode(self, raw: bytes) -> _SetupWindowState:
        try:
            document = json.loads(
                raw.decode("utf-8"), object_pairs_hook=_unique_object
            )
            if not isinstance(document, dict) or set(document) != {
                "schema_version",
                "is_open",
                "revision",
            }:
                raise ValueError("schema")
            if document["schema_version"] != _SCHEMA_VERSION:
                raise ValueError("schema")
            if type(document["schema_version"]) is not int:
                raise ValueError("schema")
            return _SetupWindowState(
                is_open=document["is_open"],
                revision=document["revision"],
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError):
            raise BootstrapAuthorityUnavailable(
                "setup-window authority is unavailable"
            ) from None

    @staticmethod
    def _encode(state: _SetupWindowState) -> bytes:
        return json.dumps(
            {
                "schema_version": _SCHEMA_VERSION,
                "is_open": state.is_open,
                "revision": state.revision,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")


def _validate_optional_revision(revision: str | None) -> None:
    if revision is None:
        return
    try:
        parsed_revision = UUID(revision)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("expected setup-window revision is invalid") from None
    if str(parsed_revision) != revision:
        raise ValueError("expected setup-window revision is invalid")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
