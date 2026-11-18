"""投影持久化：状态机、manifest 账本、清理 outbox 与 resolver 读路径。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine

from atlas_richie.vector_core import (
    ActiveProjectionVersionResolver,
    VectorProjectionReference,
    VectorProjectionSpecification,
    VectorProjectionState,
)
from atlas_richie.vector_persistence_sqlalchemy import (
    CLEANUP_EVENT,
    OUTBOX_PENDING,
    OUTBOX_PROCESSED,
    ProjectionStateError,
    ProjectionVersionNotFoundError,
    VectorProjectionError,
    VectorProjectionProperties,
    VectorProjectionStore,
)


class FakeDeleter:
    """记录向量删除调用。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.fail = False

    def delete_by_ids(self, index_name: str, ids) -> int:
        if self.fail:
            raise RuntimeError("vector store unreachable")
        self.calls.append((index_name, list(ids)))
        return len(ids)


@pytest.fixture
def engine():
    return create_engine("sqlite://")


@pytest.fixture
def deleter():
    return FakeDeleter()


@pytest.fixture
def store(engine, deleter):
    return VectorProjectionStore(engine, deleter=deleter)


def _reference(document_ref: str = "doc-1") -> VectorProjectionReference:
    return VectorProjectionReference(
        tenant_id=1, knowledge_base_id="kb-1", document_ref=document_ref
    )


def _specification(source_version: str = "v1") -> VectorProjectionSpecification:
    return VectorProjectionSpecification(
        source_version=source_version,
        index_name="kb-1-index",
        embedding_space_id="space-a",
    )


def _activate(store: VectorProjectionStore, version_id: str, delay=None) -> None:
    store.mark_writing(version_id)
    store.mark_ready_if_no_failure(version_id)
    store.activate(version_id, delay)


