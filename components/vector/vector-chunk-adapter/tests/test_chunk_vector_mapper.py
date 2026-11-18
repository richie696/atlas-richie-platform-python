"""chunk → VectorRecord 映射契约，以及与 parser-adapter 的串联。"""

from __future__ import annotations

import pytest

from atlas_richie.chunking_core import Chunk, ChunkingRule, DefaultChunkingService, Strategy
from atlas_richie.vector_core import Modality, VectorRecord
from atlas_richie.vector_chunk_adapter import ChunkVectorRecordMapper, VectorRecordContext

pytestmark = pytest.mark.unit


def _chunk(ordinal: int = 0, text: str = "body", start: int = 0, end: int = 4) -> Chunk:
    return Chunk(ordinal=ordinal, text=text, char_start=start, char_end=end)


def _context(**overrides) -> VectorRecordContext:
    base = dict(index_name="kb", document_id="doc-1", version=3)
    base.update(overrides)
    return VectorRecordContext(**base)


class TestMapping:
    def test_id_is_document_version_ordinal(self) -> None:
        record = ChunkVectorRecordMapper().map(_chunk(ordinal=2), _context())
        assert record.id == "doc-1:3:2"

    def test_fields_are_carried(self) -> None:
        record = ChunkVectorRecordMapper().map(
            _chunk(ordinal=1, text="hello", start=5, end=10),
            _context(namespace="tenant-7"),
        )
        assert record.index_name == "kb"
        assert record.document_id == "doc-1"
        assert record.chunk_no == 1
        assert record.version == 3
        assert record.namespace == "tenant-7"
        assert record.content.text == "hello"
        assert record.content.modality is Modality.TEXT
        assert record.status == "ACTIVE"

    def test_chunk_position_metadata_uses_java_camel_case(self) -> None:
        record = ChunkVectorRecordMapper().map(_chunk(2, "abc", 7, 10), _context())
        assert record.metadata["chunkOrdinal"] == 2
        assert record.metadata["charStart"] == 7
        assert record.metadata["charEnd"] == 10

    def test_context_metadata_is_merged_not_replaced(self) -> None:
        context = _context(metadata={"tenantId": 7, "knowledgeBaseId": "kb"})
        record = ChunkVectorRecordMapper().map(_chunk(), context)
        assert record.metadata["tenantId"] == 7
        assert record.metadata["knowledgeBaseId"] == "kb"
        assert record.metadata["chunkOrdinal"] == 0

    def test_context_metadata_is_not_mutated(self) -> None:
        meta = {"tenantId": 7}
        ChunkVectorRecordMapper().map(_chunk(), _context(metadata=meta))
        assert meta == {"tenantId": 7}, "映射不得污染调用方的 metadata"

    def test_position_keys_win_over_context_collisions(self) -> None:
        context = _context(metadata={"chunkOrdinal": 99})
        assert ChunkVectorRecordMapper().map(_chunk(0), context).metadata["chunkOrdinal"] == 0

    def test_vector_is_left_for_the_embedding_step(self) -> None:
        assert ChunkVectorRecordMapper().map(_chunk(), _context()).vector is None

    def test_none_chunk_rejected(self) -> None:
        with pytest.raises(ValueError):
            ChunkVectorRecordMapper().map(None, _context())

    def test_none_context_rejected(self) -> None:
        with pytest.raises(ValueError):
            ChunkVectorRecordMapper().map(_chunk(), None)


class TestIdentitySemantics:
    def test_same_version_remap_is_idempotent(self) -> None:
        mapper = ChunkVectorRecordMapper()
        first = mapper.map(_chunk(0, "text", 0, 4), _context())
        second = mapper.map(_chunk(0, "text", 0, 4), _context())
        assert first.id == second.id

    def test_version_bump_changes_id(self) -> None:
        mapper = ChunkVectorRecordMapper()
        old = mapper.map(_chunk(0), _context(version=3))
        new = mapper.map(_chunk(0), _context(version=4))
        assert old.id != new.id
        assert old.document_id == new.document_id, "同一文档，便于按版本清理"

    def test_ordinals_produce_distinct_ids(self) -> None:
        mapper = ChunkVectorRecordMapper()
        ids = {mapper.map(_chunk(i), _context()).id for i in range(5)}
        assert len(ids) == 5


