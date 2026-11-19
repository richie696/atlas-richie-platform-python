"""SPI 契约层测试：请求上下文、拦截器链、决策事件（对位 Java web-core 的 A-1 单测）。"""

from __future__ import annotations

import pytest

from atlas_richie.web_protection.guards import RequestSizeGuard
from atlas_richie.web_protection.spi import (
    CLIENT_IP_ATTRIBUTE,
    DECISION_ATTRIBUTE,
    GATEWAY_BYPASS_ATTRIBUTE,
    GATEWAY_ID_ATTRIBUTE,
    LOGIN_KEY_ATTRIBUTE,
    LONG_LIVED_ATTRIBUTE,
    DefaultWebInterceptorChain,
    MutableWebRequestContext,
    WebDecisionSink,
    WebFilterDecision,
    WebInterceptor,
    WebInterceptorChain,
    WebRequestContext,
)

pytestmark = pytest.mark.unit


class _Recorder:
    """记录执行顺序的拦截器。"""

    def __init__(self, name: str, calls: list[str], *, stop: bool = False) -> None:
        self._name = name
        self._calls = calls
        self._stop = stop

    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        self._calls.append(self._name)
        if not self._stop:
            chain.proceed(ctx)


class _Sink:
    def __init__(self) -> None:
        self.decisions: list[WebFilterDecision] = []

    def publish(self, decision: WebFilterDecision) -> None:
        self.decisions.append(decision)


class TestAttributeConstants:
    def test_values_match_java_contract(self) -> None:
        assert DECISION_ATTRIBUTE == "platform.web.filter-decision"
        assert GATEWAY_BYPASS_ATTRIBUTE == "platform.web.gateway-bypass"
        assert GATEWAY_ID_ATTRIBUTE == "platform.web.gateway-id"
        assert LONG_LIVED_ATTRIBUTE == "platform.web.long-lived"

    def test_python_only_attributes_are_namespaced(self) -> None:
        assert CLIENT_IP_ATTRIBUTE.startswith("platform.web.")
        assert LOGIN_KEY_ATTRIBUTE.startswith("platform.web.")
        assert CLIENT_IP_ATTRIBUTE != LOGIN_KEY_ATTRIBUTE


