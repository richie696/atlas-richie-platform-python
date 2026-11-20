"""降级策略 SPI 测试（对位 Java `web.core.degrade` 的判定链）。"""

from __future__ import annotations

import json

import pytest

from atlas_richie.web_protection.degrade import (
    ATTR_EXCEPTION,
    ATTR_HIT_STRATEGY,
    ATTR_LATENCY_MS,
    ATTR_MANUAL,
    ATTR_SKIP,
    STRATEGY_NAME_FALLBACK,
    STRATEGY_NAME_ROUTE,
    DegradeConfig,
    DegradeEvaluator,
    DegradeResult,
    DefaultDegradeStrategyRegistry,
    Fallback,
    RouteFallback,
    Trigger,
)
from atlas_richie.web_protection.spi import MutableWebRequestContext

pytestmark = pytest.mark.unit


class _Strategy:
    """最小策略实现（对位 Java `DegradeStrategy` 的一个匿名实现）。"""

    def __init__(self, name: str, order: int, trigger: Trigger, body: str = "stub") -> None:
        self._name = name
        self._order = order
        self._trigger = trigger
        self._body = body
        self.seen: list[dict] = []

    def name(self) -> str:
        return self._name

    def triggers(self) -> frozenset[Trigger]:
        return frozenset({self._trigger})

    def order(self) -> int:
        return self._order

    def matches(self, trigger) -> bool:
        return trigger == self._trigger

    def build(self, trigger, ctx) -> DegradeResult:
        self.seen.append(dict(ctx))
        return DegradeResult.of(200, self._body, self._name)


def _ctx(path: str = "/api/orders") -> MutableWebRequestContext:
    return MutableWebRequestContext(method="GET", path=path)


class TestDegradeResult:
    def test_rejects_status_below_http_range(self) -> None:
        with pytest.raises(ValueError):
            DegradeResult(status=99, body="x", strategy_name="s")

    def test_rejects_status_above_http_range(self) -> None:
        with pytest.raises(ValueError):
            DegradeResult(status=600, body="x", strategy_name="s")

    def test_rejects_none_body(self) -> None:
        with pytest.raises(ValueError):
            DegradeResult(status=200, body=None, strategy_name="s")

    def test_rejects_none_strategy_name(self) -> None:
        with pytest.raises(ValueError):
            DegradeResult(status=200, body="x", strategy_name=None)

    def test_none_headers_becomes_empty(self) -> None:
        assert DegradeResult(status=200, body="x", strategy_name="s").headers == {}

    def test_of_with_headers(self) -> None:
        result = DegradeResult.of_with_headers(503, "b", "s", {"x": "1"})
        assert result.headers == {"x": "1"}


class TestTrigger:
    def test_reason_is_lower_case_with_dashes(self) -> None:
        assert Trigger.EXCEPTION.reason == "exception"
        assert Trigger.HIGH_LATENCY.reason == "high-latency"
        assert Trigger.CUSTOM.reason == "custom"


class TestRegistry:
    def test_selects_lowest_order(self) -> None:
        registry = DefaultDegradeStrategyRegistry()
        registry.register("late", _Strategy("late", 10, Trigger.EXCEPTION))
        registry.register("early", _Strategy("early", 1, Trigger.EXCEPTION))
        selected = registry.select(Trigger.EXCEPTION)
        assert selected is not None and selected.name() == "early"

    def test_ties_broken_by_name(self) -> None:
        registry = DefaultDegradeStrategyRegistry()
        registry.register("b", _Strategy("b", 5, Trigger.EXCEPTION))
        registry.register("a", _Strategy("a", 5, Trigger.EXCEPTION))
        selected = registry.select(Trigger.EXCEPTION)
        assert selected is not None and selected.name() == "a"

    def test_register_same_name_overwrites(self) -> None:
        registry = DefaultDegradeStrategyRegistry()
        registry.register("x", _Strategy("x", 1, Trigger.EXCEPTION))
        registry.register("x", _Strategy("x", 2, Trigger.CUSTOM))
        assert len(registry.all()) == 1
        assert registry.select(Trigger.CUSTOM) is not None

    def test_unregister_removes(self) -> None:
        registry = DefaultDegradeStrategyRegistry()
        registry.register("x", _Strategy("x", 1, Trigger.EXCEPTION))
        registry.unregister("x")
        assert registry.select(Trigger.EXCEPTION) is None
        assert registry.all() == []

    def test_blank_name_rejected(self) -> None:
        registry = DefaultDegradeStrategyRegistry()
        with pytest.raises(ValueError):
            registry.register("  ", _Strategy("x", 1, Trigger.EXCEPTION))

    def test_none_strategy_rejected(self) -> None:
        registry = DefaultDegradeStrategyRegistry()
        with pytest.raises(ValueError):
            registry.register("x", None)


