"""键归一化、公开 URL 构造、ACL 直读策略与注册表热替换。"""

from __future__ import annotations

import pytest

from atlas_richie.storage_core import (
    Acl,
    DirectDownloadPolicy,
    StorageEngineRegistry,
    StorageError,
    build_public_object_url,
    real_path,
    resolve_download_policy,
)

pytestmark = pytest.mark.unit


class TestRealPath:
    @pytest.mark.parametrize(
        ("base", "key", "expected"),
        [
            ("uploads", "a.txt", "uploads/a.txt"),
            ("uploads/", "a.txt", "uploads/a.txt"),
            ("/uploads/", "/a.txt", "uploads/a.txt"),
            ("uploads", "uploads/a.txt", "uploads/a.txt"),
            ("uploads", "/uploads/a.txt", "uploads/a.txt"),
            ("uploads/", "uploads/a.txt", "uploads/a.txt"),
            ("", "a.txt", "a.txt"),
            (None, "a.txt", "a.txt"),
            ("  ", "a.txt", "a.txt"),
            ("uploads", "uploads", "uploads"),
            ("a/b", "c.txt", "a/b/c.txt"),
            ("a/b", "a/b/c.txt", "a/b/c.txt"),
        ],
    )
    def test_join(self, base, key, expected) -> None:
        assert real_path(base, key) == expected

    def test_idempotent(self) -> None:
        once = real_path("uploads", "a.txt")
        assert real_path("uploads", once) == once, "直传回传的真实 key 再拼接不得重复前缀"

    def test_prefix_lookalike_is_not_treated_as_prefixed(self) -> None:
        assert real_path("up", "uploads/a.txt") == "up/uploads/a.txt"


class TestPublicUrl:
    def test_virtual_host_style(self) -> None:
        assert (
            build_public_object_url("https://oss.example.com", "bkt", "a.txt")
            == "https://bkt.oss.example.com/a.txt"
        )

    def test_scheme_added_when_missing(self) -> None:
        assert (
            build_public_object_url("oss.example.com", "bkt", "a.txt")
            == "https://bkt.oss.example.com/a.txt"
        )

    def test_path_style_when_endpoint_addresses_bucket(self) -> None:
        assert (
            build_public_object_url("https://bkt.oss.example.com", "bkt", "a.txt")
            == "https://bkt.oss.example.com/a.txt"
        )

    def test_trailing_slashes_stripped(self) -> None:
        assert (
            build_public_object_url("https://oss.example.com///", "bkt", "a.txt")
            == "https://bkt.oss.example.com/a.txt"
        )

    def test_blank_endpoint_returns_key(self) -> None:
        assert build_public_object_url("", "bkt", "a.txt") == "a.txt"
        assert build_public_object_url(None, "bkt", "a.txt") == "a.txt"

    def test_http_scheme_preserved_for_path_style(self) -> None:
        assert (
            build_public_object_url("http://bkt.oss.example.com", "bkt", "a.txt")
            == "http://bkt.oss.example.com/a.txt"
        )


class _FakeEngine:
    def __init__(self) -> None:
        self.presign_calls: list[tuple] = []

    def presign_download(self, bucket, key, *, expires_seconds=900):
        self.presign_calls.append((bucket, key, expires_seconds))
        return DirectDownloadPolicy(
            success=True, download_url=f"https://signed/{key}", bucket=bucket, key=key
        )


class TestResolveDownloadPolicy:
    def test_public_read_uses_stable_url_without_presign(self) -> None:
        engine = _FakeEngine()
        policy = resolve_download_policy(
            engine, "bkt", "a.txt", acl=Acl.PUBLIC_READ, endpoint="https://oss.example.com"
        )
        assert policy.success is True
        assert policy.download_url == "https://bkt.oss.example.com/a.txt"
        assert policy.fallback is False
        assert engine.presign_calls == [], "公开 ACL 不得走 presign"

    def test_public_read_write_also_public(self) -> None:
        engine = _FakeEngine()
        policy = resolve_download_policy(
            engine, "bkt", "a.txt", acl="public-read-write", endpoint="https://oss.example.com"
        )
        assert policy.success is True
        assert engine.presign_calls == []

    def test_private_acl_presigns(self) -> None:
        engine = _FakeEngine()
        policy = resolve_download_policy(engine, "bkt", "a.txt", acl=Acl.PRIVATE)
        assert policy.success is True
        assert policy.download_url == "https://signed/a.txt"
        assert engine.presign_calls == [("bkt", "a.txt", 900)]

    def test_default_acl_is_private(self) -> None:
        engine = _FakeEngine()
        resolve_download_policy(engine, "bkt", "a.txt")
        assert engine.presign_calls, "未指定 ACL 默认私有，必须 presign"

    def test_base_path_applied_to_real_key(self) -> None:
        engine = _FakeEngine()
        policy = resolve_download_policy(
            engine, "bkt", "a.txt", acl=Acl.PUBLIC_READ,
            endpoint="https://oss.example.com", base_path="uploads",
        )
        assert policy.key == "uploads/a.txt"
        assert policy.download_url.endswith("/uploads/a.txt")

    def test_expire_floor_is_sixty_seconds(self) -> None:
        engine = _FakeEngine()
        resolve_download_policy(engine, "bkt", "a.txt", expires_seconds=5)
        assert engine.presign_calls[0][2] == 60

    def test_blank_key_fails(self) -> None:
        policy = resolve_download_policy(_FakeEngine(), "bkt", "  ")
        assert policy.success is False
        assert "对象键" in policy.error_message

    def test_public_policy_has_expiry(self) -> None:
        policy = resolve_download_policy(
            _FakeEngine(), "bkt", "a.txt", acl=Acl.PUBLIC_READ, endpoint="https://e.com"
        )
        assert policy.expire_at is not None


class TestRegistryHotSwap:
    def test_replace_swaps_and_returns_previous(self) -> None:
        registry = StorageEngineRegistry()
        first, second = _FakeEngine(), _FakeEngine()
        registry.register("primary", first)
        previous = registry.replace("primary", second)
        assert previous is first
        assert registry.get("primary") is second

    def test_replace_preserves_default(self) -> None:
        registry = StorageEngineRegistry()
        registry.register("a", _FakeEngine(), default=True)
        registry.register("b", _FakeEngine())
        registry.replace("a", _FakeEngine())
        assert registry.default_name == "a"

    def test_replace_unknown_raises(self) -> None:
        with pytest.raises(StorageError):
            StorageEngineRegistry().replace("absent", _FakeEngine())

    def test_unregister_returns_removed(self) -> None:
        registry = StorageEngineRegistry()
        engine = _FakeEngine()
        registry.register("a", engine)
        assert registry.unregister("a") is engine
        assert registry.names() == ()

    def test_unregister_default_falls_back_to_first_remaining(self) -> None:
        registry = StorageEngineRegistry()
        registry.register("a", _FakeEngine(), default=True)
        registry.register("b", _FakeEngine())
        registry.unregister("a")
        assert registry.default_name == "b"
        assert registry.get() is not None

    def test_unregister_last_default_becomes_none(self) -> None:
        registry = StorageEngineRegistry()
        registry.register("a", _FakeEngine())
        registry.unregister("a")
        assert registry.default_name is None
        with pytest.raises(StorageError):
            registry.get()

    def test_unregister_absent_is_none(self) -> None:
        assert StorageEngineRegistry().unregister("absent") is None

    def test_register_duplicate_still_rejected(self) -> None:
        registry = StorageEngineRegistry()
        registry.register("a", _FakeEngine())
        with pytest.raises(ValueError):
            registry.register("a", _FakeEngine())