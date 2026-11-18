"""嵌入 SPI、模态路由与文本查询入口。"""

from __future__ import annotations

import base64

import pytest

from atlas_richie.vector_core import (
    EmbeddingModel,
    ImageContent,
    Modality,
    ModalityAwareEmbeddingService,
    RerankNotConfiguredError,
    SearchOptions,
    TextContent,
    UnsupportedModalityError,
    VectorQueryResolver,
    VectorSearchResult,
    VectorTextSearch,
    eq,
)


class FakeModel:
    def __init__(self, dims: int = 3, marker: float = 1.0) -> None:
        self._dims = dims
        self._marker = marker
        self.calls: list[str] = []

    def embed(self, text: str) -> tuple[float, ...]:
        self.calls.append(text)
        return (self._marker,) + (0.0,) * (self._dims - 1)

    def dimensions(self) -> int:
        return self._dims


class FakeEngine:
    def __init__(self, results=None) -> None:
        self.results = results or []
        self.calls: list[tuple] = []
        self._semantics = None

    def score_semantics(self):
        from atlas_richie.vector_core import VectorScoreSemantics

        return VectorScoreSemantics.final_score("fake", 0.0, 1.0, True, "identity")

    def search(self, vector, resolved):
        self.calls.append((vector, resolved))
        return list(self.results)


def _service(**kwargs) -> ModalityAwareEmbeddingService:
    return ModalityAwareEmbeddingService(FakeModel(), **kwargs)


class TestModalityRouting:
    def test_text_model_is_required(self) -> None:
        with pytest.raises(ValueError, match="baseline"):
            ModalityAwareEmbeddingService(None)

    def test_text_embeds_via_text_model(self) -> None:
        model = FakeModel()
        service = ModalityAwareEmbeddingService(model)
        assert service.embed(Modality.TEXT, TextContent("hello")) == (1.0, 0.0, 0.0)
        assert model.calls == ["hello"]

    def test_image_requires_image_model(self) -> None:
        service = _service()
        with pytest.raises(UnsupportedModalityError, match="not configured"):
            service.embed(Modality.IMAGE, ImageContent(b"\x89PNG", "image/png"))

    def test_image_embeds_data_url(self) -> None:
        image_model = FakeModel(marker=2.0)
        service = ModalityAwareEmbeddingService(FakeModel(), image_model)
        data = b"\x89PNG\r\n"
        result = service.embed(Modality.IMAGE, ImageContent(data, "image/png"))
        assert result == (2.0, 0.0, 0.0)
        expected = "data:image/png;base64," + base64.b64encode(data).decode()
        assert image_model.calls == [expected]

    def test_wrong_content_type_for_text_rejected(self) -> None:
        with pytest.raises(ValueError, match="TextContent"):
            _service().embed(Modality.TEXT, ImageContent(b"x", "image/png"))

    def test_wrong_content_type_for_image_rejected(self) -> None:
        service = ModalityAwareEmbeddingService(FakeModel(), FakeModel())
        with pytest.raises(ValueError, match="ImageContent"):
            service.embed(Modality.IMAGE, TextContent("not an image"))

    def test_none_content_rejected(self) -> None:
        with pytest.raises(ValueError):
            _service().embed(Modality.TEXT, None)

    def test_supports_modality(self) -> None:
        service = _service()
        assert service.supports_modality(Modality.TEXT) is True
        assert service.supports_modality(Modality.IMAGE) is False
        assert service.supports_modality(None) is False
        service.set_image_model(FakeModel())
        assert service.supports_modality(Modality.IMAGE) is True

    def test_dimension_for(self) -> None:
        service = ModalityAwareEmbeddingService(FakeModel(dims=5))
        assert service.dimension_for(Modality.TEXT) == 5
        assert service.dimension_for(Modality.IMAGE) == 0
        assert service.dimension_for(None) == 0
        service.set_image_model(FakeModel(dims=7))
        assert service.dimension_for(Modality.IMAGE) == 7

    def test_set_text_model_rejects_none(self) -> None:
        with pytest.raises(ValueError):
            _service().set_text_model(None)

    def test_set_image_model_can_clear(self) -> None:
        service = ModalityAwareEmbeddingService(FakeModel(), FakeModel())
        service.set_image_model(None)
        assert service.supports_modality(Modality.IMAGE) is False

    def test_satisfies_embedding_protocol(self) -> None:
        assert isinstance(FakeModel(), EmbeddingModel)


