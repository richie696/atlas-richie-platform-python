"""真实 PostgreSQL + pgvector 集成测试。"""

from __future__ import annotations

import math

import pytest

from atlas_richie.vector_core import (
    AccessScope,
    VectorCapability,
    VectorDiversificationOptions,
    VectorQueryErrorCode,
    VectorQueryRequest,
    VectorQueryResolver,
    VectorQueryValidationException,
    VectorRecord,
    VectorScoreStage,
    VectorStoreEngine,
    VectorStoreNotExistsError,
    and_,
    build_access_filter,
    eq,
)
from atlas_richie.vector_pgvector import PgVectorProperties, PgVectorStore

pytestmark = pytest.mark.integration


def _record(
    id: str,
    vector,
    *,
    tenant: int = 1,
    kb: str = "kb",
    visibility: str = "COMPANY",
    departments=(),
    principals=(),
    status: str = "ACTIVE",
    content: str | None = None,
) -> VectorRecord:
    return VectorRecord.text(
        "idx",
        content or f"content-{id}",
        id=id,
        vector=tuple(vector),
        metadata={
            "tenantId": tenant,
            "knowledgeBaseId": kb,
            "status": status,
            "visibility": visibility,
            "allowedDepartmentIds": list(departments),
            "allowedPrincipalIds": list(principals),
        },
    )


def _resolve(store, request: VectorQueryRequest):
    resolver = VectorQueryResolver(
        store_defaults=store.query_defaults(), score_semantics=store.score_semantics()
    )
    return resolver.resolve(request)


class TestSchemaAndCrud:
    def test_satisfies_engine_protocol(self, store_factory) -> None:
        assert isinstance(store_factory(), VectorStoreEngine)

    def test_ensure_schema_is_idempotent(self, store_factory) -> None:
        store = store_factory()
        store.ensure_schema()
        store.ensure_schema()
        assert store.count() == 0

    def test_upsert_and_count(self, store_factory) -> None:
        store = store_factory()
        assert store.upsert([_record("a", (1, 0, 0)), _record("b", (0, 1, 0))]) == 2
        assert store.count() == 2

    def test_upsert_empty_is_noop(self, store_factory) -> None:
        assert store_factory().upsert([]) == 0

    def test_upsert_conflict_updates_in_place(self, store_factory) -> None:
        store = store_factory()
        store.upsert([_record("a", (1, 0, 0), content="old")])
        store.upsert([_record("a", (0, 1, 0), content="new")])
        assert store.count() == 1
        hit = store.search((0, 1, 0), _resolve(store, VectorQueryRequest("q", top_k=1)))[0]
        assert hit.id == "a"
        assert hit.content == "new"

    def test_delete_reports_removed_count(self, store_factory) -> None:
        store = store_factory()
        store.upsert([_record("a", (1, 0, 0)), _record("b", (0, 1, 0))])
        assert store.delete(["a", "missing"]) == 1
        assert store.count() == 1
        assert store.delete([]) == 0

    def test_round_trip_preserves_fields(self, store_factory) -> None:
        store = store_factory()
        record = VectorRecord.text(
            "idx", "hello", id="a", vector=(1.0, 0.0, 0.0),
            metadata={"tenantId": 1, "k": "v"},
        )
        object.__setattr__(record, "tags", ("t1", "t2"))
        object.__setattr__(record, "source", "doc-1")
        object.__setattr__(record, "namespace", "ns")
        store.upsert([record])
        hit = store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q")))[0]
        assert hit.content == "hello"
        assert hit.tags == ("t1", "t2")
        assert hit.source == "doc-1"
        assert hit.namespace == "ns"
        assert hit.status == "ACTIVE"
        assert hit.metadata["k"] == "v"
        assert hit.created_at is not None

    def test_image_record_round_trip(self, store_factory) -> None:
        store = store_factory()
        store.upsert(
            [VectorRecord.image("idx", b"\x89PNG\r\n", "image/png", id="img", vector=(1, 0, 0))]
        )
        hit = store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q")))[0]
        assert hit.id == "img"
        assert hit.content is None

    def test_missing_embedding_rejected(self, store_factory) -> None:
        store = store_factory()
        with pytest.raises(VectorQueryValidationException) as info:
            store.upsert([VectorRecord.text("idx", "x", id="a")])
        assert info.value.code is VectorQueryErrorCode.INVALID_VALUE

    def test_wrong_record_dimension_rejected(self, store_factory) -> None:
        store = store_factory(dimension=3)
        with pytest.raises(VectorQueryValidationException, match="dimension"):
            store.upsert([_record("a", (1, 0))])

    def test_wrong_query_dimension_rejected(self, store_factory) -> None:
        store = store_factory(dimension=3)
        with pytest.raises(VectorQueryValidationException, match="dimension"):
            store.search((1, 0), _resolve(store, VectorQueryRequest("q")))

    def test_missing_table_is_translated(self, pg_dsn) -> None:
        store = PgVectorStore(
            PgVectorProperties(dsn=pg_dsn, table="vt_does_not_exist_xyz", dimension=3),
            store_id="pgvector-test",
        )
        try:
            with pytest.raises(VectorStoreNotExistsError):
                store.count()
        finally:
            store.close()

    def test_close_is_idempotent_and_reconnects(self, store_factory) -> None:
        store = store_factory()
        store.upsert([_record("a", (1, 0, 0))])
        store.close()
        store.close()
        assert store.count() == 1, "close 后再操作应自动重连"


