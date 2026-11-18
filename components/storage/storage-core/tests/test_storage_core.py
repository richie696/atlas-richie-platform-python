"""Storage core contract tests, offline (in-memory engine)."""

from __future__ import annotations

import io

import pytest

from atlas_richie.storage_core import (
    Acl,
    DirectDownloadPolicy,
    DirectUploadPolicy,
    DownloadResult,
    ObjectListing,
    ObjectNotFoundError,
    ObjectStat,
    ObjectStorageEngine,
    StorageEngineRegistry,
    StorageError,
    UploadResult,
)

pytestmark = pytest.mark.unit


class InMemoryEngine:
    """Minimal engine used to pin the SPI shape and registry behaviour."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, bucket, key, data, *, content_type=None, acl=None, metadata=None):
        payload = data if isinstance(data, bytes) else data.read()
        self.objects[(bucket, key)] = payload
        return UploadResult(bucket=bucket, key=key, size=len(payload))

    def get_object(self, bucket, key):
        if (bucket, key) not in self.objects:
            raise ObjectNotFoundError(f"{bucket}/{key}")
        payload = self.objects[(bucket, key)]
        return DownloadResult(bucket, key, io.BytesIO(payload), ObjectStat(bucket, key, len(payload)))

    def stat_object(self, bucket, key):
        if (bucket, key) not in self.objects:
            raise ObjectNotFoundError(f"{bucket}/{key}")
        return ObjectStat(bucket, key, len(self.objects[(bucket, key)]))

    def delete_object(self, bucket, key):
        return self.objects.pop((bucket, key), None) is not None

    def list_objects(self, bucket, *, prefix="", limit=1000, token=None):
        keys = tuple(sorted(k for b, k in self.objects if b == bucket and k.startswith(prefix)))
        return ObjectListing(bucket, keys[:limit], truncated=len(keys) > limit)

    def presign_upload(self, bucket, key, *, expires_seconds=900, content_type=None):
        return DirectUploadPolicy(success=True, upload_url=f"mem://{bucket}/{key}", bucket=bucket, key=key)

    def presign_download(self, bucket, key, *, expires_seconds=900):
        return DirectDownloadPolicy(success=True, download_url=f"mem://{bucket}/{key}", bucket=bucket, key=key)


class TestAcl:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, Acl.PRIVATE),
            ("private", Acl.PRIVATE),
            ("PUBLIC-READ", Acl.PUBLIC_READ),
            ("public_read", Acl.PUBLIC_READ),
            ("publicread", Acl.PUBLIC_READ),
            ("public-read-write", Acl.PUBLIC_READ_WRITE),
            ("publicreadwrite", Acl.PUBLIC_READ_WRITE),
            ("authenticated-read", Acl.AUTHENTICATED_READ),
            ("authenticatedread", Acl.AUTHENTICATED_READ),
            (Acl.PUBLIC_READ, Acl.PUBLIC_READ),
        ],
    )
    def test_normalization(self, value, expected: Acl) -> None:
        assert Acl.parse(value) is expected

    def test_bucket_owner_full_control_does_not_grant_public(self) -> None:
        assert Acl.parse("bucket-owner-full-control") is Acl.PRIVATE

    def test_unknown_value_raises(self) -> None:
        with pytest.raises(ValueError, match="unsupported ACL"):
            Acl.parse("everyone")


class TestRegistry:
    def test_first_registered_becomes_default(self) -> None:
        registry = StorageEngineRegistry()
        engine = InMemoryEngine()
        registry.register("primary", engine)
        assert registry.default_name == "primary"
        assert registry.get() is engine
        assert registry.get("primary") is engine

    def test_explicit_default_overrides(self) -> None:
        registry = StorageEngineRegistry()
        registry.register("a", InMemoryEngine())
        registry.register("b", InMemoryEngine(), default=True)
        assert registry.default_name == "b"

    def test_duplicate_name_rejected(self) -> None:
        registry = StorageEngineRegistry()
        registry.register("a", InMemoryEngine())
        with pytest.raises(ValueError, match="already registered"):
            registry.register("a", InMemoryEngine())

    def test_blank_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            StorageEngineRegistry().register("  ", InMemoryEngine())

    def test_unknown_name_raises(self) -> None:
        registry = StorageEngineRegistry()
        registry.register("a", InMemoryEngine())
        with pytest.raises(StorageError, match="not registered"):
            registry.get("missing")

    def test_empty_registry_raises(self) -> None:
        with pytest.raises(StorageError, match="no storage engine"):
            StorageEngineRegistry().get()

    def test_names_listing(self) -> None:
        registry = StorageEngineRegistry()
        registry.register("a", InMemoryEngine())
        registry.register("b", InMemoryEngine())
        assert set(registry.names()) == {"a", "b"}


class TestSpiConformance:
    def test_in_memory_engine_satisfies_protocol(self) -> None:
        assert isinstance(InMemoryEngine(), ObjectStorageEngine)

    def test_round_trip_through_the_spi(self) -> None:
        engine: ObjectStorageEngine = InMemoryEngine()
        uploaded = engine.put_object("b", "k", b"payload", content_type="text/plain")
        assert uploaded.size == 7
        downloaded = engine.get_object("b", "k")
        assert downloaded.stream.read() == b"payload"
        assert engine.stat_object("b", "k").size == 7
        assert engine.list_objects("b").keys == ("k",)
        assert engine.delete_object("b", "k") is True
        assert engine.delete_object("b", "k") is False
        with pytest.raises(ObjectNotFoundError):
            engine.get_object("b", "k")

    def test_stream_input_accepted(self) -> None:
        engine = InMemoryEngine()
        engine.put_object("b", "k", io.BytesIO(b"streamed"))
        assert engine.get_object("b", "k").stream.read() == b"streamed"

    def test_prefix_listing(self) -> None:
        engine = InMemoryEngine()
        for key in ("a/1", "a/2", "b/1"):
            engine.put_object("b", key, b"x")
        assert engine.list_objects("b", prefix="a/").keys == ("a/1", "a/2")

    def test_pagination_flag(self) -> None:
        engine = InMemoryEngine()
        for index in range(5):
            engine.put_object("b", f"k{index}", b"x")
        listing = engine.list_objects("b", limit=2)
        assert len(listing.keys) == 2
        assert listing.truncated is True


class TestPolicyValueObjects:
    def test_upload_failure_shape(self) -> None:
        policy = DirectUploadPolicy.failure("no credentials")
        assert policy.success is False
        assert policy.error_message == "no credentials"
        assert policy.upload_url is None
        assert policy.fallback is False

    def test_download_failure_shape(self) -> None:
        policy = DirectDownloadPolicy.failure("denied")
        assert policy.success is False
        assert policy.download_url is None

    def test_defaults(self) -> None:
        assert DirectUploadPolicy(success=True).method == "PUT"
        assert DirectDownloadPolicy(success=True).method == "GET"
        assert DirectUploadPolicy(success=True).headers == {}

    def test_fallback_flag_is_expressible(self) -> None:
        policy = DirectUploadPolicy(success=True, fallback=True, upload_url="/proxy/upload")
        assert policy.fallback is True