class TestTriggerDetection:
    def test_manual_wins_over_exception(self) -> None:
        """Java 的 detectTrigger 先看 manual，再看 exception。"""
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry())
        ctx = _ctx()
        ctx.set_attribute(ATTR_MANUAL, True)
        ctx.set_attribute(ATTR_EXCEPTION, RuntimeError("boom"))
        assert evaluator.detect_trigger(ctx) is Trigger.CUSTOM

    def test_exception_detected(self) -> None:
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry())
        ctx = _ctx()
        ctx.set_attribute(ATTR_EXCEPTION, RuntimeError("boom"))
        assert evaluator.detect_trigger(ctx) is Trigger.EXCEPTION

    def test_latency_above_threshold(self) -> None:
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry(), latency_threshold_ms=100)
        ctx = _ctx()
        ctx.set_attribute(ATTR_LATENCY_MS, 101)
        assert evaluator.detect_trigger(ctx) is Trigger.HIGH_LATENCY

    def test_latency_equal_threshold_does_not_trigger(self) -> None:
        """Java 是 `ms > threshold`，等于不触发。"""
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry(), latency_threshold_ms=100)
        ctx = _ctx()
        ctx.set_attribute(ATTR_LATENCY_MS, 100)
        assert evaluator.detect_trigger(ctx) is None

    def test_no_trigger(self) -> None:
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry())
        assert evaluator.detect_trigger(_ctx()) is None

    def test_boolean_latency_is_not_a_number(self) -> None:
        """Java 的 `instanceof Number` 不含 Boolean；Python 的 bool 是 int 子类。"""
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry(), latency_threshold_ms=1)
        ctx = _ctx()
        ctx.set_attribute(ATTR_LATENCY_MS, True)
        assert evaluator.detect_trigger(ctx) is None