class TestSearchRanking:
    def test_cosine_orders_by_similarity(self, store_factory) -> None:
        store = store_factory(metric="cosine")
        store.upsert(
            [_record("a", (1, 0, 0)), _record("b", (0.9, 0.1, 0)), _record("c", (0, 1, 0))]
        )
        hits = store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q", top_k=3)))
        assert [h.id for h in hits] == ["a", "b", "c"]
        assert hits[0].score == pytest.approx(1.0)
        assert hits[2].score == pytest.approx(0.0, abs=1e-9)

    def test_l2_score_transform(self, store_factory) -> None:
        store = store_factory(metric="l2")
        store.upsert([_record("a", (1, 0, 0)), _record("c", (0, 1, 0))])
        hits = store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q", top_k=2)))
        assert hits[0].score == pytest.approx(1.0)
        assert hits[1].score == pytest.approx(1.0 / (1.0 + math.sqrt(2)), rel=1e-6)

    def test_inner_product_score_is_negated_distance(self, store_factory) -> None:
        store = store_factory(metric="ip")
        store.upsert([_record("a", (1, 0, 0)), _record("b", (0.9, 0.1, 0))])
        hits = store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q", top_k=2)))
        assert [h.id for h in hits] == ["a", "b"]
        assert hits[0].score == pytest.approx(1.0)
        assert hits[1].score == pytest.approx(0.9)

    def test_metric_aliases(self, store_factory) -> None:
        for alias, expected in (("euclidean", "l2"), ("dot", "ip")):
            store = store_factory(metric=alias, table=f"vt_alias_{expected}")
            assert store.properties.metric == expected
            store.upsert([_record("a", (1, 0, 0))])
            assert store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q")))[0].score > 0

    def test_min_score_filters_hits(self, store_factory) -> None:
        store = store_factory(metric="cosine")
        store.upsert([_record("a", (1, 0, 0)), _record("c", (0, 1, 0))])
        hits = store.search(
            (1, 0, 0), _resolve(store, VectorQueryRequest("q", top_k=5, min_score=0.5))
        )
        assert [h.id for h in hits] == ["a"]

    def test_top_k_truncates(self, store_factory) -> None:
        store = store_factory()
        store.upsert([_record(f"id{i}", (1, i / 100, 0)) for i in range(10)])
        hits = store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q", top_k=3)))
        assert len(hits) == 3

    def test_candidate_limit_caps_recall(self, store_factory) -> None:
        store = store_factory()
        store.upsert([_record(f"id{i}", (1, i / 100, 0)) for i in range(10)])
        hits = store.search(
            (1, 0, 0),
            _resolve(store, VectorQueryRequest("q", top_k=4, candidate_limit=4)),
        )
        assert [h.id for h in hits] == ["id0", "id1", "id2", "id3"]

    def test_candidate_limit_below_top_k_is_rejected(self, store_factory) -> None:
        store = store_factory()
        with pytest.raises(VectorQueryValidationException) as info:
            _resolve(store, VectorQueryRequest("q", top_k=10, candidate_limit=4))
        assert info.value.code is VectorQueryErrorCode.INVALID_VALUE

    def test_empty_table_returns_empty(self, store_factory) -> None:
        store = store_factory()
        assert store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q"))) == []