class TestMutableWebRequestContext:
    def test_method_is_upper_cased(self) -> None:
        assert MutableWebRequestContext("get", "/a").method == "GET"

    def test_path_is_kept_as_is(self) -> None:
        assert MutableWebRequestContext("GET", "/api/v1/users/123").path == "/api/v1/users/123"

    def test_none_method_or_path_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            MutableWebRequestContext(None, "/a")
        with pytest.raises(ValueError):
            MutableWebRequestContext("GET", None)

    def test_header_lookup_is_case_insensitive(self) -> None:
        ctx = MutableWebRequestContext("GET", "/", {"X-Trace": ["abc"]})
        assert ctx.header("x-trace") == "abc"
        assert ctx.header("X-TRACE") == "abc"

    def test_header_returns_first_value(self) -> None:
        ctx = MutableWebRequestContext("GET", "/", {"x-a": ["first", "second"]})
        assert ctx.header("x-a") == "first"
        assert ctx.headers("x-a") == ["first", "second"]

    def test_missing_header_returns_none_and_empty_list(self) -> None:
        ctx = MutableWebRequestContext("GET", "/")
        assert ctx.header("x-none") is None
        assert ctx.headers("x-none") == []

    def test_single_string_header_value_is_not_split_into_characters(self) -> None:
        """str 本身是 Iterable[str]，直接 tuple() 会把 "edge-1" 拆成字符 —— 必须按单值处理。"""
        ctx = MutableWebRequestContext("GET", "/", {"x-a": "edge-1"})
        assert ctx.header("x-a") == "edge-1"
        assert ctx.headers("x-a") == ["edge-1"]

    def test_header_names_are_lowercase(self) -> None:
        ctx = MutableWebRequestContext("GET", "/", {"X-A": ["1"], "X-B": ["2"]})
        assert sorted(ctx.header_names()) == ["x-a", "x-b"]

    def test_headers_are_copied_defensively(self) -> None:
        source = {"x-a": ["1"]}
        ctx = MutableWebRequestContext("GET", "/", source)
        source["x-a"].append("2")
        source["x-b"] = ["3"]
        assert ctx.headers("x-a") == ["1"]
        assert ctx.header_names() == ["x-a"]

    def test_query_params(self) -> None:
        ctx = MutableWebRequestContext("GET", "/", query_params={"page": ["2", "3"]})
        assert ctx.query_param("page") == "2"
        assert ctx.query_params() == {"page": ["2", "3"]}
        assert ctx.query_param("missing") is None

    def test_path_variables(self) -> None:
        ctx = MutableWebRequestContext("GET", "/", path_variables={"id": "7"})
        assert ctx.path_variables() == {"id": "7"}

    def test_attribute_roundtrip_returns_old_value(self) -> None:
        ctx = MutableWebRequestContext("GET", "/")
        assert ctx.attribute("k") is None
        assert ctx.set_attribute("k", 1) is None
        assert ctx.set_attribute("k", 2) == 1
        assert ctx.attribute("k") == 2
        assert ctx.remove_attribute("k") == 2
        assert ctx.attribute("k") is None
        assert ctx.remove_attribute("k") is None

    def test_response_status_starts_at_200(self) -> None:
        ctx = MutableWebRequestContext("GET", "/")
        assert ctx.response_status == 200
        ctx.set_response_status(429)
        assert ctx.response_status == 429

    def test_response_headers_are_writable_through_add(self) -> None:
        ctx = MutableWebRequestContext("GET", "/")
        ctx.add_response_header("Retry-After", "30")
        ctx.add_response_header("Retry-After", "60")
        assert ctx.response_headers() == {"Retry-After": "60"}

    def test_client_key_and_trace_id(self) -> None:
        ctx = MutableWebRequestContext("GET", "/")
        assert ctx.client_key is None
        assert ctx.trace_id is None
        ctx.set_client_key("partner-1")
        ctx.set_trace_id("trace-1")
        assert ctx.client_key == "partner-1"
        assert ctx.trace_id == "trace-1"

    def test_mark_short_circuit_sets_status_body_and_flag(self) -> None:
        ctx = MutableWebRequestContext("GET", "/")
        assert ctx.is_short_circuited is False
        assert ctx.short_circuit_body is None
        ctx.mark_short_circuit(429, '{"error":"rate_limited"}')
        assert ctx.is_short_circuited is True
        assert ctx.response_status == 429
        assert ctx.short_circuit_body == '{"error":"rate_limited"}'

    def test_error_is_overwritten_not_accumulated(self) -> None:
        ctx = MutableWebRequestContext("GET", "/")
        assert ctx.error is None
        first = ValueError("first")
        ctx.set_error(first)
        assert ctx.error is first
        second = RuntimeError("second")
        ctx.set_error(second)
        assert ctx.error is second

    def test_start_nanos_is_set(self) -> None:
        ctx = MutableWebRequestContext("GET", "/")
        assert ctx.start_nanos > 0

    def test_close_is_idempotent(self) -> None:
        ctx = MutableWebRequestContext("GET", "/")
        ctx.close()
        ctx.close()
        assert ctx.is_closed is True

    def test_builder_assembles_a_context(self) -> None:
        ctx = (
            MutableWebRequestContext.builder()
            .method("post")
            .path("/api/orders")
            .header("X-Client-Key", "partner")
            .query_param("page", "2")
            .path_variable("id", "9")
            .build()
        )
        assert ctx.method == "POST"
        assert ctx.path == "/api/orders"
        assert ctx.header("x-client-key") == "partner"
        assert ctx.query_param("page") == "2"
        assert ctx.path_variables() == {"id": "9"}

    def test_satisfies_the_web_request_context_protocol(self) -> None:
        assert isinstance(MutableWebRequestContext("GET", "/"), WebRequestContext)

    def test_works_as_request_context_for_the_size_guard(self) -> None:
        """ctx 必须直接满足 guards.RequestContext 协议（无需额外适配层）。"""
        guard = RequestSizeGuard(max_body_bytes=100, max_header_bytes=10_000)
        ctx = MutableWebRequestContext("POST", "/", {"content-length": ["500"]})
        decision = guard.check(ctx)
        assert decision is not None
        assert decision.status == 413
        assert decision.reason == "REQUEST_BODY_TOO_LARGE"


