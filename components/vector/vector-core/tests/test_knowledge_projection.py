"""检索门面的投影版本收敛：过滤下推、空集短路、异常传播。"""

from __future__ import annotations

import pytest

from atlas_richie.vector_core import (
    AccessScope,
    In,
    KnowledgeBaseVectorService,
    KnowledgeSearchRequest,
    ModalityAwareEmbeddingService,
    PROJECTION_VERSION_FIELD,
)


class FakeModel:
    def embed(self, text: str) -> tuple[float, ...]:
        return (1.0, 0.0, 0.0)

    def dimensions(self) -> int:
        return 3


class FakeEngine:
    """记录下推给 provider 的 filter。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def capabilities(self):
        from atlas_richie.vector_core import VectorCapability, VectorStoreCapabilities

        return VectorStoreCapabilities.of(
            VectorCapability.NATIVE_FILTER, VectorCapability.ACL_FILTER
        )

    def score_semantics(self):
        from atlas_richie.vector_core import VectorScoreSemantics

        return VectorScoreSemantics.final_score("fake", 0.0, 1.0, True, "identity")

    def search(self, vector, resolved):
        self.calls.append((vector, resolved))
        return []


class FakeResolver:
    """返回固定版本集合的 resolver。"""

    def __init__(self, versions: frozenset[str]) -> None:
        self.versions = versions
        self.calls: list[tuple[int, str]] = []

    def active_version_ids(self, tenant_id: int, knowledge_base_id: str) -> frozenset[str]:
        self.calls.append((tenant_id, knowledge_base_id))
        return self.versions


class ExplodingResolver:
    def active_version_ids(self, tenant_id: int, knowledge_base_id: str) -> frozenset[str]:
        raise RuntimeError("projection store unavailable")


def _service(resolver=None):
    engine = FakeEngine()
    embeddings = ModalityAwareEmbeddingService(FakeModel())
    service = KnowledgeBaseVectorService(
        engine, embeddings, projection_versions=resolver
    )
    return service, engine


def _request(**overrides) -> KnowledgeSearchRequest:
    base = dict(
        query="cat",
        top_k=3,
        access_scope=AccessScope(tenant_id=7, tenant_admin=True),
    )
    base.update(overrides)
    return KnowledgeSearchRequest(**base)


class TestProjectionVersionFilter:
    def test_active_versions_are_pushed_down(self) -> None:
        resolver = FakeResolver(frozenset({"v1", "v2"}))
        service, engine = _service(resolver)
        service.search("kb-1", _request())
        _, resolved = engine.calls[0]
        projection_filter = resolved.filter.filters[-1]
        assert isinstance(projection_filter, In)
        assert projection_filter.field == PROJECTION_VERSION_FIELD
        assert projection_filter.values == ("v1", "v2")

    def test_resolver_receives_tenant_and_knowledge_base(self) -> None:
        resolver = FakeResolver(frozenset({"v1"}))
        service, _ = _service(resolver)
        service.search("kb-42", _request())
        assert resolver.calls == [(7, "kb-42")]

    def test_without_resolver_no_version_filter(self) -> None:
        service, engine = _service(None)
        service.search("kb-1", _request())
        _, resolved = engine.calls[0]
        assert all(
            not (
                isinstance(child, In) and child.field == PROJECTION_VERSION_FIELD
            )
            for child in resolved.filter.filters
        )

    def test_version_filter_is_anded_after_acl(self) -> None:
        resolver = FakeResolver(frozenset({"v1"}))
        service, engine = _service(resolver)
        service.search("kb-1", _request())
        _, resolved = engine.calls[0]
        # 顶层 And = (ACL 子树, 版本 In)
        assert len(resolved.filter.filters) == 2
        assert isinstance(resolved.filter.filters[1], In)


class TestEmptyActiveSet:
    def test_empty_set_short_circuits_without_calling_provider(self) -> None:
        resolver = FakeResolver(frozenset())
        service, engine = _service(resolver)
        result = service.search("kb-1", _request())
        assert engine.calls == []
        assert result.citations == ()
        assert result.diagnostics.candidate_count == 0
        assert result.diagnostics.returned_count == 0

    def test_empty_set_still_reports_hybrid_intent(self) -> None:
        resolver = FakeResolver(frozenset())
        service, _ = _service(resolver)
        result = service.search("kb-1", _request(hybrid=True))
        assert result.diagnostics.hybrid is True
        assert result.diagnostics.elapsed >= 0


class TestResolverFailure:
    def test_resolver_error_propagates(self) -> None:
        service, engine = _service(ExplodingResolver())
        with pytest.raises(RuntimeError, match="projection store unavailable"):
            service.search("kb-1", _request())
        assert engine.calls == [], "解析失败不得退化成全量召回"