class TestAclPushdown:
    def test_tenant_isolation(self, store_factory) -> None:
        store = store_factory()
        store.upsert([_record("mine", (1, 0, 0), tenant=1), _record("other", (1, 0, 0), tenant=2)])
        scope = AccessScope(tenant_id=1, tenant_admin=True)
        hits = store.search(
            (1, 0, 0),
            _resolve(store, VectorQueryRequest("q", filter=build_access_filter("kb", scope))),
        )
        assert [h.id for h in hits] == ["mine"]

    def test_knowledge_base_isolation(self, store_factory) -> None:
        store = store_factory()
        store.upsert([_record("in", (1, 0, 0), kb="kb"), _record("out", (1, 0, 0), kb="other")])
        scope = AccessScope(tenant_id=1, tenant_admin=True)
        hits = store.search(
            (1, 0, 0),
            _resolve(store, VectorQueryRequest("q", filter=build_access_filter("kb", scope))),
        )
        assert [h.id for h in hits] == ["in"]

    def test_inactive_documents_excluded(self, store_factory) -> None:
        store = store_factory()
        store.upsert(
            [_record("live", (1, 0, 0)), _record("deleted", (1, 0, 0), status="DELETED")]
        )
        scope = AccessScope(tenant_id=1, tenant_admin=True)
        hits = store.search(
            (1, 0, 0),
            _resolve(store, VectorQueryRequest("q", filter=build_access_filter("kb", scope))),
        )
        assert [h.id for h in hits] == ["live"]

    def test_acl_is_prefilter_not_post_truncation(self, store_factory) -> None:
        """50 条无权文档相似度更高且超出 candidate_limit；后裁剪会漏掉唯一有权文档。"""
        store = store_factory()
        store.upsert([_record(f"noise{i}", (1, 0, 0), tenant=2) for i in range(50)])
        store.upsert([_record("visible", (0.8, 0.6, 0), tenant=1)])
        scope = AccessScope(tenant_id=1, tenant_admin=True)
        hits = store.search(
            (1, 0, 0),
            _resolve(
                store,
                VectorQueryRequest("q", top_k=1, filter=build_access_filter("kb", scope)),
            ),
        )
        assert [h.id for h in hits] == ["visible"]

    @pytest.mark.parametrize(
        ("visibility", "departments", "principals", "visible"),
        [
            ("COMPANY", (), (), True),
            ("DEPARTMENT", ("d1",), (), True),
            ("DEPARTMENT", ("d2",), (), False),
            ("DEPARTMENT", (), ("u1",), False),
            ("CUSTOM", ("d1",), (), True),
            ("CUSTOM", (), ("u1",), True),
            ("CUSTOM", ("d2",), ("u2",), False),
            ("PRIVATE", (), ("u1",), True),
            ("PRIVATE", ("d1",), (), False),
            ("PRIVATE", (), (), False),
        ],
    )
    def test_visibility_decision_tree(
        self, store_factory, visibility, departments, principals, visible
    ) -> None:
        store = store_factory()
        store.upsert(
            [
                _record(
                    "doc", (1, 0, 0), visibility=visibility,
                    departments=("d1",) if visibility != "COMPANY" else (),
                    principals=("u1",) if visibility in ("CUSTOM", "PRIVATE") else (),
                )
            ]
        )
        scope = AccessScope(
            tenant_id=1,
            department_ids=frozenset(departments),
            principal_ids=frozenset(principals),
        )
        hits = store.search(
            (1, 0, 0),
            _resolve(store, VectorQueryRequest("q", filter=build_access_filter("kb", scope))),
        )
        assert bool(hits) is visible

    def test_empty_scope_sees_only_company(self, store_factory) -> None:
        store = store_factory()
        store.upsert(
            [
                _record("company", (1, 0, 0), visibility="COMPANY"),
                _record("private", (1, 0, 0), visibility="PRIVATE", principals=("u1",)),
            ]
        )
        hits = store.search(
            (1, 0, 0),
            _resolve(
                store,
                VectorQueryRequest("q", filter=build_access_filter("kb", AccessScope(tenant_id=1))),
            ),
        )
        assert [h.id for h in hits] == ["company"]

    def test_tenant_admin_bypasses_visibility(self, store_factory) -> None:
        store = store_factory()
        store.upsert([_record("private", (1, 0, 0), visibility="PRIVATE", principals=("u1",))])
        hits = store.search(
            (1, 0, 0),
            _resolve(
                store,
                VectorQueryRequest(
                    "q", filter=build_access_filter("kb", AccessScope(tenant_id=1, tenant_admin=True))
                ),
            ),
        )
        assert [h.id for h in hits] == ["private"]

    def test_business_filter_combines_with_acl(self, store_factory) -> None:
        store = store_factory()
        store.upsert([_record("a", (1, 0, 0)), _record("b", (1, 0, 0))])
        scope_filter = build_access_filter("kb", AccessScope(tenant_id=1, tenant_admin=True))
        combined = and_(scope_filter, eq("knowledgeBaseId", "kb"))
        hits = store.search(
            (1, 0, 0), _resolve(store, VectorQueryRequest("q", filter=combined))
        )
        assert len(hits) == 2


