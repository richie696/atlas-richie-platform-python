"""投影写入器：metadata 装饰、状态机驱动与 manifest 落库。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from atlas_richie.vector_core import (
    BulkIngestionPipeline,
    BulkItemFailed,
    BulkItemSucceeded,
    TextContent,
    VectorProjectionReference,
    VectorProjectionSpecification,
    VectorProjectionState,
    VectorRecord,
)
from atlas_richie.vector_persistence_sqlalchemy import (
    VectorProjectionStore,
    VectorProjectionWriter,
)


class FakeEmbedder:
    def embed(self, record: VectorRecord) -> tuple[float, ...]:
        return (0.1, 0.2, 0.3)


class FakeWriter:
    def __init__(self) -> None:
        self.batches: list[list] = []

    def write(self, index_name: str, records) -> None:
        self.batches.append(list(records))


class FailingEmbedder:
    def embed(self, record: VectorRecord) -> tuple[float, ...]:
        raise RuntimeError("embedding model timeout")


@pytest.fixture
def store():
    return VectorProjectionStore(create_engine("sqlite://"))


@pytest.fixture
def writer(store):
    return VectorProjectionWriter(store, BulkIngestionPipeline(FakeEmbedder(), FakeWriter()))


def _reference() -> VectorProjectionReference:
    return VectorProjectionReference(
        tenant_id=1, knowledge_base_id="kb-1", document_ref="doc-42"
    )


def _specification() -> VectorProjectionSpecification:
    return VectorProjectionSpecification(
        source_version="etag-9", index_name="kb-1-index", embedding_space_id="space-a"
    )


def _record(record_id: str, index_name: str = "kb-1-index") -> VectorRecord:
    return VectorRecord(
        id=record_id,
        index_name=index_name,
        content=TextContent(text=f"text-{record_id}"),
    )


class TestWriteFlow:
    def test_write_drives_version_to_ready(self, store, writer) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        list(writer.write(version.version_id, [_record("v1")]))
        persisted = store.find_version(version.version_id)
        assert persisted is not None
        assert persisted.state is VectorProjectionState.READY
        assert persisted.written_records == 1
        assert persisted.failed_records == 0

    def test_manifest_records_written_vector_ids(self, store, writer) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        list(writer.write(version.version_id, [_record("v1"), _record("v2")]))
        assert store.manifest_vector_ids(version.version_id) == ("v1", "v2")

    def test_version_is_writing_during_the_stream(self, store, writer) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        stream = writer.write(version.version_id, [_record("v1")])
        assert store.find_version(version.version_id).state is VectorProjectionState.PREPARING
        list(stream)
        assert store.find_version(version.version_id).state is VectorProjectionState.READY

    def test_events_are_forwarded_to_the_caller(self, store, writer) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        events = list(writer.write(version.version_id, [_record("v1")]))
        assert any(isinstance(event, BulkItemSucceeded) for event in events)

    def test_unknown_version_rejected(self, writer) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            list(writer.write("missing", [_record("v1")]))

    def test_terminal_version_rejected(self, store, writer) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        store.mark_failed(version.version_id, "boom")
        with pytest.raises(ValueError, match="terminal state"):
            list(writer.write(version.version_id, [_record("v1")]))


class TestMetadataDecoration:
    def test_record_gets_the_six_projection_fields(self, store, writer) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        captured: list[VectorRecord] = []

        class CapturingWriter:
            def write(self, index_name: str, records) -> None:
                captured.extend(item.record for item in records)

        writer = VectorProjectionWriter(
            store, BulkIngestionPipeline(FakeEmbedder(), CapturingWriter())
        )
        list(writer.write(version.version_id, [_record("v1")]))
        metadata = captured[0].metadata
        assert metadata["tenantId"] == 1
        assert metadata["knowledgeBaseId"] == "kb-1"
        assert metadata["projectionId"] == version.projection_id
        assert metadata["projectionVersionId"] == version.version_id
        assert metadata["sourceVersion"] == "etag-9"
        assert metadata["embeddingSpaceId"] == "space-a"
        assert metadata["status"] == "ACTIVE"

    def test_document_id_comes_from_the_reference(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        captured: list[VectorRecord] = []

        class CapturingWriter:
            def write(self, index_name: str, records) -> None:
                captured.extend(item.record for item in records)

        writer = VectorProjectionWriter(
            store, BulkIngestionPipeline(FakeEmbedder(), CapturingWriter())
        )
        list(writer.write(version.version_id, [_record("v1")]))
        assert captured[0].document_id == "doc-42"

    def test_index_name_mismatch_fails_the_version(self, store, writer) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        events = list(
            writer.write(version.version_id, [_record("v1", index_name="other")])
        )
        failures = [event for event in events if isinstance(event, BulkItemFailed)]
        assert len(failures) == 1
        assert failures[0].error_code == "ValueError"
        assert "index_name" in failures[0].message
        persisted = store.find_version(version.version_id)
        assert persisted is not None
        assert persisted.state is VectorProjectionState.FAILED
        assert persisted.failed_records == 1

    def test_missing_index_name_is_filled_from_the_version(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        captured: list[VectorRecord] = []

        class CapturingWriter:
            def write(self, index_name: str, records) -> None:
                captured.extend(item.record for item in records)

        writer = VectorProjectionWriter(
            store, BulkIngestionPipeline(FakeEmbedder(), CapturingWriter())
        )
        record = VectorRecord(
            id="v1", index_name="", content=TextContent(text="t")
        )
        list(writer.write(version.version_id, [record]))
        assert captured[0].index_name == "kb-1-index"


class TestFailureHandling:
    def test_embedding_failure_marks_the_version_failed(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        writer = VectorProjectionWriter(
            store, BulkIngestionPipeline(FailingEmbedder(), FakeWriter())
        )
        list(writer.write(version.version_id, [_record("v1")]))
        persisted = store.find_version(version.version_id)
        assert persisted is not None
        assert persisted.state is VectorProjectionState.FAILED
        assert persisted.failed_records == 1
        assert persisted.failure_reason is not None

    def test_stream_exception_marks_the_version_failed(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())

        class ExplodingRecords:
            def __iter__(self):
                raise RuntimeError("source exploded")

        writer = VectorProjectionWriter(
            store, BulkIngestionPipeline(FakeEmbedder(), FakeWriter())
        )
        events = list(writer.write(version.version_id, ExplodingRecords()))
        failures = [event for event in events if isinstance(event, BulkItemFailed)]
        assert len(failures) == 1
        assert failures[0].error_code == "RuntimeError"
        persisted = store.find_version(version.version_id)
        assert persisted is not None
        assert persisted.state is VectorProjectionState.FAILED
        assert persisted.failed_records == 1

    def test_failure_events_are_forwarded(self, store) -> None:
        version = store.begin_rebuild(_reference(), _specification())
        writer = VectorProjectionWriter(
            store, BulkIngestionPipeline(FailingEmbedder(), FakeWriter())
        )
        events = list(writer.write(version.version_id, [_record("v1")]))
        assert any(isinstance(event, BulkItemFailed) for event in events)
