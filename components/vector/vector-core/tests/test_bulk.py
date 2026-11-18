"""批量入库编排：事件协议、攒批、失败语义与库管嵌入分支。"""

from __future__ import annotations

import pytest

from atlas_richie.vector_core import (
    BulkCompleted,
    BulkIngestionPipeline,
    BulkItemFailed,
    BulkItemStarted,
    BulkItemSucceeded,
    BulkOptions,
    BulkProcessingStage,
    BulkStarted,
    EmbeddedVectorRecord,
    ModalityAwareRecordEmbedder,
    TextContent,
    VectorRecord,
)


class FakeEmbedder:
    def __init__(self, fail_ids: set[str] | None = None) -> None:
        self.fail_ids = fail_ids or set()
        self.calls: list[str] = []

    def embed(self, record: VectorRecord) -> tuple[float, ...]:
        self.calls.append(record.id)
        if record.id in self.fail_ids:
            raise RuntimeError("embedding model timeout")
        return (0.1, 0.2, 0.3)


class FakeWriter:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.batches: list[list[EmbeddedVectorRecord]] = []

    def write(self, index_name: str, records) -> None:
        self.batches.append(list(records))
        if self.fail:
            raise RuntimeError("provider write failed")


class FakeStoreManagedWriter:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.batches: list[list[VectorRecord]] = []

    def write(self, index_name: str, records) -> None:
        self.batches.append(list(records))
        if self.fail:
            raise RuntimeError("provider write failed")


def _record(record_id: str = "r1", index_name: str = "idx", item_id: str | None = None):
    metadata = {} if item_id is None else {"__itemId": item_id}
    return VectorRecord(
        id=record_id,
        index_name=index_name,
        content=TextContent(text=f"text-{record_id}"),
        metadata=metadata,
    )


def _pipeline(embedder=None, writer=None, store_managed=None):
    return BulkIngestionPipeline(
        embedder, writer, store_managed_writer=store_managed
    )


class TestEventProtocol:
    def test_started_then_completed(self) -> None:
        pipeline = _pipeline(FakeEmbedder(), FakeWriter())
        events = list(pipeline.execute("idx", [_record()]))
        assert isinstance(events[0], BulkStarted)
        assert isinstance(events[-1], BulkCompleted)
        assert events[0].operation_id == events[-1].operation_id

    def test_single_item_event_order(self) -> None:
        pipeline = _pipeline(FakeEmbedder(), FakeWriter())
        events = list(pipeline.execute("idx", [_record()]))
        stages = [
            (type(event).__name__, getattr(event, "stage", None))
            for event in events
        ]
        assert stages[1] == ("BulkItemStarted", BulkProcessingStage.EMBEDDING)
        assert stages[2] == ("BulkItemStarted", BulkProcessingStage.PERSISTING)
        assert isinstance(events[3], BulkItemSucceeded)
        assert events[3].vector_id == "r1"

    def test_execution_is_lazy(self) -> None:
        writer = FakeWriter()
        pipeline = _pipeline(FakeEmbedder(), writer)
        stream = pipeline.execute("idx", [_record()])
        assert writer.batches == [], "调用 execute 不应触发写入"
        list(stream)
        assert len(writer.batches) == 1

    def test_blank_index_name_rejected(self) -> None:
        pipeline = _pipeline(FakeEmbedder(), FakeWriter())
        with pytest.raises(ValueError, match="index_name"):
            list(pipeline.execute("  ", [_record()]))

    def test_none_records_rejected(self) -> None:
        pipeline = _pipeline(FakeEmbedder(), FakeWriter())
        with pytest.raises(ValueError, match="records"):
            list(pipeline.execute("idx", None))

    def test_pipeline_requires_a_write_path(self) -> None:
        with pytest.raises(ValueError, match="embedder"):
            BulkIngestionPipeline(FakeEmbedder(), None)

    def test_store_managed_excludes_embedding_stage(self) -> None:
        pipeline = _pipeline(store_managed=FakeStoreManagedWriter())
        events = list(pipeline.execute("idx", [_record()]))
        stages = {getattr(event, "stage", None) for event in events}
        assert BulkProcessingStage.EMBEDDING not in stages
        assert BulkProcessingStage.PERSISTING in stages

    def test_store_managed_cannot_be_combined_with_embedder(self) -> None:
        with pytest.raises(ValueError, match="cannot be combined"):
            BulkIngestionPipeline(
                FakeEmbedder(), FakeWriter(), store_managed_writer=FakeStoreManagedWriter()
            )


class TestBatching:
    def test_write_batch_size_splits_calls(self) -> None:
        writer = FakeWriter()
        pipeline = _pipeline(FakeEmbedder(), writer)
        records = [_record(f"r{i}") for i in range(5)]
        list(pipeline.execute("idx", records, BulkOptions(write_batch_size=2)))
        assert [len(batch) for batch in writer.batches] == [2, 2, 1]

    def test_write_requests_count_calls_not_records(self) -> None:
        writer = FakeWriter()
        pipeline = _pipeline(FakeEmbedder(), writer)
        records = [_record(f"r{i}") for i in range(5)]
        events = list(pipeline.execute("idx", records, BulkOptions(write_batch_size=2)))
        summary = events[-1].summary
        assert summary.write_requests == 3
        assert summary.embedding_requests == 5
        assert summary.succeeded == 5
        assert summary.processed == 5

    def test_non_positive_batch_size_rejected(self) -> None:
        with pytest.raises(ValueError, match="write_batch_size"):
            BulkOptions(write_batch_size=0)


