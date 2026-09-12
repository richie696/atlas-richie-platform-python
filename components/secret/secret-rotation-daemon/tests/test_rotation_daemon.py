"""Tests for `SecretRotationDaemon` using a mock `SecretOperations`.

中文
----
用 `MagicMock` 模拟 `SecretOperations`,精确控制
`get_metadata` 的返回值,验证:

- 注册 callback → 第一次 poll 触发 callback(因为没 last-seen version)
- 第二次 poll 同 version → 不触发
- 改 version → 再触发
- 多个 reference + callback 互相独立
- 单条 reference 失败不影响其它
- start/stop 生命周期
- close 拒绝后续 register

英文
--------
MagicMock-backed tests for the rotation daemon. Cover the
happy path (first poll, version change), idempotency (same
version), per-reference error isolation, lifecycle
(start/stop/close), and the callback's `SecretRotated` event shape.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from atlas_richie.secret import SecretException
from atlas_richie.secret.metadata import SecretBackend, SecretMetadata
from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret_rotation_daemon import (
    SecretRotated,
    SecretRotationDaemon,
)


def _make_metadata(version_number: str) -> SecretMetadata:
    """Build a `SecretMetadata` with a specific version number."""
    return SecretMetadata(
        reference=SecretReference(provider="test", path="anything"),
        version=SecretVersion(
            number=version_number,
            created_at=datetime.now(tz=timezone.utc),
        ),
        backend=SecretBackend.IN_MEMORY,
        created_at=datetime.now(tz=timezone.utc),
        expires_at=None,
        tags={},
    )


def test_first_poll_fires_callback() -> None:
    ops = MagicMock()
    ops.get_metadata.return_value = _make_metadata("1")
    ref = SecretReference(provider="test", path="db")
    events: list[SecretRotated] = []
    daemon = SecretRotationDaemon(ops, poll_interval_seconds=0.01)
    daemon.register(ref, lambda e: events.append(e))
    daemon.poll_once()
    assert len(events) == 1
    assert events[0].reference is ref
    assert events[0].old_version is None
    assert events[0].new_version.number == "1"


def test_second_poll_with_same_version_is_idempotent() -> None:
    ops = MagicMock()
    ops.get_metadata.return_value = _make_metadata("1")
    ref = SecretReference(provider="test", path="db")
    events: list[SecretRotated] = []
    daemon = SecretRotationDaemon(ops)
    daemon.register(ref, lambda e: events.append(e))
    daemon.poll_once()
    daemon.poll_once()
    daemon.poll_once()
    assert len(events) == 1  # only the first poll fired


def test_version_change_fires_callback() -> None:
    ops = MagicMock()
    ops.get_metadata.side_effect = [
        _make_metadata("1"),
        _make_metadata("1"),  # no change
        _make_metadata("2"),  # change!
    ]
    ref = SecretReference(provider="test", path="db")
    events: list[SecretRotated] = []
    daemon = SecretRotationDaemon(ops)
    daemon.register(ref, lambda e: events.append(e))
    daemon.poll_once()
    daemon.poll_once()
    daemon.poll_once()
    assert len(events) == 2
    assert events[1].old_version.number == "1"
    assert events[1].new_version.number == "2"


def test_multiple_references_independent() -> None:
    ops = MagicMock()
    ref_a = SecretReference(provider="test", path="a")
    ref_b = SecretReference(provider="test", path="b")
    # Each `get_metadata` call dispatches by path.
    def _by_path(ref: SecretReference) -> SecretMetadata:
        return _make_metadata(ref.path)
    ops.get_metadata.side_effect = _by_path

    events_a: list[SecretRotated] = []
    events_b: list[SecretRotated] = []
    daemon = SecretRotationDaemon(ops)
    daemon.register(ref_a, lambda e: events_a.append(e))
    daemon.register(ref_b, lambda e: events_b.append(e))
    daemon.poll_once()
    assert len(events_a) == 1
    assert len(events_b) == 1
    assert events_a[0].new_version.number == "a"
    assert events_b[0].new_version.number == "b"


def test_get_metadata_failure_does_not_kill_other_references() -> None:
    ops = MagicMock()
    ref_good = SecretReference(provider="test", path="good")
    ref_bad = SecretReference(provider="test", path="bad")

    def _maybe_fail(ref: SecretReference) -> SecretMetadata:
        if ref.path == "bad":
            raise SecretException("simulated failure")
        return _make_metadata("1")

    ops.get_metadata.side_effect = _maybe_fail

    events: list[SecretRotated] = []
    daemon = SecretRotationDaemon(ops)
    daemon.register(ref_good, lambda e: events.append(e))
    daemon.register(ref_bad, lambda e: events.append(e))
    daemon.poll_once()
    # Only the good reference's callback fires; the bad one's
    # failure is logged and ignored.
    assert len(events) == 1
    assert events[0].reference is ref_good


def test_callback_exception_does_not_kill_daemon() -> None:
    ops = MagicMock()
    ops.get_metadata.side_effect = [
        _make_metadata("1"),
        _make_metadata("2"),
    ]
    ref = SecretReference(provider="test", path="db")
    good_events: list[SecretRotated] = []

    def bad_callback(_event: SecretRotated) -> None:
        raise RuntimeError("consumer-side bug")

    daemon = SecretRotationDaemon(ops)
    daemon.register(ref, bad_callback)
    # First poll: bad callback raises; daemon must survive.
    daemon.poll_once()
    # Replace callback with a good one and re-register.
    daemon.unregister(ref)
    daemon.register(ref, lambda e: good_events.append(e))
    daemon.poll_once()  # first poll: version "2" differs from last-seen
    assert len(good_events) == 1
    assert good_events[0].new_version.number == "2"


def test_unregister_stops_firing() -> None:
    ops = MagicMock()
    ops.get_metadata.return_value = _make_metadata("1")
    ref = SecretReference(provider="test", path="db")
    events: list[SecretRotated] = []
    daemon = SecretRotationDaemon(ops)
    daemon.register(ref, lambda e: events.append(e))
    daemon.poll_once()
    daemon.unregister(ref)
    daemon.poll_once()  # no longer watching
    assert len(events) == 1


def test_lifecycle_start_stop_is_idempotent() -> None:
    ops = MagicMock()
    ops.get_metadata.return_value = _make_metadata("1")
    ref = SecretReference(provider="test", path="db")
    events: list[SecretRotated] = []
    daemon = SecretRotationDaemon(ops, poll_interval_seconds=0.01)
    daemon.register(ref, lambda e: events.append(e))
    daemon.start()
    daemon.start()  # idempotent
    # Give the thread a moment to do at least one poll.
    import time as _t
    _t.sleep(0.05)
    daemon.stop()
    daemon.stop()  # idempotent
    assert daemon.is_running is False
    # At least one event should have fired during the 0.05s window.
    assert len(events) >= 1


def test_register_rejects_non_callable() -> None:
    ops = MagicMock()
    daemon = SecretRotationDaemon(ops)
    ref = SecretReference(provider="test", path="db")
    with pytest.raises(TypeError):
        daemon.register(ref, "not-callable")  # type: ignore[arg-type]


def test_poll_interval_must_be_positive() -> None:
    ops = MagicMock()
    with pytest.raises(ValueError):
        SecretRotationDaemon(ops, poll_interval_seconds=0)
    with pytest.raises(ValueError):
        SecretRotationDaemon(ops, poll_interval_seconds=-1)


def test_close_blocks_further_registers() -> None:
    ops = MagicMock()
    daemon = SecretRotationDaemon(ops)
    daemon.close()
    ref = SecretReference(provider="test", path="db")
    with pytest.raises(SecretException):
        daemon.register(ref, lambda e: None)


def test_registered_count() -> None:
    ops = MagicMock()
    daemon = SecretRotationDaemon(ops)
    assert daemon.registered_count == 0
    ref1 = SecretReference(provider="test", path="a")
    ref2 = SecretReference(provider="test", path="b")
    daemon.register(ref1, lambda e: None)
    daemon.register(ref2, lambda e: None)
    assert daemon.registered_count == 2
    daemon.unregister(ref1)
    assert daemon.registered_count == 1
