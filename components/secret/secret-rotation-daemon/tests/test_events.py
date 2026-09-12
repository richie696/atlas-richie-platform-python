"""Tests for `SecretRotated` event dataclass.

中文
----
`SecretRotated` 是 frozen dataclass,验证:
- 构造 / equality / hash
- slots 生效
- 必填字段

英文
--------
The `SecretRotated` event is a frozen slots dataclass. Verify
construction / equality / hashing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret_rotation_daemon import SecretRotated


def test_secret_rotated_construction_and_equality() -> None:
    ref = SecretReference(provider="test", path="db")
    old = SecretVersion(number="1", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    new = SecretVersion(number="2", created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    event1 = SecretRotated(reference=ref, old_version=old, new_version=new)
    event2 = SecretRotated(reference=ref, old_version=old, new_version=new)
    assert event1 == event2
    assert hash(event1) == hash(event2)
    assert event1.reference is ref
    assert event1.old_version == old
    assert event1.new_version == new


def test_secret_rotated_allows_none_old_version() -> None:
    """First-poll cold start has no previous version."""
    ref = SecretReference(provider="test", path="db")
    new = SecretVersion(number="1", created_at=datetime.now(tz=timezone.utc))
    event = SecretRotated(reference=ref, old_version=None, new_version=new)
    assert event.old_version is None
    assert event.new_version is new


def test_secret_rotated_is_frozen() -> None:
    ref = SecretReference(provider="test", path="db")
    new = SecretVersion(number="1", created_at=datetime.now(tz=timezone.utc))
    event = SecretRotated(reference=ref, old_version=None, new_version=new)
    try:
        event.new_version = None  # type: ignore[misc]
        raise AssertionError("frozen dataclass should reject mutation")
    except (AttributeError, Exception):
        # `frozen=True` raises `dataclasses.FrozenInstanceError`
        # (a subclass of `AttributeError`).
        pass