class TestDiversificationAgainstDatabase:
    def test_mmr_reorders_real_candidates(self, store_factory) -> None:
        store = store_factory()
        store.upsert(
            [
                _record("a", (1, 0, 0)),
                _record("b", (0.99, 0.01, 0)),
                _record("c", (0, 1, 0)),
            ]
        )
        request = VectorQueryRequest(
            "q", top_k=2, diversification=VectorDiversificationOptions(mmr_enabled=True)
        )
        hits = store.search((1, 0, 0), _resolve(store, request))
        assert [h.id for h in hits] == ["a", "c"]
        assert all(h.vector is None for h in hits), "默认不回传向量"

    def test_include_vectors_returns_embeddings(self, store_factory) -> None:
        store = store_factory()
        store.upsert([_record("a", (1, 0, 0))])
        request = VectorQueryRequest(
            "q", top_k=1, diversification=VectorDiversificationOptions(include_vectors=True)
        )
        hits = store.search((1, 0, 0), _resolve(store, request))
        assert hits[0].vector == pytest.approx((1.0, 0.0, 0.0))

    def test_plain_search_does_not_fetch_vectors(self, store_factory) -> None:
        store = store_factory()
        store.upsert([_record("a", (1, 0, 0))])
        hits = store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q")))
        assert hits[0].vector is None


class TestIndexAndTuning:
    def test_hnsw_index_created(self, store_factory) -> None:
        store = store_factory(index_type="hnsw")
        store.upsert([_record("a", (1, 0, 0))])
        assert store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q")))[0].id == "a"

    def test_ivfflat_index_created(self, store_factory) -> None:
        store = store_factory(index_type="ivfflat")
        store.upsert([_record("a", (1, 0, 0))])
        assert store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q")))[0].id == "a"

    def test_no_index_still_searches(self, store_factory) -> None:
        store = store_factory(index_type="none")
        store.upsert([_record("a", (1, 0, 0))])
        assert store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q")))[0].id == "a"

    def test_hnsw_ef_search_is_applied(self, store_factory) -> None:
        store = store_factory(index_type="hnsw", hnsw_ef_search=64)
        store.upsert([_record(f"id{i}", (1, i / 100, 0)) for i in range(20)])
        hits = store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q", top_k=5)))
        assert len(hits) == 5

    def test_ivfflat_probes_is_applied(self, store_factory) -> None:
        store = store_factory(index_type="ivfflat", ivfflat_probes=10)
        store.upsert([_record(f"id{i}", (1, i / 100, 0)) for i in range(20)])
        hits = store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q", top_k=5)))
        assert len(hits) == 5

    def test_tuning_is_transaction_scoped(self, store_factory) -> None:
        store = store_factory(index_type="hnsw", hnsw_ef_search=64)
        store.upsert([_record("a", (1, 0, 0))])
        store.search((1, 0, 0), _resolve(store, VectorQueryRequest("q")))
        with store._session() as conn:
            value = conn.execute("SHOW hnsw.ef_search").fetchone()[0]
        assert value != "64", "SET LOCAL 不应泄漏到后续事务"


