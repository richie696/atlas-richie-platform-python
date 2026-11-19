"""L1 write-through contract tests.

A write-through region pushes cache mutations back to the source of truth.
Mirrors JSR-107 write-through semantics:

- the cache is updated **first**, then the writer is called;
- a writer exception propagates, but the cache-side change already happened;
- the writer is invoked for removals too (remove / removeAll / clear).
"""

from __future__ import annotations

import pytest

from atlas_richie.cache_core.local import (
    CacheDefinition,
    LocalCacheManager,
    LocalCacheProperties,
)
from atlas_richie.cache_core.local.manage import (
    CallableCacheWriter,
    as_cache_writer,
)

pytestmark = pytest.mark.unit

REGION = "write-through-region"


class _RecordingWriter:
    """Writer that records every write and delete."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, object]] = []
        self.deletes: list[str] = []

    def write(self, key: str, value: object) -> None:
        self.writes.append((key, value))

    def delete(self, key: str) -> None:
        self.deletes.append(key)


def _manager(*, write_through: bool = True) -> LocalCacheManager:
    definition = CacheDefinition(write_through=write_through, statistics_enabled=True)
    return LocalCacheManager(
        properties=LocalCacheProperties(cache_definitions={REGION: definition})
    )


class TestWriteThroughBasics:
    def test_put_pushes_the_value_to_the_writer(self) -> None:
        manager = _manager()
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)

        manager.put(REGION, "k", "v")

        assert writer.writes == [("k", "v")]
        assert manager.get(REGION, "k") == "v"

    def test_put_all_pushes_every_key(self) -> None:
        manager = _manager()
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)

        manager.put_all(REGION, {"a": 1, "b": 2})

        assert writer.writes == [("a", 1), ("b", 2)]

    def test_put_if_absent_pushes_only_on_success(self) -> None:
        manager = _manager()
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)

        assert manager.put_if_absent(REGION, "k", "v") is True
        assert manager.put_if_absent(REGION, "k", "v2") is False

        assert writer.writes == [("k", "v")]

    def test_replace_pushes_the_new_value(self) -> None:
        manager = _manager()
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)
        manager.put(REGION, "k", "v")
        writer.writes.clear()

        assert manager.replace(REGION, "k", "v", "v2") is True
        assert writer.writes == [("k", "v2")]

    def test_failed_replace_does_not_notify(self) -> None:
        manager = _manager()
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)
        manager.put(REGION, "k", "v")
        writer.writes.clear()

        assert manager.replace(REGION, "k", "other", "v2") is False
        assert writer.writes == []

    def test_get_and_put_pushes_the_new_value(self) -> None:
        manager = _manager()
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)

        assert manager.get_and_put(REGION, "k", "v") is None
        assert writer.writes == [("k", "v")]


class TestWriteThroughRemovals:
    def test_remove_pushes_a_delete(self) -> None:
        manager = _manager()
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)
        manager.put(REGION, "k", "v")
        writer.writes.clear()

        assert manager.remove(REGION, "k") is True
        assert writer.deletes == ["k"]

    def test_removing_an_absent_key_does_not_notify(self) -> None:
        manager = _manager()
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)

        assert manager.remove(REGION, "absent") is False
        assert writer.deletes == []

    def test_get_and_remove_pushes_a_delete(self) -> None:
        manager = _manager()
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)
        manager.put(REGION, "k", "v")
        writer.writes.clear()

        assert manager.get_and_remove(REGION, "k") == "v"
        assert writer.deletes == ["k"]

    def test_clear_pushes_a_delete_per_key(self) -> None:
        manager = _manager()
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)
        manager.put_all(REGION, {"a": 1, "b": 2})
        writer.writes.clear()

        assert manager.clear_region(REGION) == 2
        assert sorted(writer.deletes) == ["a", "b"]


class TestWriteThroughOrdering:
    def test_cache_is_updated_before_the_writer_runs(self) -> None:
        manager = _manager()
        observed: list[str] = []

        class _OrderedWriter:
            def write(self, key: str, value: object) -> None:
                observed.append("writer")
                assert manager.get(REGION, key) == value

            def delete(self, key: str) -> None:
                observed.append("delete")

        manager.register_writer(REGION, _OrderedWriter())
        manager.put(REGION, "k", "v")

        assert observed == ["writer"]

    def test_writer_exception_propagates_after_the_cache_changed(self) -> None:
        manager = _manager()

        class _FailingWriter:
            def write(self, key: str, value: object) -> None:
                raise RuntimeError("sink down")

            def delete(self, key: str) -> None:
                raise RuntimeError("sink down")

        manager.register_writer(REGION, _FailingWriter())

        with pytest.raises(RuntimeError, match="sink down"):
            manager.put(REGION, "k", "v")

        assert manager.get(REGION, "k") == "v", "the cache change already happened"


class TestWriteThroughRegistration:
    def test_writer_registered_after_bucket_creation_takes_effect(self) -> None:
        manager = _manager()
        manager.put(REGION, "k", "v")
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)

        manager.put(REGION, "k2", "v2")

        assert writer.writes == [("k2", "v2")]

    def test_callable_pair_is_accepted(self) -> None:
        manager = _manager()
        writes: list[tuple[str, object]] = []
        deletes: list[str] = []
        manager.register_writer(
            REGION, (lambda k, v: writes.append((k, v)), lambda k: deletes.append(k))
        )

        manager.put(REGION, "k", "v")
        manager.remove(REGION, "k")

        assert writes == [("k", "v")]
        assert deletes == ["k"]

    def test_writer_without_delete_is_rejected(self) -> None:
        manager = _manager()

        class _WriteOnly:
            def write(self, key: str, value: object) -> None:
                return None

        with pytest.raises(TypeError):
            manager.register_writer(REGION, _WriteOnly())

    def test_invalid_writer_is_rejected(self) -> None:
        manager = _manager()
        with pytest.raises(TypeError):
            manager.register_writer(REGION, "not-a-writer")

    def test_as_cache_writer_wraps_a_pair(self) -> None:
        writer = as_cache_writer((lambda k, v: None, lambda k: None))
        assert isinstance(writer, CallableCacheWriter)

    def test_as_cache_writer_keeps_a_writer_object(self) -> None:
        writer = _RecordingWriter()
        assert as_cache_writer(writer) is writer


class TestWriteThroughDisabled:
    def test_disabled_region_never_notifies(self) -> None:
        manager = _manager(write_through=False)
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)

        manager.put(REGION, "k", "v")
        manager.remove(REGION, "k")

        assert writer.writes == []
        assert writer.deletes == []

    def test_close_does_not_push_deletes(self) -> None:
        manager = _manager()
        writer = _RecordingWriter()
        manager.register_writer(REGION, writer)
        manager.put(REGION, "k", "v")
        writer.writes.clear()

        manager.close()

        assert writer.deletes == [], "shutdown must not wipe the source of truth"
