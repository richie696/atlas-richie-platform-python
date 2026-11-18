"""知识库检索门面：ACL、引用、单文档截断、MMR 与诊断。"""

from __future__ import annotations

import pytest

from atlas_richie.vector_core import (
    AccessScope,
    ImageContent,
    KnowledgeBaseVectorService,
    KnowledgeSearchRequest,
    Modality,
    ModalityAwareEmbeddingService,
    RetrievalCitation,
    TextContent,
    UnsupportedModalityError,
    VectorCapabilityMismatchError,
    VectorSearchResult,
    eq,
)


class FakeModel:
    def embed(self, text: str) -> tuple[float, ...]:
        return (1.0, 0.0, 0.0)

    def dimensions(self) -> int:
        return 3


class FakeEngine:
    """Records the resolved query and replays canned candidates."""

    def __init__(self, candidates=None, hybrid_capable=False) -> None:
        self.candidates = candidates or []
        self.calls: list[tuple] = []
        self._hybrid = hybrid_capable

    def capabilities(self):
        from atlas_richie.vector_core import VectorCapability, VectorStoreCapabilities

        caps = [VectorCapability.NATIVE_FILTER, VectorCapability.ACL_FILTER]
        if self._hybrid:
            caps.append(VectorCapability.ACL_SAFE_HYBRID)
        return VectorStoreCapabilities.of(*caps)

    def score_semantics(self):
        from atlas_richie.vector_core import VectorScoreSemantics

        return VectorScoreSemantics.final_score("fake", 0.0, 1.0, True, "identity")

    def search(self, vector, resolved):
        self.calls.append((vector, resolved))
        return list(self.candidates)


def _result(id, score=0.9, document_id=None, chunk_no=None, vector=None, content=None):
    metadata = {}
    if document_id is not None:
        metadata["documentId"] = document_id
    if chunk_no is not None:
        metadata["chunkNo"] = chunk_no
    return VectorSearchResult(
        id=id, content=content or f"content-{id}", score=score,
        vector=vector, metadata=metadata,
    )


def _service(candidates=None, **engine_kwargs):
    engine = FakeEngine(candidates, **engine_kwargs)
    embeddings = ModalityAwareEmbeddingService(FakeModel())
    return KnowledgeBaseVectorService(engine, embeddings), engine


def _request(**overrides) -> KnowledgeSearchRequest:
    base = dict(query="cat", top_k=3, access_scope=AccessScope(tenant_id=1, tenant_admin=True))
    base.update(overrides)
    return KnowledgeSearchRequest(**base)


class TestRequestValidation:
    def test_blank_query_rejected(self) -> None:
        with pytest.raises(ValueError, match="query"):
            _request(query="  ")

    def test_non_positive_top_k_rejected(self) -> None:
        with pytest.raises(ValueError, match="topK"):
            _request(top_k=0)

    def test_candidate_k_defaults_to_at_least_50(self) -> None:
        assert _request(top_k=3).candidate_k == 50
        assert _request(top_k=80).candidate_k == 80

    def test_candidate_k_below_top_k_rejected(self) -> None:
        with pytest.raises(ValueError, match="candidateK"):
            _request(top_k=10, candidate_k=5)

    def test_explicit_candidate_k_kept(self) -> None:
        assert _request(candidate_k=20).candidate_k == 20

    def test_none_scope_rejected(self) -> None:
        with pytest.raises(ValueError, match="accessScope"):
            _request(access_scope=None)

    @pytest.mark.parametrize("lambda_", [-0.1, 1.1])
    def test_mmr_lambda_bounds(self, lambda_) -> None:
        with pytest.raises(ValueError, match="mmrLambda"):
            _request(mmr_lambda=lambda_)

    def test_max_chunks_defaults_to_two(self) -> None:
        assert _request().max_chunks_per_document == 2
        assert _request(max_chunks_per_document=5).max_chunks_per_document == 5

    @pytest.mark.parametrize("min_score", [float("nan"), float("inf"), -0.1])
    def test_invalid_min_score_rejected(self, min_score) -> None:
        with pytest.raises(ValueError, match="minScore"):
            _request(min_score=min_score)

    def test_normalized_min_score_above_one_rejected(self) -> None:
        from atlas_richie.vector_core import VectorScoreThresholdKind

        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            _request(min_score=1.5, threshold_kind=VectorScoreThresholdKind.NORMALIZED_RELEVANCE)


class TestAclPushdown:
    def test_acl_filter_reaches_the_engine(self) -> None:
        service, engine = _service([_result("a")])
        service.search("kb-1", _request())
        _, resolved = engine.calls[0]
        assert resolved.filter is not None
        # 必选三段 + tenantAdmin 跳过 visibility
        assert len(resolved.filter.filters) == 3

    def test_additional_filter_is_anded(self) -> None:
        service, engine = _service([_result("a")])
        service.search("kb-1", _request(additional_filter=eq("lang", "zh")))
        _, resolved = engine.calls[0]
        assert resolved.filter.filters[-1] == eq("lang", "zh")

    def test_non_admin_scope_adds_visibility_branch(self) -> None:
        service, engine = _service([_result("a")])
        service.search("kb-1", _request(access_scope=AccessScope(tenant_id=1)))
        _, resolved = engine.calls[0]
        assert len(resolved.filter.filters) == 4

    def test_blank_knowledge_base_id_rejected(self) -> None:
        service, _ = _service()
        with pytest.raises(ValueError, match="knowledgeBaseId"):
            service.search("  ", _request())

    def test_candidate_k_is_the_search_limit(self) -> None:
        service, engine = _service([_result("a")])
        service.search("kb", _request(top_k=2, candidate_k=17))
        _, resolved = engine.calls[0]
        assert resolved.candidate_limit == 17


