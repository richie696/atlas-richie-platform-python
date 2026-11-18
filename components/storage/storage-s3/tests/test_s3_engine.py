"""S3 adapter tests against a real S3-compatible endpoint.

Each test uses a uniquely named bucket created and removed around it, so runs
never interfere with each other or with any pre-existing data.
"""

from __future__ import annotations

import urllib.request
import uuid

import pytest

from atlas_richie.storage_core import (
    BucketNotFoundError,
    ObjectNotFoundError,
    ObjectStorageEngine,
    StorageError,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def bucket(engine):
    name = f"it-storage-{uuid.uuid4().hex[:12]}"
    engine.client.create_bucket(Bucket=name)
    try:
        yield name
    finally:
        listed = engine.client.list_objects_v2(Bucket=name)
        for item in listed.get("Contents", []):
            engine.client.delete_object(Bucket=name, Key=item["Key"])
        engine.client.delete_bucket(Bucket=name)


class TestProtocol:
    def test_engine_satisfies_spi(self, engine) -> None:
        assert isinstance(engine, ObjectStorageEngine)


class TestObjectLifecycle:
    def test_put_get_round_trip(self, engine, bucket) -> None:
        uploaded = engine.put_object(bucket, "a.txt", b"hello", content_type="text/plain")
        assert uploaded.bucket == bucket
        assert uploaded.key == "a.txt"
        assert uploaded.size == 5
        assert uploaded.etag

        downloaded = engine.get_object(bucket, "a.txt")
        assert downloaded.stream.read() == b"hello"
        assert downloaded.stat.content_type == "text/plain"
        assert downloaded.stat.size == 5

    def test_stat_matches_put(self, engine, bucket) -> None:
        engine.put_object(bucket, "k", b"12345", metadata={"owner": "alice"})
        stat = engine.stat_object(bucket, "k")
        assert stat.size == 5
        assert stat.metadata.get("owner") == "alice"
        assert stat.last_modified is not None

    def test_overwrite_replaces_content(self, engine, bucket) -> None:
        engine.put_object(bucket, "k", b"first")
        engine.put_object(bucket, "k", b"second")
        assert engine.get_object(bucket, "k").stream.read() == b"second"

    def test_delete_reports_prior_existence(self, engine, bucket) -> None:
        engine.put_object(bucket, "k", b"x")
        assert engine.delete_object(bucket, "k") is True
        assert engine.delete_object(bucket, "k") is False

    def test_missing_object_raises_translated_error(self, engine, bucket) -> None:
        with pytest.raises(ObjectNotFoundError):
            engine.get_object(bucket, "absent")
        with pytest.raises(ObjectNotFoundError):
            engine.stat_object(bucket, "absent")

    def test_missing_bucket_raises_translated_error(self, engine) -> None:
        with pytest.raises(BucketNotFoundError):
            engine.list_objects(f"no-such-bucket-{uuid.uuid4().hex[:8]}")

    def test_binary_payload_integrity(self, engine, bucket) -> None:
        payload = bytes(range(256)) * 4
        engine.put_object(bucket, "bin", payload)
        assert engine.get_object(bucket, "bin").stream.read() == payload

    def test_stream_input(self, engine, bucket) -> None:
        import io

        engine.put_object(bucket, "s", io.BytesIO(b"streamed"))
        assert engine.get_object(bucket, "s").stream.read() == b"streamed"


class TestListing:
    def test_prefix_and_keys(self, engine, bucket) -> None:
        for key in ("a/1", "a/2", "b/1"):
            engine.put_object(bucket, key, b"x")
        listing = engine.list_objects(bucket, prefix="a/")
        assert listing.keys == ("a/1", "a/2")
        assert listing.truncated is False

    def test_pagination_with_continuation_token(self, engine, bucket) -> None:
        for index in range(5):
            engine.put_object(bucket, f"k{index}", b"x")
        first = engine.list_objects(bucket, limit=2)
        assert len(first.keys) == 2
        assert first.truncated is True
        assert first.next_token
        second = engine.list_objects(bucket, limit=2, token=first.next_token)
        assert len(second.keys) == 2
        assert not set(first.keys) & set(second.keys)

    def test_empty_bucket(self, engine, bucket) -> None:
        listing = engine.list_objects(bucket)
        assert listing.keys == ()
        assert listing.truncated is False


class TestPresign:
    def test_presigned_upload_actually_works(self, engine, bucket) -> None:
        policy = engine.presign_upload(bucket, "up.txt", expires_seconds=300, content_type="text/plain")
        assert policy.success is True
        assert policy.method == "PUT"
        assert policy.upload_url
        assert policy.expire_at is not None

        request = urllib.request.Request(
            policy.upload_url, data=b"presigned-body", method="PUT",
            headers={"Content-Type": "text/plain"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - test endpoint
            assert response.status in (200, 201)
        assert engine.get_object(bucket, "up.txt").stream.read() == b"presigned-body"

    def test_presigned_download_actually_works(self, engine, bucket) -> None:
        engine.put_object(bucket, "down.txt", b"download-me")
        policy = engine.presign_download(bucket, "down.txt", expires_seconds=300)
        assert policy.success is True
        assert policy.method == "GET"
        with urllib.request.urlopen(policy.download_url, timeout=15) as response:  # noqa: S310
            assert response.read() == b"download-me"

    def test_presign_failure_is_a_policy_not_a_raise(self, engine) -> None:
        class _Broken:
            def generate_presigned_url(self, *args, **kwargs):
                raise RuntimeError("signer unavailable")

        from atlas_richie.storage_s3 import S3StorageEngine

        broken = S3StorageEngine(client=_Broken())
        upload = broken.presign_upload("b", "k")
        download = broken.presign_download("b", "k")
        assert upload.success is False and upload.error_message
        assert download.success is False and download.error_message


class TestErrorTranslation:
    def test_unknown_error_becomes_storage_error(self, engine, bucket) -> None:
        from botocore.exceptions import ClientError

        class _Broken:
            def head_object(self, **kwargs):
                raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "HeadObject")

            def delete_object(self, **kwargs):
                raise AssertionError("should not be reached")

        from atlas_richie.storage_s3 import S3StorageEngine

        broken = S3StorageEngine(client=_Broken())
        with pytest.raises(StorageError, match="AccessDenied"):
            broken.delete_object(bucket, "k")