class TestContractsAndReceipt:
    def test_capabilities_declaration(self, store_factory) -> None:
        capabilities = store_factory().capabilities()
        for capability in (
            VectorCapability.NATIVE_FILTER,
            VectorCapability.ACL_FILTER,
            VectorCapability.CANDIDATE_VECTOR,
            VectorCapability.QUERY_TUNING,
            VectorCapability.SCORE_STAGES,
            VectorCapability.INDEX_LIFECYCLE,
            VectorCapability.PRECOMPUTED_VECTOR,
        ):
            assert capabilities.supports(capability), capability
        assert not capabilities.supports(VectorCapability.SERVER_SIDE_MMR)
        assert not capabilities.supports(VectorCapability.ACL_SAFE_HYBRID)
        assert capabilities.descriptor(VectorCapability.CANDIDATE_VECTOR).constraints[
            "client-mmr"
        ] == "true"

    def test_score_semantics_per_metric(self, store_factory) -> None:
        for metric, normalized in (("cosine", True), ("l2", True), ("ip", False)):
            semantics = store_factory(metric=metric, table=f"vt_sem_{metric}").score_semantics()
            descriptor = semantics.descriptor(VectorScoreStage.FINAL_SCORE)
            assert descriptor.normalized is normalized
            assert descriptor.source.startswith("postgresql.adapter.")

    def test_store_defaults_raise_candidate_limit(self, store_factory) -> None:
        store = store_factory()
        assert store.query_defaults().candidate_limit == 40
        assert _resolve(store, VectorQueryRequest.of("q")).candidate_limit == 40

    def test_receipt_fingerprint_and_evidence(self, store_factory) -> None:
        store = store_factory(dimension=3, metric="cosine", index_type="hnsw")
        resolver = VectorQueryResolver(
            store_defaults=store.query_defaults(), score_semantics=store.score_semantics()
        )
        request = VectorQueryRequest("q", top_k=5)
        resolved = resolver.resolve(request)
        receipt = store.receipt(resolved, resolver, request)
        assert receipt.provider == "POSTGRESQL"
        assert receipt.logical_index_fingerprint.endswith(":3:cosine:hnsw")
        by_name = {p.name: p for p in receipt.parameters}
        assert by_name["topK"].source.value == "REQUEST"
        assert by_name["topK"].disposition.value == "APPLIED"
        assert by_name["topK"].effective == "5"
        assert by_name["candidateLimit"].source.value == "STORE_DEFAULT"
        assert by_name["candidateLimit"].disposition.value == "DEFAULTED"

    def test_execute_returns_results_and_receipt(self, store_factory) -> None:
        store = store_factory()
        store.upsert([_record("a", (1, 0, 0))])
        request = VectorQueryRequest("q", top_k=1)
        execution = store.execute((1, 0, 0), _resolve(store, request), request=request)
        assert execution.results[0].id == "a"
        assert execution.receipt.store_id == store.store_id


class TestProperties:
    def test_invalid_identifier_rejected(self) -> None:
        with pytest.raises(ValueError):
            PgVectorProperties(table="bad;table")
        with pytest.raises(ValueError):
            PgVectorProperties(schema="public--x")

    def test_invalid_metric_rejected(self) -> None:
        with pytest.raises(ValueError, match="unsupported PostgreSQL metric"):
            PgVectorProperties(metric="manhattan")

    def test_invalid_index_rejected(self) -> None:
        with pytest.raises(ValueError, match="unsupported PostgreSQL index type"):
            PgVectorProperties(index_type="btree")

    def test_invalid_dimension_rejected(self) -> None:
        with pytest.raises(ValueError):
            PgVectorProperties(dimension=0)

    def test_conninfo_from_parts(self) -> None:
        info = PgVectorProperties(host="db", port=5433, dbname="app", user="u").conninfo()
        assert "host=db" in info
        assert "port=5433" in info
        assert "dbname=app" in info

    def test_dsn_wins_over_parts(self) -> None:
        info = PgVectorProperties(dsn="postgresql://h/x", host="ignored").conninfo()
        assert "host=h" in info
        assert "ignored" not in info

class _WordCountEmbedding:
    """Deterministic test embedding: 3 dims = counts of cat/dog/bird.

    Not a real model — it proves the text→vector→search plumbing against a
    real pgvector backend without needing an external embedding service.
    """

    def embed(self, text: str) -> tuple[float, ...]:
        lowered = text.lower()
        return (
            float(lowered.count("cat")),
            float(lowered.count("dog")),
            float(lowered.count("bird")),
        )

    def dimensions(self) -> int:
        return 3