class TestFailureSemantics:
    def test_embedding_failure_does_not_stop_the_batch(self) -> None:
        embedder = FakeEmbedder(fail_ids={"r2"})
        writer = FakeWriter()
        pipeline = _pipeline(embedder, writer)
        records = [_record(f"r{i}") for i in range(3)]
        events = list(pipeline.execute("idx", records))
        failures = [event for event in events if isinstance(event, BulkItemFailed)]
        assert len(failures) == 1
        failure = failures[0]
        assert failure.stage is BulkProcessingStage.EMBEDDING
        assert failure.error_code == "RuntimeError"
        assert failure.message == "embedding model timeout"
        assert len(writer.batches) == 1, "失败的条目不进入落库批次"
        summary = events[-1].summary
        assert summary.failed == 1
        assert summary.succeeded == 2

    def test_write_failure_replays_per_item(self) -> None:
        writer = FakeWriter(fail=True)
        pipeline = _pipeline(FakeEmbedder(), writer)
        records = [_record(f"r{i}") for i in range(2)]
        events = list(pipeline.execute("idx", records))
        failures = [event for event in events if isinstance(event, BulkItemFailed)]
        assert len(failures) == 2
        assert all(f.stage is BulkProcessingStage.PERSISTING for f in failures)
        assert events[-1].summary.failed == 2
        assert events[-1].summary.succeeded == 0

    def test_index_name_mismatch_is_reported_as_failure(self) -> None:
        writer = FakeWriter()
        pipeline = _pipeline(FakeEmbedder(), writer)
        events = list(pipeline.execute("idx", [_record("r1", index_name="other")]))
        failures = [event for event in events if isinstance(event, BulkItemFailed)]
        assert len(failures) == 1
        assert failures[0].stage is BulkProcessingStage.EMBEDDING
        assert writer.batches == []

    def test_fail_fast_stops_after_first_failure(self) -> None:
        embedder = FakeEmbedder(fail_ids={"r0"})
        writer = FakeWriter()
        pipeline = _pipeline(embedder, writer)
        records = [_record(f"r{i}") for i in range(5)]
        events = list(pipeline.execute("idx", records, BulkOptions(fail_fast=True)))
        failures = [event for event in events if isinstance(event, BulkItemFailed)]
        assert len(failures) == 1
        assert embedder.calls == ["r0"]

    def test_error_message_is_truncated(self) -> None:
        class Boom(Exception):
            pass

        class FailingEmbedder:
            def embed(self, record):
                raise Boom("x" * 1000)

        pipeline = _pipeline(FailingEmbedder(), FakeWriter())
        events = list(pipeline.execute("idx", [_record()]))
        failure = next(e for e in events if isinstance(e, BulkItemFailed))
        assert len(failure.message) == 512

    def test_source_error_is_reported_as_a_failure_event(self) -> None:
        def exploding():
            yield _record("r1")
            raise RuntimeError("source exploded")

        writer = FakeWriter()
        pipeline = _pipeline(FakeEmbedder(), writer)
        events = list(pipeline.execute("idx", exploding()))
        failures = [event for event in events if isinstance(event, BulkItemFailed)]
        assert len(failures) == 1
        assert failures[0].error_code == "RuntimeError"
        assert failures[0].message == "source exploded"
        assert isinstance(events[-1], BulkCompleted)

    def test_already_embedded_batch_is_not_dropped_on_source_error(self) -> None:
        def exploding():
            yield _record("r1")
            raise RuntimeError("source exploded")

        writer = FakeWriter()
        pipeline = _pipeline(FakeEmbedder(), writer)
        list(pipeline.execute("idx", exploding()))
        assert len(writer.batches) == 1
        assert [item.record.id for item in writer.batches[0]] == ["r1"]

    def test_completed_event_is_emitted_after_failure(self) -> None:
        embedder = FakeEmbedder(fail_ids={"r1"})
        pipeline = _pipeline(embedder, FakeWriter())
        events = list(pipeline.execute("idx", [_record()]))
        assert isinstance(events[-1], BulkCompleted)
        assert events[-1].summary.failed == 1


class TestItemIdentity:
    def test_item_id_comes_from_metadata(self) -> None:
        writer = FakeWriter()
        pipeline = _pipeline(FakeEmbedder(), writer)
        events = list(pipeline.execute("idx", [_record(item_id="item-7")]))
        started = next(e for e in events if isinstance(e, BulkItemStarted))
        assert started.item_id == "item-7"

    def test_missing_item_id_becomes_unknown(self) -> None:
        pipeline = _pipeline(FakeEmbedder(), FakeWriter())
        events = list(pipeline.execute("idx", [_record()]))
        started = next(e for e in events if isinstance(e, BulkItemStarted))
        assert started.item_id == "unknown"

    def test_blank_record_id_is_assigned(self) -> None:
        writer = FakeWriter()
        pipeline = _pipeline(FakeEmbedder(), writer)
        list(pipeline.execute("idx", [_record("  ")]))
        assert writer.batches[0][0].record.id
        assert writer.batches[0][0].record.id != "  "


class TestModalityAdapter:
    def test_adapter_delegates_to_modality_service(self) -> None:
        from atlas_richie.vector_core import ModalityAwareEmbeddingService

        class Model:
            def embed(self, text: str) -> tuple[float, ...]:
                return (1.0, 0.0)

            def dimensions(self) -> int:
                return 2

        service = ModalityAwareEmbeddingService(Model())
        embedder = ModalityAwareRecordEmbedder(service)
        assert embedder.embed(_record()) == (1.0, 0.0)