class TestDefaultWebInterceptorChain:
    def test_interceptors_run_in_registration_order(self) -> None:
        calls: list[str] = []
        chain = DefaultWebInterceptorChain([
            _Recorder("a", calls),
            _Recorder("b", calls),
            _Recorder("c", calls),
        ])
        ctx = MutableWebRequestContext("GET", "/")
        chain.proceed(ctx)
        assert calls == ["a", "b", "c"]

    def test_not_calling_proceed_stops_the_chain(self) -> None:
        calls: list[str] = []
        chain = DefaultWebInterceptorChain([
            _Recorder("a", calls),
            _Recorder("b", calls, stop=True),
            _Recorder("c", calls),
        ])
        chain.proceed(MutableWebRequestContext("GET", "/"))
        assert calls == ["a", "b"]

    def test_proceed_on_short_circuited_context_is_a_noop(self) -> None:
        calls: list[str] = []
        chain = DefaultWebInterceptorChain([_Recorder("a", calls)])
        ctx = MutableWebRequestContext("GET", "/")
        ctx.mark_short_circuit(429, "denied")
        chain.proceed(ctx)
        assert calls == []

    def test_proceed_past_the_end_of_the_chain_is_a_noop(self) -> None:
        calls: list[str] = []
        chain = DefaultWebInterceptorChain([])
        chain.proceed(MutableWebRequestContext("GET", "/"))
        assert calls == []

    def test_interceptors_property_is_read_only(self) -> None:
        calls: list[str] = []
        recorder = _Recorder("a", calls)
        chain = DefaultWebInterceptorChain([recorder])
        assert chain.interceptors == (recorder,)

    def test_current_index_tracks_the_cursor(self) -> None:
        calls: list[str] = []
        chain = DefaultWebInterceptorChain([
            _Recorder("a", calls),
            _Recorder("b", calls),
        ])
        assert chain.current_index == 0
        chain.proceed(MutableWebRequestContext("GET", "/"))
        assert chain.current_index == 2

    def test_exception_propagates_to_the_caller(self) -> None:
        class _Boom:
            def intercept(self, ctx, chain) -> None:
                raise RuntimeError("boom")

        chain = DefaultWebInterceptorChain([_Boom()])
        with pytest.raises(RuntimeError, match="boom"):
            chain.proceed(MutableWebRequestContext("GET", "/"))

    def test_none_interceptors_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            DefaultWebInterceptorChain(None)


class TestWebFilterDecision:
    def test_four_fields_match_java_record(self) -> None:
        decision = WebFilterDecision("RateLimitInterceptor", "partner-1", 429, "rate_limited")
        assert decision.interceptor == "RateLimitInterceptor"
        assert decision.key == "partner-1"
        assert decision.status == 429
        assert decision.reason == "rate_limited"

    def test_is_deny_is_status_ge_400(self) -> None:
        assert WebFilterDecision("x", None, 429, "r").is_deny is True
        assert WebFilterDecision("x", None, 503, "r").is_deny is True
        assert WebFilterDecision("x", None, 200, "r").is_deny is False
        assert WebFilterDecision("x", None, 399, "r").is_deny is False

    def test_rate_limit_deny_factory(self) -> None:
        decision = WebFilterDecision.rate_limit_deny("RateLimitInterceptor", "partner-1", 429)
        assert decision.reason == "rate_limit.exceeded"
        assert decision.key == "partner-1"
        assert decision.status == 429

    def test_circuit_breaker_deny_factory(self) -> None:
        decision = WebFilterDecision.circuit_breaker_deny("CircuitBreakerInterceptor", "svc", 503)
        assert decision.reason == "circuit_breaker.open"
        assert decision.status == 503

    def test_decision_is_frozen(self) -> None:
        decision = WebFilterDecision("x", None, 429, "r")
        with pytest.raises(Exception):
            decision.status = 200

    def test_sink_protocol_is_structural(self) -> None:
        assert isinstance(_Sink(), WebDecisionSink)