class TestBeginRebuild:
    def test_creates_projection_and_preparing_version(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        assert version.state is VectorProjectionState.PREPARING
        assert version.written_records == 0
        assert version.failed_records == 0
        persisted = store.find_version(version.version_id)
        assert persisted is not None
        assert persisted.projection_id == version.projection_id
        assert persisted.specification.index_name == "kb-1-index"

    def test_reuses_projection_row_for_same_reference(self, store) -> None:
        first = store.begin_rebuild(_reference(), _specification())
        second = store.begin_rebuild(_reference(), _specification("v2"))
        assert first.projection_id == second.projection_id
        assert first.version_id != second.version_id

    def test_distinct_documents_get_distinct_projections(self, store) -> None:
        first = store.begin_rebuild(_reference("doc-a"), _specification())
        second = store.begin_rebuild(_reference("doc-b"), _specification())
        assert first.projection_id != second.projection_id

    def test_unknown_version_lookup_returns_none(self, store) -> None:
        assert store.find_version("missing") is None


class TestResolverReadPath:
    def test_no_active_version_before_activation(self, store) -> None:
        store.begin_rebuild(_reference(), _specification())
        assert store.active_version_ids(1, "kb-1") == frozenset()

    def test_active_version_visible_after_activation(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        _activate(store, version.version_id)
        assert store.active_version_ids(1, "kb-1") == frozenset({version.version_id})

    def test_resolver_is_tenant_scoped(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        _activate(store, version.version_id)
        assert store.active_version_ids(2, "kb-1") == frozenset()
        assert store.active_version_ids(1, "kb-other") == frozenset()

    def test_store_satisfies_the_resolver_protocol(self, store) -> None:
        assert isinstance(store, ActiveProjectionVersionResolver)


class TestLifecycle:
    def test_only_ready_version_can_be_activated(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        with pytest.raises(ProjectionStateError, match="only READY"):
            store.activate(version.version_id)

    def test_unknown_version_activation_is_explicit(self, store) -> None:
        with pytest.raises(ProjectionVersionNotFoundError):
            store.activate("missing")

    def test_activation_switches_pointer_and_retires_previous(self, store) -> None:
        first = store.begin_rebuild(_reference(), _specification())
        _activate(store, first.version_id)
        second = store.begin_rebuild(_reference(), _specification("v2"))
        _activate(store, second.version_id)

        assert store.active_version_ids(1, "kb-1") == frozenset({second.version_id})
        retired = store.find_version(first.version_id)
        assert retired is not None
        assert retired.state is VectorProjectionState.RETIRING
        assert retired.cleanup_after is not None

    def test_retiring_version_enqueues_cleanup_event(self, store) -> None:
        first = store.begin_rebuild(_reference(), _specification())
        _activate(store, first.version_id)
        second = store.begin_rebuild(_reference(), _specification("v2"))
        _activate(store, second.version_id)

        events = store.pending_cleanup_events()
        assert len(events) == 1
        assert events[0].event_type == CLEANUP_EVENT
        assert events[0].version_id == first.version_id
        assert events[0].state == OUTBOX_PENDING
        # 宽限期未到，事件还不该被当作"到期"
        assert store.due_cleanup_events() == ()

    def test_active_version_cannot_be_failed(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        _activate(store, version.version_id)
        with pytest.raises(ProjectionStateError, match="cannot fail"):
            store.mark_failed(version.version_id, "boom")

    def test_failed_version_keeps_reason(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        store.mark_failed(version.version_id, "  ")
        persisted = store.find_version(version.version_id)
        assert persisted is not None
        assert persisted.state is VectorProjectionState.FAILED
        assert persisted.failure_reason == "unknown"

    def test_writing_transition_is_cas_guarded(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        store.mark_writing(version.version_id)
        with pytest.raises(ProjectionStateError, match="invalid projection version"):
            store.mark_writing(version.version_id)


class TestManifest:
    def test_recorded_vector_ids_are_idempotent(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        store.mark_writing(version.version_id)
        store.record_succeeded(version.version_id, "vec-1")
        store.record_succeeded(version.version_id, "vec-1")
        assert store.manifest_vector_ids(version.version_id) == ("vec-1",)
        persisted = store.find_version(version.version_id)
        assert persisted is not None
        assert persisted.written_records == 1

    def test_blank_vector_id_rejected(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        with pytest.raises(ValueError, match="vector_id"):
            store.record_succeeded(version.version_id, "  ")

    def test_failure_marks_version_failed_on_completion(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        store.mark_writing(version.version_id)
        store.record_failure(version.version_id, "provider timeout")
        store.mark_ready_if_no_failure(version.version_id)
        persisted = store.find_version(version.version_id)
        assert persisted is not None
        assert persisted.state is VectorProjectionState.FAILED
        assert persisted.failed_records == 1
        assert persisted.failure_reason == "provider timeout"

    def test_clean_run_becomes_ready(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        store.mark_writing(version.version_id)
        store.record_succeeded(version.version_id, "vec-1")
        store.mark_ready_if_no_failure(version.version_id)
        persisted = store.find_version(version.version_id)
        assert persisted is not None
        assert persisted.state is VectorProjectionState.READY
        assert persisted.written_records == 1


class TestCleanup:
    def test_due_version_is_cleaned_through_manifest(self, store, deleter) -> None:
        first = store.begin_rebuild(_reference(), _specification())
        store.mark_writing(first.version_id)
        store.record_succeeded(first.version_id, "vec-1")
        store.record_succeeded(first.version_id, "vec-2")
        store.mark_ready_if_no_failure(first.version_id)
        store.activate(first.version_id)
        second = store.begin_rebuild(_reference(), _specification("v2"))
        _activate(store, second.version_id, timedelta(0))

        assert store.cleanup_due_projections(10) == 1
        assert deleter.calls == [("kb-1-index", ["vec-1", "vec-2"])]
        assert store.manifest_vector_ids(first.version_id) == ()
        cleaned = store.find_version(first.version_id)
        assert cleaned is not None
        assert cleaned.state is VectorProjectionState.CLEANED

    def test_cleanup_marks_outbox_event_processed(self, store) -> None:
        first = store.begin_rebuild(_reference(), _specification())
        _activate(store, first.version_id)
        second = store.begin_rebuild(_reference(), _specification("v2"))
        _activate(store, second.version_id, timedelta(0))
        store.cleanup_due_projections(10)
        assert store.pending_cleanup_events() == ()

    def test_not_yet_due_version_is_untouched(self, store, deleter) -> None:
        first = store.begin_rebuild(_reference(), _specification())
        _activate(store, first.version_id)
        second = store.begin_rebuild(_reference(), _specification("v2"))
        _activate(store, second.version_id, timedelta(hours=1))
        assert store.cleanup_due_projections(10) == 0
        assert deleter.calls == []

    def test_cleanup_failure_is_recorded_for_retry(self, store, deleter) -> None:
        first = store.begin_rebuild(_reference(), _specification())
        _activate(store, first.version_id)
        store.record_succeeded(first.version_id, "vec-1")
        second = store.begin_rebuild(_reference(), _specification("v2"))
        _activate(store, second.version_id, timedelta(0))

        deleter.fail = True
        assert store.cleanup_due_projections(10) == 0
        events = store.pending_cleanup_events()
        assert events[0].attempts == 1
        assert events[0].last_error is not None
        retiring = store.find_version(first.version_id)
        assert retiring is not None
        assert retiring.state is VectorProjectionState.RETIRING

    def test_cleanup_requires_a_deleter(self, engine) -> None:
        store = VectorProjectionStore(engine)
        with pytest.raises(VectorProjectionError, match="deleter"):
            store.cleanup_due_projections(10)

    def test_non_positive_max_versions_is_a_noop(self, store) -> None:
        assert store.cleanup_due_projections(0) == 0
        assert store.cleanup_due_projections(-1) == 0


class TestProperties:
    def test_defaults_match_java(self) -> None:
        properties = VectorProjectionProperties()
        assert properties.cleanup_delay == timedelta(hours=24)
        assert properties.delete_batch_size == 200

    def test_invalid_values_rejected(self) -> None:
        with pytest.raises(ValueError, match="delete_batch_size"):
            VectorProjectionProperties(delete_batch_size=0)
        with pytest.raises(ValueError, match="cleanup_delay"):
            VectorProjectionProperties(cleanup_delay=timedelta(seconds=-1))
