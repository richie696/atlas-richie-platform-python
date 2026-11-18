"""ACL 安全混合检索兜底与 RRF 融合。

数值行为已对 Java AclSafeHybridSearchFallback 做过 660 条随机用例差分
（排序与分数至 1e-12 一致）；这里补齐差分未覆盖的 native_first 分支与契约。
"""

from __future__ import annotations

import math

import pytest

from atlas_richie.vector_core import (
    RRF_K,
    CheckedSearch,
    HybridSearchOptions,
    VectorSearchResult,
    fuse,
    native_first,
)


def _r(id: str, score: float = 1.0) -> VectorSearchResult:
    return VectorSearchResult.of(id, f"content-{id}", score)


class TestFusion:
    def test_overlap_outranks_single_source_hits(self) -> None:
        dense = [_r("a", 0.9), _r("b", 0.8)]
        sparse = [_r("b", 5.0), _r("c", 4.0)]
        out = fuse(dense, sparse, None, 3)
        assert [r.id for r in out] == ["b", "a", "c"]

    def test_scores_match_the_rrf_formula(self) -> None:
        out = fuse([_r("a"), _r("b")], [_r("b"), _r("c")], None, 3)
        by_id = {r.id: r.score for r in out}
        assert by_id["a"] == pytest.approx(0.7 / (RRF_K + 1))
        assert by_id["b"] == pytest.approx(0.7 / (RRF_K + 2) + 0.3 / (RRF_K + 1))
        assert by_id["c"] == pytest.approx(0.3 / (RRF_K + 2))

    def test_raw_scores_do_not_leak_into_fused_score(self) -> None:
        """RRF 用排名而非原始分数，避免跨量纲比较。"""
        out = fuse([_r("a", 0.001)], [_r("a", 9999.0)], None, 1)
        assert out[0].score == pytest.approx(0.7 / 61 + 0.3 / 61)
        assert out[0].score < 1.0

    def test_zero_weight_skips_a_source_entirely(self) -> None:
        options = HybridSearchOptions(vector_weight=1.0, keyword_weight=0.0)
        out = fuse([_r("a")], [_r("b")], options, 5)
        assert [r.id for r in out] == ["a"]

    def test_zero_dense_weight_keeps_only_sparse(self) -> None:
        options = HybridSearchOptions(vector_weight=0.0, keyword_weight=1.0)
        out = fuse([_r("a")], [_r("b")], options, 5)
        assert [r.id for r in out] == ["b"]

    def test_blank_and_null_ids_are_skipped_without_consuming_rank(self) -> None:
        dense = [None, _r("  "), _r(None), _r("a")]
        out = fuse(dense, [], None, 5)
        assert [r.id for r in out] == ["a"]
        assert out[0].score == pytest.approx(0.7 / (RRF_K + 1)), "被跳过的条目不得占用排名"

    def test_limit_truncates(self) -> None:
        out = fuse([_r("a"), _r("b"), _r("c")], [], None, 2)
        assert len(out) == 2

    @pytest.mark.parametrize("limit", [0, -1, -100])
    def test_invalid_limit_rejected(self, limit: int) -> None:
        with pytest.raises(ValueError, match="greater than zero"):
            fuse([], [], None, limit)

    def test_empty_inputs(self) -> None:
        assert fuse([], [], None, 5) == []
        assert fuse(None, None, None, 5) == []

    def test_ties_break_on_id_ascending(self) -> None:
        out = fuse([_r("z"), _r("a")], [], None, 2)
        assert [r.id for r in out] == ["z", "a"], "同排名时按分数降序、id 升序"
        tied = fuse([_r("z")], [_r("a")], HybridSearchOptions(0.5, 0.5), 2)
        assert [r.id for r in tied] == ["a", "z"]

    def test_inputs_are_not_mutated(self) -> None:
        dense = [_r("a", 0.9)]
        sparse = [_r("a", 5.0)]
        fuse(dense, sparse, None, 1)
        assert dense[0].score == 0.9
        assert sparse[0].score == 5.0

    def test_other_fields_are_preserved(self) -> None:
        source = VectorSearchResult(
            id="a", content="A", score=0.5, type="chunk", tags=("t",),
            source="doc", namespace="ns", status="ACTIVE", metadata={"k": "v"},
        )
        out = fuse([source], [], None, 1)
        assert out[0].content == "A"
        assert out[0].tags == ("t",)
        assert out[0].metadata == {"k": "v"}
        assert out[0].namespace == "ns"

    def test_first_occurrence_supplies_the_payload(self) -> None:
        out = fuse(
            [VectorSearchResult.of("a", "from-dense", 0.9)],
            [VectorSearchResult.of("a", "from-sparse", 5.0)],
            None, 1,
        )
        assert out[0].content == "from-dense"


