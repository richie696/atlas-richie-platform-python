"""本地文件系统存储引擎：协议一致性、路径安全、原子性与列举分页。"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from atlas_richie.storage_core import (
    Acl,
    BucketNotFoundError,
    ObjectNotFoundError,
    ObjectStorageEngine,
    StorageError,
)
from atlas_richie.storage_local import LocalStorageEngine

pytestmark = pytest.mark.unit


@pytest.fixture
def engine(tmp_path: Path) -> LocalStorageEngine:
    store = LocalStorageEngine(tmp_path / "objects")
    store.create_bucket("uploads")
    return store


class TestProtocol:
    def test_satisfies_storage_engine_protocol(self, engine) -> None:
        assert isinstance(engine, ObjectStorageEngine)

    def test_round_trip(self, engine) -> None:
        result = engine.put_object("uploads", "a.txt", b"hello")
        assert result.size == 5
        assert result.etag and len(result.etag) == 64
        with engine.get_object("uploads", "a.txt").stream as fh:
            assert fh.read() == b"hello"

    def test_stream_input(self, engine) -> None:
        engine.put_object("uploads", "s.bin", io.BytesIO(b"streamed"))
        with engine.get_object("uploads", "s.bin").stream as fh:
            assert fh.read() == b"streamed"

    def test_stat_reports_size_and_metadata(self, engine) -> None:
        engine.put_object(
            "uploads", "m.txt", b"abc", content_type="text/plain",
            metadata={"owner": "richie"}, acl="public-read",
        )
        stat = engine.stat_object("uploads", "m.txt")
        assert stat.size == 3
        assert stat.content_type == "text/plain"
        assert stat.metadata == {"owner": "richie"}
        assert stat.last_modified is not None
        assert stat.etag

    def test_overwrite_replaces_content(self, engine) -> None:
        engine.put_object("uploads", "o.txt", b"first")
        engine.put_object("uploads", "o.txt", b"second-longer")
        with engine.get_object("uploads", "o.txt").stream as fh:
            assert fh.read() == b"second-longer"
        assert engine.stat_object("uploads", "o.txt").size == 13

    def test_delete_reports_prior_existence(self, engine) -> None:
        engine.put_object("uploads", "d.txt", b"x")
        assert engine.delete_object("uploads", "d.txt") is True
        assert engine.delete_object("uploads", "d.txt") is False

    def test_delete_also_removes_sidecar(self, engine, tmp_path) -> None:
        engine.put_object("uploads", "d.txt", b"x")
        engine.delete_object("uploads", "d.txt")
        assert not list((tmp_path / "objects" / "uploads").glob("*.atlas-meta.json"))

    def test_missing_object_raises(self, engine) -> None:
        with pytest.raises(ObjectNotFoundError):
            engine.get_object("uploads", "nope")
        with pytest.raises(ObjectNotFoundError):
            engine.stat_object("uploads", "nope")

    def test_missing_bucket_raises(self, engine) -> None:
        with pytest.raises(BucketNotFoundError):
            engine.list_objects("absent")

    def test_nested_keys_create_directories(self, engine) -> None:
        engine.put_object("uploads", "a/b/c.txt", b"deep")
        with engine.get_object("uploads", "a/b/c.txt").stream as fh:
            assert fh.read() == b"deep"


class TestPathSafety:
    @pytest.mark.parametrize(
        "key",
        ["../escape", "a/../../escape", "..", "/absolute", "\\windows", "c:drive", "a:b"],
    )
    def test_unsafe_keys_rejected(self, engine, key) -> None:
        with pytest.raises(StorageError):
            engine.put_object("uploads", key, b"x")

    def test_traversal_does_not_write_outside_root(self, engine, tmp_path) -> None:
        with pytest.raises(StorageError):
            engine.put_object("uploads", "../outside.txt", b"x")
        assert not (tmp_path / "objects" / "outside.txt").exists()
        assert not (tmp_path / "outside.txt").exists()

    def test_symlink_escape_is_blocked(self, engine, tmp_path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_bytes(b"secret")
        bucket = tmp_path / "objects" / "uploads"
        os.symlink(outside, bucket / "link")
        with pytest.raises(StorageError):
            engine.get_object("uploads", "link/secret.txt")

    @pytest.mark.parametrize("bucket", ["", "..", ".", "a/b", "a\\b"])
    def test_unsafe_bucket_rejected(self, engine, bucket) -> None:
        with pytest.raises(StorageError):
            engine.put_object(bucket, "k", b"x")

    def test_empty_key_rejected(self, engine) -> None:
        with pytest.raises(StorageError):
            engine.put_object("uploads", "", b"x")


class TestSizeLimit:
    def test_oversize_bytes_rejected_and_cleaned(self, engine, tmp_path) -> None:
        store = LocalStorageEngine(tmp_path / "small", max_size=4)
        store.create_bucket("b")
        with pytest.raises(StorageError, match="max_size"):
            store.put_object("b", "big", b"12345")
        assert list((tmp_path / "small" / "b").iterdir()) == []

    def test_oversize_stream_rejected_and_cleaned(self, engine, tmp_path) -> None:
        store = LocalStorageEngine(tmp_path / "small2", max_size=4)
        store.create_bucket("b")
        with pytest.raises(StorageError, match="max_size"):
            store.put_object("b", "big", io.BytesIO(b"12345"))
        assert list((tmp_path / "small2" / "b").iterdir()) == []

    def test_exact_limit_allowed(self, tmp_path) -> None:
        store = LocalStorageEngine(tmp_path / "exact", max_size=4)
        store.create_bucket("b")
        assert store.put_object("b", "ok", b"1234").size == 4

    @pytest.mark.parametrize("size", [0, -1])
    def test_invalid_max_size_rejected(self, tmp_path, size) -> None:
        with pytest.raises(ValueError):
            LocalStorageEngine(tmp_path / "x", max_size=size)


class TestListing:
    def test_prefix_filter_and_sort(self, engine) -> None:
        for key in ["b/2", "a/2", "a/1", "c/1"]:
            engine.put_object("uploads", key, b"x")
        listing = engine.list_objects("uploads", prefix="a/")
        assert listing.keys == ("a/1", "a/2")
        assert listing.truncated is False

    def test_sidecar_and_temp_files_are_not_listed(self, engine) -> None:
        engine.put_object("uploads", "real.txt", b"x")
        listing = engine.list_objects("uploads")
        assert listing.keys == ("real.txt",)

    def test_pagination(self, engine) -> None:
        for index in range(5):
            engine.put_object("uploads", f"k{index}", b"x")
        first = engine.list_objects("uploads", limit=2)
        assert first.keys == ("k0", "k1")
        assert first.truncated is True
        assert first.next_token == "k1"
        second = engine.list_objects("uploads", limit=2, token=first.next_token)
        assert second.keys == ("k2", "k3")
        third = engine.list_objects("uploads", limit=2, token=second.next_token)
        assert third.keys == ("k4",)
        assert third.truncated is False

    def test_empty_bucket(self, engine) -> None:
        listing = engine.list_objects("uploads")
        assert listing.keys == ()
        assert listing.truncated is False

    def test_invalid_limit_rejected(self, engine) -> None:
        with pytest.raises(ValueError):
            engine.list_objects("uploads", limit=0)


class TestPresign:
    def test_upload_presign_fails_honestly(self, engine) -> None:
        policy = engine.presign_upload("uploads", "k")
        assert policy.success is False
        assert policy.upload_url is None
        assert "presigned" in policy.error_message

    def test_download_presign_fails_honestly(self, engine) -> None:
        policy = engine.presign_download("uploads", "k")
        assert policy.success is False
        assert policy.download_url is None


class TestBucketLifecycle:
    def test_create_and_delete_bucket(self, tmp_path) -> None:
        store = LocalStorageEngine(tmp_path / "root")
        store.create_bucket("b")
        store.put_object("b", "k", b"x")
        assert store.delete_bucket("b") is True
        with pytest.raises(BucketNotFoundError):
            store.list_objects("b")

    def test_acl_is_recorded(self, engine, tmp_path) -> None:
        engine.put_object("uploads", "p.txt", b"x", acl=Acl.PUBLIC_READ)
        meta = json.loads(
            (tmp_path / "objects" / "uploads" / "p.txt.atlas-meta.json").read_text()
        )
        assert meta["acl"] == Acl.PUBLIC_READ.value

    def test_context_manager(self, tmp_path) -> None:
        with LocalStorageEngine(tmp_path / "cm") as store:
            store.create_bucket("b")
            store.put_object("b", "k", b"x")
        assert (tmp_path / "cm" / "b" / "k").read_bytes() == b"x"