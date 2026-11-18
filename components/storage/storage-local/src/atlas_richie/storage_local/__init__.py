"""本地文件系统对象存储引擎（纯标准库）。

对位 Java `atlas-richie-storage-local` 的 `LocalStorageEngine`。这是唯一
不需要任何外部服务就能跑的 provider，适合开发、测试与 CI。

与 Java 的两处有意差异：
- 元数据存在对象旁的 sidecar JSON 里，而不是 MyBatis 表 + GlobalCache，
  因此本包零第三方依赖、零外部服务。
- 不支持 presign：本地文件系统没有可签名的 URL 语义，直接返回失败策略，
  而不是伪造一个看起来能用的地址。

安全：key 禁止 `..` / `:` / 绝对路径（与 Java isSafeKey 一致），并在解析
真实路径后再次确认落在 bucket 根目录内，以挡住符号链接逃逸。写入走同目录
临时文件 + `os.replace` 原子替换，读者永远看不到半个对象。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from atlas_richie.storage_core import (
    Acl,
    BucketNotFoundError,
    DirectDownloadPolicy,
    DirectUploadPolicy,
    DownloadResult,
    ObjectListing,
    ObjectNotFoundError,
    ObjectStat,
    StorageError,
    UploadResult,
)

_META_SUFFIX = ".atlas-meta.json"
_DEFAULT_MAX_SIZE = 1_048_576
_CHUNK = 65_536


def _safe_key(key: str) -> str:
    if (
        not key
        or ".." in key
        or ":" in key
        or key.startswith("/")
        or key.startswith("\\")
    ):
        raise StorageError(f"unsafe object key: {key!r}")
    return key


class LocalStorageEngine:
    """`ObjectStorageEngine` backed by a directory tree: root/bucket/key."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_size: int = _DEFAULT_MAX_SIZE,
        name: str = "local",
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_size = int(max_size)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def root(self) -> Path:
        return self._root

    # ── 路径解析 ────────────────────────────────────────────────────

    def _bucket_dir(self, bucket: str, *, create: bool = False) -> Path:
        if not bucket or "/" in bucket or "\\" in bucket or bucket in (".", ".."):
            raise StorageError(f"unsafe bucket name: {bucket!r}")
        path = self._root / bucket
        if create:
            path.mkdir(parents=True, exist_ok=True)
        elif not path.is_dir():
            raise BucketNotFoundError(f"bucket not found: {bucket}")
        return path.resolve()

    def _object_path(self, bucket: str, key: str, *, create: bool = False) -> Path:
        bucket_dir = self._bucket_dir(bucket, create=create)
        _safe_key(key)
        target = (bucket_dir / key).resolve()
        # resolve() 已展开符号链接；再确认包含关系，挡住指向根目录外的链接。
        if not target.is_relative_to(bucket_dir):
            raise StorageError(f"object key escapes bucket: {key!r}")
        return target

    @staticmethod
    def _meta_path(target: Path) -> Path:
        return target.with_name(target.name + _META_SUFFIX)

    def _read_meta(self, target: Path) -> dict:
        meta = self._meta_path(target)
        if not meta.is_file():
            return {}
        try:
            return json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    # ── 写入 ────────────────────────────────────────────────────────

    def put_object(
        self,
        bucket: str,
        key: str,
        data: bytes | BinaryIO,
        *,
        content_type: str | None = None,
        acl: Acl | str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> UploadResult:
        target = self._object_path(bucket, key, create=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".atlas-tmp-")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as out:
                if isinstance(data, bytes):
                    chunks = [data]
                else:
                    chunks = iter(lambda: data.read(_CHUNK), b"")
                for chunk in chunks:
                    size += len(chunk)
                    if size > self._max_size:
                        raise StorageError(
                            f"object exceeds max_size {self._max_size}: {key!r}"
                        )
                    digest.update(chunk)
                    out.write(chunk)
            etag = digest.hexdigest()
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        resolved_acl = Acl.parse(acl) if acl is not None else Acl.PRIVATE
        self._meta_path(target).write_text(
            json.dumps(
                {
                    "content_type": content_type,
                    "acl": resolved_acl.value,
                    "metadata": dict(metadata or {}),
                    "etag": etag,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return UploadResult(
            bucket=bucket, key=key, etag=etag, size=size, url=target.as_uri()
        )

    # ── 读取 / 元数据 ───────────────────────────────────────────────

    def _stat(self, bucket: str, key: str, target: Path) -> ObjectStat:
        info = target.stat()
        meta = self._read_meta(target)
        return ObjectStat(
            bucket=bucket,
            key=key,
            size=info.st_size,
            etag=meta.get("etag"),
            content_type=meta.get("content_type"),
            last_modified=datetime.fromtimestamp(info.st_mtime, tz=timezone.utc),
            metadata=dict(meta.get("metadata") or {}),
        )

    def stat_object(self, bucket: str, key: str) -> ObjectStat:
        target = self._object_path(bucket, key)
        if not target.is_file():
            raise ObjectNotFoundError(f"object not found: {bucket}/{key}")
        return self._stat(bucket, key, target)

    def get_object(self, bucket: str, key: str) -> DownloadResult:
        target = self._object_path(bucket, key)
        if not target.is_file():
            raise ObjectNotFoundError(f"object not found: {bucket}/{key}")
        stat = self._stat(bucket, key, target)
        return DownloadResult(bucket=bucket, key=key, stream=target.open("rb"), stat=stat)

    def delete_object(self, bucket: str, key: str) -> bool:
        target = self._object_path(bucket, key)
        existed = target.is_file()
        target.unlink(missing_ok=True)
        self._meta_path(target).unlink(missing_ok=True)
        return existed

    # ── 列举 ────────────────────────────────────────────────────────

    def list_objects(
        self, bucket: str, *, prefix: str = "", limit: int = 1000, token: str | None = None
    ) -> ObjectListing:
        bucket_dir = self._bucket_dir(bucket)
        if limit <= 0:
            raise ValueError("limit must be positive")
        keys: list[str] = []
        for path in sorted(bucket_dir.rglob("*")):
            if not path.is_file() or path.name.endswith(_META_SUFFIX):
                continue
            if path.name.startswith(".atlas-tmp-"):
                continue
            relative = path.relative_to(bucket_dir).as_posix()
            if prefix and not relative.startswith(prefix):
                continue
            if token is not None and relative <= token:
                continue
            keys.append(relative)
        truncated = len(keys) > limit
        page = keys[:limit]
        return ObjectListing(
            bucket=bucket,
            keys=tuple(page),
            truncated=truncated,
            next_token=page[-1] if truncated and page else None,
        )

    # ── presign：本地文件系统无此语义 ───────────────────────────────

    def presign_upload(
        self, bucket: str, key: str, *, expires_seconds: int = 900, content_type: str | None = None
    ) -> DirectUploadPolicy:
        return DirectUploadPolicy.failure(
            "local filesystem storage does not support presigned upload URLs"
        )

    def presign_download(
        self, bucket: str, key: str, *, expires_seconds: int = 900
    ) -> DirectDownloadPolicy:
        return DirectDownloadPolicy.failure(
            "local filesystem storage does not support presigned download URLs"
        )

    # ── bucket 生命周期 ─────────────────────────────────────────────

    def create_bucket(self, bucket: str) -> None:
        self._bucket_dir(bucket, create=True)

    def delete_bucket(self, bucket: str) -> bool:
        path = self._bucket_dir(bucket)
        shutil.rmtree(path)
        return True

    def close(self) -> None:
        """No persistent resources; present for SPI symmetry."""

    def __enter__(self) -> LocalStorageEngine:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


__all__ = ["LocalStorageEngine"]