class TestTextSearch:
    def _search(self, results=None, **kwargs):
        engine = FakeEngine(results)
        service = VectorTextSearch(engine, _service(), **kwargs)
        return service, engine

    def test_query_is_embedded_then_searched(self) -> None:
        results = [VectorSearchResult.of("a", "A", 0.9)]
        service, engine = self._search(results)
        out = service.search_by_text("hello")
        assert out == results
        vector, resolved = engine.calls[0]
        assert vector == (1.0, 0.0, 0.0)
        assert resolved.query == "hello"

    def test_options_map_to_request(self) -> None:
        service, engine = self._search()
        options = SearchOptions(
            rerank=False, limit=5, min_score=0.2, filter=eq("tenantId", 7),
            include_candidate_vectors=True,
        )
        service.search_by_text("q", options)
        _, resolved = engine.calls[0]
        assert resolved.top_k == 5
        assert resolved.min_score == 0.2
        assert resolved.filter == eq("tenantId", 7)
        assert resolved.diversification.include_vectors is True

    def test_default_options_do_not_request_rerank(self) -> None:
        service, _ = self._search()
        service.search_by_text("q")  # 不应抛 RerankNotConfiguredError

    def test_explicit_rerank_without_reranker_raises(self) -> None:
        service, _ = self._search()
        with pytest.raises(RerankNotConfiguredError, match="reranker"):
            service.search_by_text("q", SearchOptions(rerank=True))

    def test_injected_reranker_is_used(self) -> None:
        class _Reverser:
            def rerank(self, query, candidates):
                return list(reversed(candidates))

        results = [VectorSearchResult.of("a", "A", 0.9), VectorSearchResult.of("b", "B", 0.8)]
        engine = FakeEngine(results)
        service = VectorTextSearch(engine, _service(), reranker=_Reverser())
        out = service.search_by_text("q", SearchOptions(rerank=True))
        assert [r.id for r in out] == ["b", "a"]

    def test_image_search_uses_image_model(self) -> None:
        image_model = FakeModel(marker=3.0)
        engine = FakeEngine()
        embeddings = ModalityAwareEmbeddingService(FakeModel(), image_model)
        service = VectorTextSearch(engine, embeddings)
        service.search_by_image(ImageContent(b"img", "image/png"))
        vector, resolved = engine.calls[0]
        assert vector == (3.0, 0.0, 0.0)
        assert resolved.query == "[image]"

    def test_image_search_without_image_model_raises(self) -> None:
        service = VectorTextSearch(FakeEngine(), _service())
        with pytest.raises(UnsupportedModalityError):
            service.search_by_image(ImageContent(b"img", "image/png"))

    def test_resolver_defaults_from_engine_semantics(self) -> None:
        engine = FakeEngine()
        service = VectorTextSearch(engine, _service())
        service.search_by_text("q", SearchOptions(rerank=False, min_score=0.5))
        _, resolved = engine.calls[0]
        assert resolved.min_score == 0.5

    def test_custom_resolver_is_respected(self) -> None:
        from atlas_richie.vector_core import VectorQueryDefaults

        engine = FakeEngine()
        resolver = VectorQueryResolver(store_defaults=VectorQueryDefaults(top_k=3))
        service = VectorTextSearch(engine, _service(), resolver=resolver)
        service.search_by_text("q")
        _, resolved = engine.calls[0]
        assert resolved.top_k == 3

    def test_blank_query_rejected(self) -> None:
        service, _ = self._search()
        with pytest.raises(ValueError):
            service.search_by_text("   ")