@pytest.mark.integration
class TestTextSearchAgainstPgVector:
    def _embeddings(self):
        from atlas_richie.vector_core import ModalityAwareEmbeddingService

        return ModalityAwareEmbeddingService(_WordCountEmbedding())

    def _embed(self, embeddings, text):
        from atlas_richie.vector_core import Modality, TextContent

        return embeddings.embed(Modality.TEXT, TextContent(text))

    def test_text_query_finds_semantically_matching_records(self, store_factory) -> None:
        from atlas_richie.vector_core import VectorTextSearch

        store = store_factory(dimension=3, metric="cosine")
        embeddings = self._embeddings()
        for id, text in [("cat-1", "cat cat cat"), ("dog-1", "dog dog"), ("bird-1", "bird")]:
            store.upsert([_record(id, self._embed(embeddings, text), content=text)])
        hits = VectorTextSearch(store, embeddings).search_by_text("cat")
        assert hits, "文本查询必须真的返回命中"
        assert hits[0].id == "cat-1"
        assert hits[0].content == "cat cat cat"

    def test_text_query_with_acl_filter(self, store_factory) -> None:
        from atlas_richie.vector_core import (
            AccessScope,
            SearchOptions,
            VectorTextSearch,
            build_access_filter,
        )

        store = store_factory(dimension=3, metric="cosine")
        embeddings = self._embeddings()
        for id, tenant in [("mine", 1), ("other", 2)]:
            store.upsert([_record(id, self._embed(embeddings, "cat"), tenant=tenant)])
        scope_filter = build_access_filter("kb", AccessScope(tenant_id=1, tenant_admin=True))
        hits = VectorTextSearch(store, embeddings).search_by_text(
            "cat", SearchOptions(rerank=False, filter=scope_filter)
        )
        assert [h.id for h in hits] == ["mine"]

    def test_full_rag_chain_text_query(self, store_factory) -> None:
        """parse → chunk → map → embed → upsert → 文本查询，全链闭环。"""
        from atlas_richie.chunking_parser_adapter import ParserChunkingAdapter, Section
        from atlas_richie.document_parser import BytesSource, ParserRouter
        from atlas_richie.vector_chunk_adapter import ChunkVectorRecordMapper, VectorRecordContext
        from atlas_richie.vector_core import VectorTextSearch

        store = store_factory(dimension=3, metric="cosine")
        embeddings = self._embeddings()
        source = BytesSource("cat cat cat\n\ndog dog\n\nbird".encode(), name="pets.txt")
        mapper = ChunkVectorRecordMapper()
        context = VectorRecordContext(
            index_name="kb", document_id="pets", version=1,
            metadata={"tenantId": 1, "knowledgeBaseId": "kb", "status": "ACTIVE",
                      "visibility": "COMPANY"},
        )
        sections = [
            event.value.result.chunks
            for event in ParserChunkingAdapter().chunk_events(
                ParserRouter().parse(source), file_name="pets.txt"
            )
            if isinstance(event, Section)
        ]
        # map_sections 分配文档级全局 ordinal：逐条 map 会让多 section 的
        # id 全部碰撞（这正是该 API 存在的理由，见 vector-chunk-adapter）。
        records = [
            r.with_vector(self._embed(embeddings, r.content.text))
            for r in mapper.map_sections(sections, context)
        ]
        assert len(records) == 3
        assert len({r.id for r in records}) == 3
        store.upsert(records)
        hits = VectorTextSearch(store, embeddings).search_by_text("cat")
        assert hits[0].content == "cat cat cat"
        assert hits[0].metadata.get("chunkOrdinal") == 0