class TestWeights:
    def test_defaults_when_options_absent(self) -> None:
        out = fuse([_r("a")], [], None, 1)
        assert out[0].score == pytest.approx(0.7 / 61)

    @pytest.mark.parametrize(
        ("dense", "sparse"),
        [(0.5, 0.4), (0.5, 0.6), (-0.1, 1.1), (1.1, -0.1), (2.0, -1.0)],
    )
    def test_weights_must_sum_to_one_within_range(self, dense: float, sparse: float) -> None:
        with pytest.raises(ValueError, match="sum to 1"):
            fuse([], [], HybridSearchOptions(dense, sparse), 5)

    @pytest.mark.parametrize("value", [float("nan"), float("inf")])
    def test_non_finite_weights_rejected(self, value: float) -> None:
        with pytest.raises(ValueError):
            fuse([], [], HybridSearchOptions(value, 0.5), 5)

    def test_tolerance_allows_floating_point_sum(self) -> None:
        options = HybridSearchOptions(vector_weight=0.1, keyword_weight=0.9)
        assert fuse([_r("a")], [], options, 1)


class _Search:
    def __init__(self, results=None, error: Exception | None = None) -> None:
        self._results = results or []
        self._error = error
        self.calls = 0

    def search(self):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._results


class TestNativeFirst:
    def test_satisfies_checked_search_protocol(self) -> None:
        assert isinstance(_Search(), CheckedSearch)

    def test_native_success_short_circuits(self) -> None:
        native = _Search([_r("a"), _r("b"), _r("c")])
        dense, sparse = _Search([_r("x")]), _Search([_r("y")])
        out = native_first(native, dense, sparse, None, 2, lambda e: True)
        assert [r.id for r in out] == ["a", "b"]
        assert dense.calls == 0 and sparse.calls == 0, "原生成功不得触发兜底"

    def test_native_results_are_copied_and_null_filtered(self) -> None:
        native = _Search([None, _r("a"), _r("b")])
        out = native_first(native, _Search(), _Search(), None, 5, lambda e: True)
        assert [r.id for r in out] == ["a", "b"]

    def test_allowed_failure_falls_back_to_fusion(self) -> None:
        native = _Search(error=RuntimeError("native hybrid unsupported"))
        dense, sparse = _Search([_r("a")]), _Search([_r("b")])
        out = native_first(native, dense, sparse, None, 5, lambda e: True)
        assert {r.id for r in out} == {"a", "b"}
        assert dense.calls == 1 and sparse.calls == 1

    def test_disallowed_failure_is_rethrown_unchanged(self) -> None:
        """ACL 拒绝一类错误必须原样抛出，不能被兜底绕过。"""
        error = PermissionError("acl denied")
        native = _Search(error=error)
        dense, sparse = _Search([_r("a")]), _Search([_r("b")])
        with pytest.raises(PermissionError) as info:
            native_first(native, dense, sparse, None, 5, lambda e: False)
        assert info.value is error
        assert dense.calls == 0 and sparse.calls == 0

    def test_predicate_inspects_the_exception_type(self) -> None:
        native = _Search(error=NotImplementedError("no native hybrid"))
        out = native_first(
            native, _Search([_r("a")]), _Search(), None, 5,
            lambda e: isinstance(e, NotImplementedError),
        )
        assert [r.id for r in out] == ["a"]

    def test_native_empty_result_is_not_a_failure(self) -> None:
        out = native_first(_Search([]), _Search([_r("a")]), _Search(), None, 5, lambda e: True)
        assert out == [], "空结果是合法命中，不应触发兜底"

    @pytest.mark.parametrize("limit", [0, -1])
    def test_invalid_limit_rejected_on_native_path(self, limit: int) -> None:
        with pytest.raises(ValueError, match="greater than zero"):
            native_first(_Search([_r("a")]), _Search(), _Search(), None, limit, lambda e: True)

    def test_none_search_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not be None"):
            native_first(None, _Search(), _Search(), None, 5, lambda e: True)

    def test_none_predicate_rejected(self) -> None:
        with pytest.raises(ValueError, match="fallback_allowed"):
            native_first(_Search(), _Search(), _Search(), None, 5, None)

    def test_fused_scores_are_finite(self) -> None:
        out = native_first(
            _Search(error=RuntimeError("x")), _Search([_r("a")]), _Search([_r("a")]),
            None, 5, lambda e: True,
        )
        assert all(math.isfinite(r.score) for r in out)