"""Redis secret backend integration tests (real Redis on 16379).

中文
----
覆盖 `RedisSecretOperations` / `RedisSecretWriter` 的全部契约。
测试不依赖任何外部 mock,直接连真 Redis。

English
--------
Integration tests covering the full Redis secret backend surface
against a real Redis on `127.0.0.1:16379`. Uses plain pytest
functions so fixtures inject correctly.
"""

from __future__ import annotations

import json

import pytest

from atlas_richie.secret import (
    SecretIntegrityException,
    SecretReference,
    SecretSnapshotChangedEvent,
    SecretVersion,
    SecretVersionSelector,
)
from atlas_richie.secret_redis.operations import _version_key

pytestmark = pytest.mark.integration


def test_put_then_get(redis_session) -> None:
    reference = SecretReference(
        provider=redis_session.descriptor.name,
        path="db.password",
    )
    written = redis_session.writer.put(reference, b"sup3rs3cr3t")
    assert written.plaintext == b"sup3rs3cr3t"
    read = redis_session.operations.get(reference)
    assert read.plaintext == b"sup3rs3cr3t"
    assert read.metadata.backend.value == "redis"


def test_two_writes_get_distinct_versions(redis_session) -> None:
    reference = SecretReference(
        provider=redis_session.descriptor.name,
        path="token",
    )
    first = redis_session.writer.put(reference, b"v1")
    second = redis_session.writer.put(reference, b"v2")
    assert first.metadata.version.number != second.metadata.version.number
    # Latest resolves to the second value
    latest = redis_session.operations.get(reference)
    assert latest.plaintext == b"v2"


def test_pinned_version_returns_old_value(redis_session) -> None:
    reference = SecretReference(
        provider=redis_session.descriptor.name,
        path="k",
    )
    first = redis_session.writer.put(reference, b"old")
    redis_session.writer.put(reference, b"new")
    pinned = reference.with_version(
        SecretVersionSelector.of_static(
            SecretVersion(number=first.metadata.version.number),
        ),
    )
    assert (
        redis_session.operations.get(pinned).plaintext == b"old"
    )


def test_get_version_directly(redis_session) -> None:
    reference = SecretReference(
        provider=redis_session.descriptor.name,
        path="k",
    )
    first = redis_session.writer.put(reference, b"old")
    redis_session.writer.put(reference, b"new")
    direct = redis_session.operations.get_version(
        reference,
        SecretVersion(number=first.metadata.version.number),
    )
    assert direct.plaintext == b"old"


def test_get_metadata_returns_version_and_backend(redis_session) -> None:
    reference = SecretReference(
        provider=redis_session.descriptor.name,
        path="api.key",
    )
    written = redis_session.writer.put(reference, b"k")
    metadata = redis_session.operations.get_metadata(reference)
    assert metadata.version.number == written.metadata.version.number
    assert metadata.backend.value == "redis"
    # The `namespace` tag is the Redis namespace, not the
    # provider name (the provider name is the higher-level
    # `atlas_richie.secret` routing key).
    redis_namespace = redis_session.operations.properties.namespace
    assert metadata.tags["namespace"] == redis_namespace


def test_exists_true_then_false_after_delete(redis_session) -> None:
    reference = SecretReference(
        provider=redis_session.descriptor.name,
        path="ephemeral",
    )
    assert redis_session.operations.exists(reference) is False
    redis_session.writer.put(reference, b"x")
    assert redis_session.operations.exists(reference) is True
    redis_session.deletable.delete(reference)
    assert redis_session.operations.exists(reference) is False


def test_get_missing_raises_integrity(redis_session) -> None:
    reference = SecretReference(
        provider=redis_session.descriptor.name,
        path="never-written",
    )
    with pytest.raises(SecretIntegrityException):
        redis_session.operations.get(reference)


def test_list_with_prefix(redis_session) -> None:
    for path, value in [
        ("app.db.password", b"1"),
        ("app.cache.key", b"2"),
        ("other.token", b"3"),
    ]:
        reference = SecretReference(
            provider=redis_session.descriptor.name,
            path=path,
        )
        redis_session.writer.put(reference, value)
    all_refs = redis_session.operations.list()
    assert len(all_refs) >= 3
    app_refs = redis_session.operations.list("app.")
    assert len(app_refs) == 2
    paths = {ref.path for ref in app_refs}
    assert "app.db.password" in paths
    assert "app.cache.key" in paths


def test_rotate_emits_snapshot_event(redis_session) -> None:
    events: list[SecretSnapshotChangedEvent] = []

    class Listener:
        def on_snapshot_changed(self, event):
            events.append(event)

    redis_session.snapshot_manager.register(Listener())
    reference = SecretReference(
        provider=redis_session.descriptor.name,
        path="token",
    )
    redis_session.writer.put(reference, b"v1")
    redis_session.writer.rotate(reference, b"v2")
    assert len(events) == 1
    assert events[0].previous_metadata.version.number == "v1"
    assert events[0].current_metadata.version.number == "v2"


def test_delete_then_get_raises(redis_session) -> None:
    reference = SecretReference(
        provider=redis_session.descriptor.name,
        path="gone",
    )
    redis_session.writer.put(reference, b"x")
    redis_session.deletable.delete(reference)
    with pytest.raises(SecretIntegrityException):
        redis_session.operations.get(reference)


def test_delete_clears_all_versions(redis_session) -> None:
    reference = SecretReference(
        provider=redis_session.descriptor.name,
        path="multi",
    )
    redis_session.writer.put(reference, b"v1")
    redis_session.writer.put(reference, b"v2")
    redis_session.writer.put(reference, b"v3")
    redis_session.deletable.delete(reference)
    with pytest.raises(SecretIntegrityException):
        redis_session.operations.get(reference)
    with pytest.raises(SecretIntegrityException):
        redis_session.operations.get_version(
            reference,
            SecretVersion(number="v1"),
        )


def test_stored_value_is_encrypted(redis_session) -> None:
    """The raw Redis value must NOT contain the plaintext."""
    reference = SecretReference(
        provider=redis_session.descriptor.name,
        path="plaintext.check",
    )
    plaintext = b"very-secret-data"
    written = redis_session.writer.put(reference, plaintext)
    # The Redis key uses the redis-level namespace, not the
    # provider name. The `_version_key` helper applies the
    # `properties.namespace` we set in the conftest.
    redis_namespace = redis_session.operations.properties.namespace
    version_key = _version_key(
        redis_namespace,
        reference.path,
        written.metadata.version.number,
    )
    raw = redis_session.operations.redis_string_manager.get(version_key, bytes)
    assert raw is not None, "expected envelope to be stored at the computed key"
    assert plaintext not in raw
    envelope = json.loads(raw)
    assert envelope["algorithm"] == "AES-256-GCM"


def test_two_paths_independent(redis_session) -> None:
    ref_a = SecretReference(
        provider=redis_session.descriptor.name,
        path="path.a",
    )
    ref_b = SecretReference(
        provider=redis_session.descriptor.name,
        path="path.b",
    )
    redis_session.writer.put(ref_a, b"AAA")
    redis_session.writer.put(ref_b, b"BBB")
    assert redis_session.operations.get(ref_a).plaintext == b"AAA"
    assert redis_session.operations.get(ref_b).plaintext == b"BBB"