@pytest.mark.integration
class TestKnowledgeFacadeAgainstPgVector:
    def _setup(self, store_factory):
        from atlas_richie.vector_core import ModalityAwareEmbeddingService

        store = store_factory(dimension=3, metric="cosine")
        embeddings = ModalityAwareEmbeddingService(_WordCountEmbedding())
        return store, embeddings

    def _ingest(self, store, embeddings, docs):
        from atlas_richie.vector_chunk_adapter import ChunkVectorRecordMapper, VectorRecordContext
        from atlas_richie.vector_core import Modality, TextContent

        mapper = ChunkVectorRecordMapper()
        records = []
        for doc_id, chunks in docs.items():
            context = VectorRecordContext(
                index_name="kb", document_id=doc_id, version=1,
                metadata={"tenantId": 1, "knowledgeBaseId": "kb", "status": "ACTIVE",
                          "visibility": "COMPANY"},
            )
            from atlas_richie.chunking_core import Chunk

            section = [Chunk(i, text, 0, len(text)) for i, text in enumerate(chunks)]
            for r in mapper.map_sections([section], context):
                v = embeddings.embed(Modality.TEXT, TextContent(r.content.text))
                records.append(r.with_vector(v))
        store.upsert(records)

    def test_knowledge_search_returns_citations_with_provenance(self, store_factory) -> None:
        from atlas_richie.vector_core import (
            AccessScope,
            KnowledgeBaseVectorService,
            KnowledgeSearchRequest,
        )

        store, embeddings = self._setup(store_factory)
        self._ingest(store, embeddings, {
            "cats": ["cat cat cat", "cat likes fish"],
            "dogs": ["dog dog"],
        })
        service = KnowledgeBaseVectorService(store, embeddings)
        result = service.search("kb", KnowledgeSearchRequest(
            query="cat", top_k=3, access_scope=AccessScope(tenant_id=1, tenant_admin=True),
        ))
        assert result.citations, "知识库检索必须返回引用"
        assert result.citations[0].document_id == "cats"
        assert result.citations[0].chunk_no is not None
        assert result.diagnostics.candidate_count >= 1
        assert result.diagnostics.returned_count == len(result.citations)

    def test_per_document_cap_across_real_results(self, store_factory) -> None:
        from atlas_richie.vector_core import (
            AccessScope,
            KnowledgeBaseVectorService,
            KnowledgeSearchRequest,
        )

        store, embeddings = self._setup(store_factory)
        self._ingest(store, embeddings, {
            "cats": ["cat cat", "cat cat cat", "cat cat cat cat"],
            "dogs": ["dog"],
        })
        service = KnowledgeBaseVectorService(store, embeddings)
        result = service.search("kb", KnowledgeSearchRequest(
            query="cat", top_k=5, max_chunks_per_document=1,
            access_scope=AccessScope(tenant_id=1, tenant_admin=True),
        ))
        cat_citations = [c for c in result.citations if c.document_id == "cats"]
        assert len(cat_citations) == 1, "单文档上限必须生效"

    def test_tenant_isolation_at_the_facade_level(self, store_factory) -> None:
        from atlas_richie.vector_core import (
            AccessScope,
            KnowledgeBaseVectorService,
            KnowledgeSearchRequest,
            Modality,
            TextContent,
        )
        from atlas_richie.vector_chunk_adapter import ChunkVectorRecordMapper, VectorRecordContext
        from atlas_richie.chunking_core import Chunk

        store, embeddings = self._setup(store_factory)
        mapper = ChunkVectorRecordMapper()
        for doc_id, tenant in [("mine", 1), ("theirs", 2)]:
            context = VectorRecordContext(
                index_name="kb", document_id=doc_id, version=1,
                metadata={"tenantId": tenant, "knowledgeBaseId": "kb", "status": "ACTIVE",
                          "visibility": "COMPANY"},
            )
            r = mapper.map(Chunk(0, "cat", 0, 3), context)
            store.upsert([r.with_vector(embeddings.embed(Modality.TEXT, TextContent("cat")))])
        service = KnowledgeBaseVectorService(store, embeddings)
        result = service.search("kb", KnowledgeSearchRequest(
            query="cat", top_k=5, access_scope=AccessScope(tenant_id=1, tenant_admin=True),
        ))
        assert {c.document_id for c in result.citations} == {"mine"}

    def test_mmr_at_the_facade_level(self, store_factory) -> None:
        from atlas_richie.vector_core import (
            AccessScope,
            KnowledgeBaseVectorService,
            KnowledgeSearchRequest,
        )

        store, embeddings = self._setup(store_factory)
        # 三个高度相似的 cat chunk + 一个 dog：MMR 应让 dog 进入前列
        self._ingest(store, embeddings, {
            "cats": ["cat cat cat", "cat cat cat cat", "cat cat cat cat cat"],
            "dogs": ["dog"],
        })
        service = KnowledgeBaseVectorService(store, embeddings)
        # lambda=0.3：三个 cat 向量完全平行（cosine=1），第二轮 cat 得分
        # 0.3-0.7=-0.4，dog 得分 0，多样性胜出。lambda=0.5 时二者平局、
        # 按候选序 cat 先——这正是 MMR 权衡的语义。
        result = service.search("kb", KnowledgeSearchRequest(
            query="cat", top_k=2, mmr=True, mmr_lambda=0.3, max_chunks_per_document=99,
            access_scope=AccessScope(tenant_id=1, tenant_admin=True),
        ))
        ids = [c.document_id for c in result.citations]
        assert "dogs" in ids, "MMR 应提升多样性，让不同文档进入结果"