class TestEvaluate:
    def _evaluator(self, **kwargs) -> DegradeEvaluator:
        config = DegradeConfig(
            routes={"/api/orders": RouteFallback(pattern="/api/orders")},
            fallback=Fallback(),
        )
        return DegradeEvaluator(DefaultDegradeStrategyRegistry(), config, **kwargs)

    def test_skip_attribute_disables_degrade(self) -> None:
        evaluator = self._evaluator()
        ctx = _ctx()
        ctx.set_attribute(ATTR_SKIP, True)
        ctx.set_attribute(ATTR_EXCEPTION, RuntimeError("boom"))
        assert evaluator.evaluate(ctx) is None
        assert not ctx.is_short_circuited

    def test_unmatched_route_does_not_degrade(self) -> None:
        """Java 的降级是「受保护接口」的业务策略：没配路由就不降级。"""
        evaluator = self._evaluator()
        ctx = _ctx("/api/other")
        ctx.set_attribute(ATTR_EXCEPTION, RuntimeError("boom"))
        assert evaluator.evaluate(ctx) is None

    def test_require_route_match_disabled_uses_global_fallback(self) -> None:
        evaluator = self._evaluator(require_route_match=False)
        ctx = _ctx("/api/other")
        ctx.set_attribute(ATTR_EXCEPTION, RuntimeError("boom"))
        result = evaluator.evaluate(ctx)
        assert result is not None
        assert ctx.attribute(ATTR_HIT_STRATEGY) == STRATEGY_NAME_FALLBACK

    def test_route_hit_uses_route_config(self) -> None:
        evaluator = self._evaluator()
        ctx = _ctx()
        ctx.set_attribute(ATTR_EXCEPTION, RuntimeError("boom"))
        result = evaluator.evaluate(ctx)
        assert result is not None
        assert ctx.attribute(ATTR_HIT_STRATEGY) == STRATEGY_NAME_ROUTE
        assert result.status == 503
        assert ctx.is_short_circuited
        assert ctx.short_circuit_body == result.body

    def test_strategy_hit_wins_over_route_config(self) -> None:
        registry = DefaultDegradeStrategyRegistry()
        registry.register("stub", _Strategy("stub", 0, Trigger.EXCEPTION, body="cached"))
        config = DegradeConfig(routes={"/api/orders": RouteFallback(pattern="/api/orders")})
        evaluator = DegradeEvaluator(registry, config)
        ctx = _ctx()
        ctx.set_attribute(ATTR_EXCEPTION, RuntimeError("boom"))
        result = evaluator.evaluate(ctx)
        assert result is not None
        assert result.body == "cached"
        assert ctx.attribute(ATTR_HIT_STRATEGY) == "stub"

    def test_strategy_receives_ctx_snapshot(self) -> None:
        strategy = _Strategy("stub", 0, Trigger.EXCEPTION)
        registry = DefaultDegradeStrategyRegistry()
        registry.register("stub", strategy)
        config = DegradeConfig(routes={"/api/orders": RouteFallback(pattern="/api/orders")})
        evaluator = DegradeEvaluator(registry, config)
        ctx = _ctx()
        ctx.set_attribute(ATTR_EXCEPTION, RuntimeError("boom"))
        ctx.set_attribute(ATTR_LATENCY_MS, 42)
        evaluator.evaluate(ctx)
        snapshot = strategy.seen[0]
        assert snapshot["path"] == "/api/orders"
        assert snapshot["latencyMs"] == 42
        assert snapshot["trigger"] is Trigger.EXCEPTION
        assert "RuntimeError" in snapshot["exceptionType"]
        assert snapshot["exceptionMessage"] == "boom"

    def test_body_shape_matches_api_result(self) -> None:
        """body 形状与 Java 的 `ApiResult.error(code, msg).toJson()` 一致。"""
        evaluator = self._evaluator()
        ctx = _ctx()
        ctx.set_attribute(ATTR_EXCEPTION, RuntimeError("boom"))
        result = evaluator.evaluate(ctx)
        assert result is not None
        payload = json.loads(result.body)
        assert payload == {
            "success": False,
            "code": "DEGRADED",
            "msg": "服务降级中 (exception)",
        }

    def test_reason_placeholder_substituted(self) -> None:
        evaluator = self._evaluator()
        ctx = _ctx()
        ctx.set_attribute(ATTR_MANUAL, True)
        result = evaluator.evaluate(ctx)
        assert result is not None
        assert json.loads(result.body)["msg"] == "服务降级中 (custom)"

    def test_headers_are_applied_to_context(self) -> None:
        config = DegradeConfig(
            routes={
                "/api/orders": RouteFallback(
                    pattern="/api/orders", headers={"x-degraded": "1"}
                )
            }
        )
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry(), config)
        ctx = _ctx()
        ctx.set_attribute(ATTR_EXCEPTION, RuntimeError("boom"))
        evaluator.evaluate(ctx)
        assert ctx.response_headers()["x-degraded"] == "1"

    def test_no_trigger_means_no_degrade(self) -> None:
        evaluator = self._evaluator()
        ctx = _ctx()
        assert evaluator.evaluate(ctx) is None
        assert not ctx.is_short_circuited


class TestRouteMatching:
    def test_exact_match_beats_ant(self) -> None:
        config = DegradeConfig(
            routes={
                "/api/orders": RouteFallback(pattern="/api/orders", status=500),
                "/api/**": RouteFallback(pattern="/api/**", status=503),
            }
        )
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry(), config)
        assert evaluator.match_route("/api/orders").status == 500

    def test_ant_match(self) -> None:
        config = DegradeConfig(routes={"/api/**": RouteFallback(pattern="/api/**")})
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry(), config)
        assert evaluator.match_route("/api/orders/1") is not None

    def test_double_star_matches_zero_segment(self) -> None:
        """Java 的 `AntPathMatcher` 里 `/api/**` 能匹配 `/api`。"""
        config = DegradeConfig(routes={"/api/**": RouteFallback(pattern="/api/**")})
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry(), config)
        assert evaluator.match_route("/api") is not None

    def test_route_rules_take_priority_over_routes(self) -> None:
        config = DegradeConfig(
            routes={"/api/orders": RouteFallback(pattern="/api/orders", status=500)},
            route_rules=(RouteFallback(pattern="/api/orders", status=418),),
        )
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry(), config)
        assert evaluator.match_route("/api/orders").status == 418

    def test_route_rules_exact_before_ant(self) -> None:
        config = DegradeConfig(
            route_rules=(
                RouteFallback(pattern="/api/**", status=503),
                RouteFallback(pattern="/api/orders", status=500),
            )
        )
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry(), config)
        assert evaluator.match_route("/api/orders").status == 500

    def test_no_match(self) -> None:
        evaluator = DegradeEvaluator(DefaultDegradeStrategyRegistry())
        assert evaluator.match_route("/api/orders") is None
        assert evaluator.match_route("") is None
        assert evaluator.match_route(None) is None