class TestCitations:
    def test_citations_carry_provenance(self) -> None:
        candidates = [_result("v1", 0.9, document_id="doc-1", chunk_no=3)]
        service, _ = _service(candidates)
        result = service.search("kb", _request())
        citation = result.citations[0]
        assert isinstance(citation, RetrievalCitation)
        assert citation.vector_id == "v1"
        assert citation.document_id == "doc-1"
        assert citation.chunk_no == 3
        assert citation.content == "content-v1"
        assert citation.score == 0.9

    def test_per_document_cap(self) -> None:
        candidates = [
            _result(f"v{i}", 0.9 - i * 0.01, document_id="doc-1") for i in range(5)
        ] + [_result("other", 0.5, document_id="doc-2")]
        service, _ = _service(candidates)
        result = service.search("kb", _request(top_k=5, max_chunks_per_document=2))
        ids = [c.vector_id for c in result.citations]
        assert ids.count("v0") + ids.count("v1") + ids.count("v2") + ids.count("v3") + ids.count("v4") == 2
        assert "other" in ids

    def test_missing_document_id_falls_back_to_vector_id(self) -> None:
        candidates = [_result("v1"), _result("v2")]
        service, _ = _service(candidates)
        result = service.search("kb", _request(top_k=1, max_chunks_per_document=1))
        assert len(result.citations) == 1, "无 documentId 时按向量 id 计数，各自独立"

    def test_top_k_caps_output(self) -> None:
        candidates = [_result(f"v{i}", document_id=f"d{i}") for i in range(10)]
        service, _ = _service(candidates)
        result = service.search("kb", _request(top_k=3))
        assert len(result.citations) == 3

    def test_none_score_becomes_zero(self) -> None:
        service, _ = _service([VectorSearchResult(id="v", content="c", score=None)])
        result = service.search("kb", _request())
        assert result.citations[0].score == 0.0

    def test_non_mapping_metadata_is_tolerated(self) -> None:
        service, _ = _service([VectorSearchResult(id="v", content="c", score=0.5, metadata="junk")])
        result = service.search("kb", _request())
        assert result.citations[0].metadata == {}


class TestMmr:
    def test_mmr_requires_vectors(self) -> None:
        service, _ = _service([_result("a", vector=None)])
        with pytest.raises(VectorCapabilityMismatchError, match="embedding vectors"):
            service.search("kb", _request(mmr=True))

    def test_mmr_prefers_diverse_candidates(self) -> None:
        candidates = [
            _result("a", 0.9, vector=(1.0, 0.0)),
            _result("b", 0.85, vector=(0.99, 0.01)),
            _result("c", 0.8, vector=(0.0, 1.0)),
        ]
        service, _ = _service(candidates)
        result = service.search("kb", _request(top_k=2, mmr=True, max_chunks_per_document=99))
        assert [c.vector_id for c in result.citations] == ["a", "c"]

    def test_mmr_flag_requests_candidate_vectors(self) -> None:
        service, engine = _service([_result("a", vector=(1.0, 0.0))])
        service.search("kb", _request(mmr=True))
        _, resolved = engine.calls[0]
        assert resolved.diversification.include_vectors is True

    def test_lambda_one_is_pure_relevance(self) -> None:
        candidates = [
            _result("a", 0.9, vector=(1.0, 0.0)),
            _result("b", 0.85, vector=(0.99, 0.01)),
        ]
        service, _ = _service(candidates)
        result = service.search("kb", _request(top_k=2, mmr=True, mmr_lambda=1.0, max_chunks_per_document=99))
        assert [c.vector_id for c in result.citations] == ["a", "b"]


class TestHybridAndDiagnostics:
    def test_hybrid_without_capability_raises(self) -> None:
        service, _ = _service([_result("a")])
        with pytest.raises(VectorCapabilityMismatchError, match="hybrid"):
            service.search("kb", _request(hybrid=True))

    def test_hybrid_with_capability_proceeds(self) -> None:
        service, _ = _service([_result("a")], hybrid_capable=True)
        result = service.search("kb", _request(hybrid=True))
        assert result.diagnostics.hybrid is True

    def test_diagnostics_counts_and_timings(self) -> None:
        candidates = [_result(f"v{i}", document_id=f"d{i}") for i in range(5)]
        service, _ = _service(candidates)
        result = service.search("kb", _request(top_k=2))
        diag = result.diagnostics
        assert diag.candidate_count == 5
        assert diag.returned_count == 2
        assert diag.hybrid is False
        assert diag.reranked is False
        assert diag.elapsed >= 0
        assert diag.embedding_elapsed is not None
        assert diag.diversify_elapsed is not None

    def test_empty_candidates(self) -> None:
        service, _ = _service([])
        result = service.search("kb", _request())
        assert result.citations == ()
        assert result.diagnostics.candidate_count == 0