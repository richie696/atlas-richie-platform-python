"""Object storage contracts: engine SPI, value objects, ACL vocabulary, registry.

Zero dependencies — no SDK. Ported from the Java `atlas-richie-storage-core`
contracts; the Java `StorageEngine` interface carries many Java-type overloads
(File / InputStream / Collection / Map) which collapse into a small Python
surface. Provider adapters (S3/MinIO, OSS, COS, ...) live in separate packages.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, BinaryIO, Protocol, runtime_checkable


class StorageError(RuntimeError):
    """Base storage error."""


class ObjectNotFoundError(StorageError):
    """The requested object does not exist."""


class BucketNotFoundError(StorageError):
    """The requested bucket does not exist."""


class Acl(StrEnum):
    """Canned ACL vocabulary, normalized across providers."""

    PRIVATE = "private"
    PUBLIC_READ = "public-read"
    PUBLIC_READ_WRITE = "public-read-write"
    AUTHENTICATED_READ = "authenticated-read"

    @classmethod
    def parse(cls, value: str | Acl | None) -> Acl:
        """Accept the enum, its value, or common provider spellings."""
        if value is None:
            return cls.PRIVATE
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower().replace("_", "-")
        aliases = {
            "publicread": cls.PUBLIC_READ,
            "publicreadwrite": cls.PUBLIC_READ_WRITE,
            "authenticatedread": cls.AUTHENTICATED_READ,
            "bucket-owner-full-control": cls.PRIVATE,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return cls(normalized)
        except ValueError as error:
            raise ValueError(f"unsupported ACL: {value}") from error


@dataclass(frozen=True, slots=True)
class UploadResult:
    bucket: str
    key: str
    etag: str | None = None
    version_id: str | None = None
    size: int | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class ObjectStat:
    bucket: str
    key: str
    size: int
    etag: str | None = None
    content_type: str | None = None
    last_modified: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DownloadResult:
    bucket: str
    key: str
    stream: BinaryIO
    stat: ObjectStat | None = None


@dataclass(frozen=True, slots=True)
class ObjectListing:
    bucket: str
    keys: tuple[str, ...]
    truncated: bool = False
    next_token: str | None = None


@dataclass(frozen=True, slots=True)
class DirectUploadPolicy:
    """A presigned (or fallback proxied) client-side upload grant."""

    success: bool
    method: str = "PUT"
    upload_url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    form_fields: dict[str, str] = field(default_factory=dict)
    bucket: str | None = None
    key: str | None = None
    expire_at: datetime | None = None
    fallback: bool = False
    error_message: str | None = None

    @classmethod
    def failure(cls, message: str) -> DirectUploadPolicy:
        return cls(success=False, error_message=message)


@dataclass(frozen=True, slots=True)
class DirectDownloadPolicy:
    """A presigned (or fallback proxied) client-side download grant."""

    success: bool
    method: str = "GET"
    download_url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    bucket: str | None = None
    key: str | None = None
    expire_at: datetime | None = None
    fallback: bool = False
    error_message: str | None = None

    @classmethod
    def failure(cls, message: str) -> DirectDownloadPolicy:
        return cls(success=False, error_message=message)


@runtime_checkable
class ObjectStorageEngine(Protocol):
    """The provider-neutral object storage surface."""

    def put_object(
        self,
        bucket: str,
        key: str,
        data: bytes | BinaryIO,
        *,
        content_type: str | None = None,
        acl: Acl | str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> UploadResult: ...

    def get_object(self, bucket: str, key: str) -> DownloadResult: ...

    def stat_object(self, bucket: str, key: str) -> ObjectStat: ...

    def delete_object(self, bucket: str, key: str) -> bool: ...

    def list_objects(
        self, bucket: str, *, prefix: str = "", limit: int = 1000, token: str | None = None
    ) -> ObjectListing: ...

    def presign_upload(
        self, bucket: str, key: str, *, expires_seconds: int = 900, content_type: str | None = None
    ) -> DirectUploadPolicy: ...

    def presign_download(
        self, bucket: str, key: str, *, expires_seconds: int = 900
    ) -> DirectDownloadPolicy: ...


class StorageEngineRegistry:
    """Named engine registry, mirroring the Java `StorageEngineRegistry`."""

    def __init__(self) -> None:
        self._engines: dict[str, ObjectStorageEngine] = {}
        self._default: str | None = None
        self._lock = threading.Lock()

    def register(self, name: str, engine: ObjectStorageEngine, *, default: bool = False) -> None:
        if not name or not name.strip():
            raise ValueError("engine name must not be blank")
        with self._lock:
            if name in self._engines:
                raise ValueError(f"storage engine already registered: {name}")
            self._engines[name] = engine
            if default or self._default is None:
                self._default = name

    def get(self, name: str | None = None) -> ObjectStorageEngine:
        with self._lock:
            key = name if name is not None else self._default
            if key is None:
                raise StorageError("no storage engine registered")
            engine = self._engines.get(key)
            if engine is None:
                raise StorageError(f"storage engine not registered: {key}")
            return engine

    def replace(self, name: str, engine: ObjectStorageEngine) -> ObjectStorageEngine:
        """Hot-swap an engine, returning the previous one (对位 Java refresh).

        The default designation is preserved: swapping the default engine does
        not silently promote another.
        """
        if not name or not name.strip():
            raise ValueError("engine name must not be blank")
        with self._lock:
            previous = self._engines.get(name)
            if previous is None:
                raise StorageError(f"storage engine not registered: {name}")
            self._engines[name] = engine
            return previous

    def unregister(self, name: str) -> ObjectStorageEngine | None:
        """Remove an engine; if it was the default, fall back to the first remaining."""
        with self._lock:
            removed = self._engines.pop(name, None)
            if removed is not None and self._default == name:
                self._default = next(iter(self._engines), None)
            return removed

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._engines)

    @property
    def default_name(self) -> str | None:
        with self._lock:
            return self._default


from .keys import (
    MIN_EXPIRE_SECONDS,
    build_public_object_url,
    real_path,
    resolve_download_policy,
)

__all__ = [
    "MIN_EXPIRE_SECONDS",
    "real_path",
    "build_public_object_url",
    "resolve_download_policy",
    "Acl",
    "BucketNotFoundError",
    "DirectDownloadPolicy",
    "DirectUploadPolicy",
    "DownloadResult",
    "ObjectListing",
    "ObjectNotFoundError",
    "ObjectStat",
    "ObjectStorageEngine",
    "StorageEngineRegistry",
    "StorageError",
    "UploadResult",
]
