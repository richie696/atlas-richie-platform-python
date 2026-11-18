"""S3-compatible object storage adapter: AWS S3, MinIO, RustFS and peers.

Implements the `ObjectStorageEngine` SPI with boto3. MinIO-style endpoints need
path-style addressing; AWS S3 uses virtual-host style. Presigned URLs are produced
by boto3's SigV4 signer, so no signing logic is reimplemented here.

boto3 is a hard dependency of this adapter (not of storage-core), so installing the
core never pulls an SDK.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from typing import Any, BinaryIO

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

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

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
_NO_BUCKET_CODES = {"NoSuchBucket", "404"}


def _is_not_found(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    return code in _NOT_FOUND_CODES


class S3StorageEngine:
    """S3-compatible `ObjectStorageEngine`.

    Set `endpoint_url` and `force_path_style=True` for MinIO/RustFS. Credentials
    may be passed explicitly or left to the standard boto3 provider chain.
    """

    def __init__(
        self,
        *,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        force_path_style: bool = False,
        client: Any | None = None,
        presign_expires_seconds: int = 900,
    ) -> None:
        self._client = client or boto3.client(
            "s3",
            region_name=region_name,
            endpoint_url=endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path" if force_path_style else "auto"},
            ),
        )
        self._default_expires = presign_expires_seconds

    @property
    def client(self):
        return self._client

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
        body = data if isinstance(data, (bytes, bytearray)) else data.read()
        extra: dict[str, Any] = {}
        if content_type:
            extra["ContentType"] = content_type
        if acl is not None:
            extra["ACL"] = Acl.parse(acl).value
        if metadata:
            extra["Metadata"] = metadata
        try:
            response = self._client.put_object(Bucket=bucket, Key=key, Body=body, **extra)
        except ClientError as error:
            raise self._translate(error, bucket, key) from error
        return UploadResult(
            bucket=bucket,
            key=key,
            etag=(response.get("ETag") or "").strip('"') or None,
            version_id=response.get("VersionId"),
            size=len(body),
        )

    def get_object(self, bucket: str, key: str) -> DownloadResult:
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
        except ClientError as error:
            raise self._translate(error, bucket, key) from error
        payload = response["Body"].read()
        stat = ObjectStat(
            bucket=bucket,
            key=key,
            size=int(response.get("ContentLength", len(payload))),
            etag=(response.get("ETag") or "").strip('"') or None,
            content_type=response.get("ContentType"),
            last_modified=response.get("LastModified"),
            metadata=response.get("Metadata") or {},
        )
        return DownloadResult(bucket=bucket, key=key, stream=io.BytesIO(payload), stat=stat)

    def stat_object(self, bucket: str, key: str) -> ObjectStat:
        try:
            response = self._client.head_object(Bucket=bucket, Key=key)
        except ClientError as error:
            raise self._translate(error, bucket, key) from error
        return ObjectStat(
            bucket=bucket,
            key=key,
            size=int(response.get("ContentLength", 0)),
            etag=(response.get("ETag") or "").strip('"') or None,
            content_type=response.get("ContentType"),
            last_modified=response.get("LastModified"),
            metadata=response.get("Metadata") or {},
        )

    def delete_object(self, bucket: str, key: str) -> bool:
        """S3 delete is idempotent; report whether the object existed beforehand."""
        try:
            self._client.head_object(Bucket=bucket, Key=key)
        except ClientError as error:
            if _is_not_found(error):
                return False
            raise self._translate(error, bucket, key) from error
        try:
            self._client.delete_object(Bucket=bucket, Key=key)
        except ClientError as error:
            raise self._translate(error, bucket, key) from error
        return True

    def list_objects(
        self, bucket: str, *, prefix: str = "", limit: int = 1000, token: str | None = None
    ) -> ObjectListing:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": limit}
        if token:
            kwargs["ContinuationToken"] = token
        try:
            response = self._client.list_objects_v2(**kwargs)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in _NO_BUCKET_CODES:
                raise BucketNotFoundError(f"bucket not found: {bucket}") from error
            raise StorageError(f"list failed for {bucket}: {error}") from error
        keys = tuple(item["Key"] for item in response.get("Contents", []))
        return ObjectListing(
            bucket=bucket,
            keys=keys,
            truncated=bool(response.get("IsTruncated")),
            next_token=response.get("NextContinuationToken"),
        )

    def presign_upload(
        self, bucket: str, key: str, *, expires_seconds: int = 900, content_type: str | None = None
    ) -> DirectUploadPolicy:
        params: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        try:
            url = self._client.generate_presigned_url(
                "put_object", Params=params, ExpiresIn=expires_seconds
            )
        except Exception as error:  # noqa: BLE001 — surfaced as a policy failure, as in Java
            return DirectUploadPolicy.failure(f"presign upload failed: {error}")
        headers = {"Content-Type": content_type} if content_type else {}
        return DirectUploadPolicy(
            success=True,
            method="PUT",
            upload_url=url,
            headers=headers,
            bucket=bucket,
            key=key,
            expire_at=datetime.now(timezone.utc) + timedelta(seconds=expires_seconds),
        )

    def presign_download(
        self, bucket: str, key: str, *, expires_seconds: int = 900
    ) -> DirectDownloadPolicy:
        try:
            url = self._client.generate_presigned_url(
                "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_seconds
            )
        except Exception as error:  # noqa: BLE001
            return DirectDownloadPolicy.failure(f"presign download failed: {error}")
        return DirectDownloadPolicy(
            success=True,
            method="GET",
            download_url=url,
            bucket=bucket,
            key=key,
            expire_at=datetime.now(timezone.utc) + timedelta(seconds=expires_seconds),
        )

    @staticmethod
    def _translate(error: ClientError, bucket: str, key: str) -> StorageError:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code == "NoSuchBucket":
            return BucketNotFoundError(f"bucket not found: {bucket}")
        if _is_not_found(error):
            return ObjectNotFoundError(f"object not found: {bucket}/{key}")
        return StorageError(f"S3 error {code} for {bucket}/{key}: {error}")


__all__ = ["S3StorageEngine"]