class TestFullIngestionChain:
    def test_parse_to_chunk_to_vector_record(self) -> None:
        """parse → chunk（带溯源）→ vector record，全程零第三方依赖。"""
        from atlas_richie.chunking_parser_adapter import ParserChunkingAdapter, Section
        from atlas_richie.document_parser import BytesSource, ParserRouter

        source = BytesSource(
            "# 标题\n\n第一段内容。\n\n第二段内容。".encode("utf-8"), name="doc.md"
        )
        mapper = ChunkVectorRecordMapper()
        context = _context(metadata={"tenantId": 7, "knowledgeBaseId": "kb"})
        sections = [
            event.value.result.chunks
            for event in ParserChunkingAdapter().chunk_events(
                ParserRouter().parse(source), file_name="doc.md"
            )
            if isinstance(event, Section)
        ]
        assert len(sections) > 1, "该文档应产出多个 section"
        records = mapper.map_sections(sections, context)
        assert records, "完整链路必须真的产出向量记录"
        assert len({r.id for r in records}) == len(records), "id 不得碰撞"
        for record in records:
            assert record.metadata["tenantId"] == 7
            assert record.vector is None
            assert record.content.text

    def test_real_chunking_service_output_maps_cleanly(self) -> None:
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        rule = ChunkingRule("r", "1", Strategy.FIXED, 12, 0)
        result = DefaultChunkingService().chunk(text, rule)
        assert len(result.chunks) > 1
        mapper = ChunkVectorRecordMapper()
        records = [mapper.map(c, _context()) for c in result.chunks]
        assert [r.chunk_no for r in records] == [c.ordinal for c in result.chunks]
        for record, chunk in zip(records, result.chunks):
            assert record.content.text == chunk.text
            assert record.metadata["charStart"] == chunk.char_start
            assert text[chunk.char_start : chunk.char_end] == chunk.text

class TestGlobalOrdinalNumbering:
    """Regression: per-section chunk ordinals all start at 0, so mapping them
    with chunk-local ordinals collides on documentId:version:ordinal."""

    def test_local_ordinals_would_collide(self) -> None:
        mapper = ChunkVectorRecordMapper()
        sections = [[_chunk(0, "aa", 0, 2)], [_chunk(0, "bb", 0, 2)]]
        ids = [mapper.map(c, _context()).id for sec in sections for c in sec]
        assert ids == ["doc-1:3:0", "doc-1:3:0"], "这就是需要全局编号的原因"

    def test_map_sections_assigns_unique_global_ordinals(self) -> None:
        mapper = ChunkVectorRecordMapper()
        sections = [
            [_chunk(0, "aa", 0, 2), _chunk(1, "bb", 2, 4)],
            [_chunk(0, "cc", 0, 2)],
        ]
        records = mapper.map_sections(sections, _context())
        assert [r.id for r in records] == ["doc-1:3:0", "doc-1:3:1", "doc-1:3:2"]
        assert [r.chunk_no for r in records] == [0, 1, 2]
        assert [r.metadata["chunkOrdinal"] for r in records] == [0, 1, 2]

    def test_char_offsets_stay_section_local(self) -> None:
        """全局编号只影响身份；字符区间仍是各自 section 内的坐标。"""
        records = ChunkVectorRecordMapper().map_sections(
            [[_chunk(0, "aa", 0, 2)], [_chunk(0, "bb", 5, 7)]], _context()
        )
        assert records[1].metadata["charStart"] == 5
        assert records[1].metadata["charEnd"] == 7

    def test_explicit_ordinal_override(self) -> None:
        record = ChunkVectorRecordMapper().map(_chunk(0), _context(), ordinal=9)
        assert record.id == "doc-1:3:9"
        assert record.chunk_no == 9

    def test_negative_ordinal_rejected(self) -> None:
        with pytest.raises(ValueError):
            ChunkVectorRecordMapper().map(_chunk(0), _context(), ordinal=-1)

    def test_empty_sections(self) -> None:
        assert ChunkVectorRecordMapper().map_sections([], _context()) == []
        assert ChunkVectorRecordMapper().map_sections([[], []], _context()) == []
