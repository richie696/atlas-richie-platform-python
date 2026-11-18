"""对象键归一化与 ACL 驱动的直读策略（对位 Java `ObjectStorageKeys` /
`AbstractObjectStorageEngine` 的纯算法部分）。

`real_path` 是幂等拼接：直传策略回传的已是含 basePath 的真实 key，再次拼接
会产生 `basePath/basePath/...` 的误键。key 已带前缀时原样返回。

`resolve_download_policy` 按 ACL 决策：public-read / public-read-write 走
稳定公开 URL（无需签名、不过期）；私有 ACL 必须走 presign——绝不把私有对象
的公开 URL 发出去。过期时间下限 60s（对位 Java）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import Acl, DirectDownloadPolicy, ObjectStorageEngine

MIN_EXPIRE_SECONDS = 60


def real_path(base_path: str | None, key: str) -> str:
    """Idempotently join basePath and key (对位 Java `ObjectStorageKeys.realPath`)."""
    if not base_path or not base_path.strip():
        return key
    normalized_base = base_path.strip("/")
    normalized_key = key.lstrip("/")
    if normalized_key == normalized_base or normalized_key.startswith(normalized_base + "/"):
        return normalized_key
    return f"{normalized_base}/{normalized_key}"


def build_public_object_url(endpoint: str | None, bucket: str, real_key: str) -> str:
    """Virtual-host style unless the endpoint already addresses the bucket."""
    if not endpoint or not endpoint.strip():
        return real_key
    normalized = endpoint if endpoint.startswith(("http://", "https://")) else f"https://{endpoint}"
    stripped = normalized.rstrip("/")
    if f"{bucket}." in stripped:
        return f"{stripped}/{real_key}"
    host = stripped.removeprefix("https://").removeprefix("http://").rstrip("/")
    return f"https://{bucket}.{host}/{real_key}"


def resolve_download_policy(
    engine: ObjectStorageEngine,
    bucket: str,
    key: str,
    *,
    acl: Acl | str | None = None,
    endpoint: str | None = None,
    base_path: str | None = None,
    expires_seconds: int = 900,
) -> DirectDownloadPolicy:
    """ACL-driven download grant: public URL for public ACLs, presign otherwise."""
    if not key or not key.strip():
        return DirectDownloadPolicy.failure("对象键不能为空")
    safe_expire = max(expires_seconds, MIN_EXPIRE_SECONDS)
    resolved_acl = Acl.parse(acl)
    real_key = real_path(base_path, key)
    if resolved_acl in (Acl.PUBLIC_READ, Acl.PUBLIC_READ_WRITE):
        return DirectDownloadPolicy(
            success=True,
            download_url=build_public_object_url(endpoint, bucket, real_key),
            bucket=bucket,
            key=real_key,
            expire_at=datetime.now(timezone.utc) + timedelta(seconds=safe_expire),
            fallback=False,
        )
    return engine.presign_download(bucket, real_key, expires_seconds=safe_expire)


__all__ = [
    "MIN_EXPIRE_SECONDS",
    "real_path",
    "build_public_object_url",
    "resolve_download_policy",
]