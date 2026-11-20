"""Trace ID 归一化测试（1:1 对位 Java `TraceIdParserTest` / `OtelTracingInterceptorTest`）。"""

from __future__ import annotations

import re

import pytest

from atlas_richie.web_protection.tracing import TraceIdInterceptor, TraceIdParser
from atlas_richie.web_protection.spi import (
    DefaultWebInterceptorChain,
    MutableWebRequestContext,
)

pytestmark = pytest.mark.unit

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
HEX32 = re.compile(r"^[0-9a-f]{32}$")


class TestResolve:
    def test_prefers_w3c_traceparent(self) -> None:
        resolved = TraceIdParser.resolve(TRACEPARENT, "fallback-request-id")
        assert resolved == TRACE_ID

    def test_falls_back_to_request_id(self) -> None:
        resolved = TraceIdParser.resolve(None, "client-supplied-id")
        assert len(resolved) == 32
        assert resolved.startswith("client-supplied-id")

    def test_generates_random_when_both_missing(self) -> None:
        resolved = TraceIdParser.resolve(None, None)
        assert len(resolved) == 32
        assert HEX32.match(resolved)

    def test_generates_random_when_both_blank(self) -> None:
        resolved = TraceIdParser.resolve("   ", "")
        assert len(resolved) == 32
        assert HEX32.match(resolved)

    def test_traceparent_without_version_falls_through(self) -> None:
        resolved = TraceIdParser.resolve("not-a-traceparent", "fallback")
        assert len(resolved) == 32

    def test_invalid_traceparent_falls_back_to_request_id(self) -> None:
        resolved = TraceIdParser.resolve("01-" + TRACE_ID + "-00f067aa0ba902b7-01", "fallback-id")
        assert resolved.startswith("fallback-id")

    def test_never_returns_none(self) -> None:
        for traceparent, request_id in ((None, None), ("", ""), (" ", " "), ("x", None)):
            assert TraceIdParser.resolve(traceparent, request_id) is not None


class TestResolvePadding:
    def test_valid_32_hex_request_id_is_returned_verbatim(self) -> None:
        """Java 对合法 32-hex 的 `X-Request-Id` **原样返回**（保留大小写）。"""
        upper = TRACE_ID.upper()
        assert TraceIdParser.resolve(None, upper) == upper

    def test_short_request_id_is_padded_with_random_hex(self) -> None:
        """补的是随机 hex，不是补零（与 Java 的 padOrGenerate 一致）。"""
        resolved = TraceIdParser.resolve(None, "abc")
        assert len(resolved) == 32
        assert resolved.startswith("abc")
        assert resolved != "abc" + "0" * 29
        assert HEX32.match(resolved)

    def test_short_request_id_is_lowercased(self) -> None:
        resolved = TraceIdParser.resolve(None, "ABC")
        assert resolved.startswith("abc")

    def test_long_request_id_is_truncated_to_32(self) -> None:
        resolved = TraceIdParser.resolve(None, "A" * 40)
        assert resolved == "a" * 32

    def test_request_id_is_trimmed(self) -> None:
        resolved = TraceIdParser.resolve(None, "  padded-id  ")
        assert resolved.startswith("padded-id")


class TestParseTraceparent:
    def test_invalid_version_returns_none(self) -> None:
        assert TraceIdParser.parse_traceparent(
            "01-" + TRACE_ID + "-00f067aa0ba902b7-01"
        ) is None

    def test_invalid_trace_id_returns_none(self) -> None:
        assert TraceIdParser.parse_traceparent("00-XX-00f067aa0ba902b7-01") is None

    def test_too_short_returns_none(self) -> None:
        assert TraceIdParser.parse_traceparent("00-abc-00f067aa0ba902b7-01") is None

    def test_valid_returns_lowercase(self) -> None:
        parsed = TraceIdParser.parse_traceparent(
            "00-" + TRACE_ID.upper() + "-00f067aa0ba902b7-01"
        )
        assert parsed == TRACE_ID

    def test_none_input_returns_none(self) -> None:
        assert TraceIdParser.parse_traceparent(None) is None

    def test_empty_input_returns_none(self) -> None:
        assert TraceIdParser.parse_traceparent("") is None

    def test_extra_segments_are_tolerated(self) -> None:
        assert TraceIdParser.parse_traceparent(TRACEPARENT + "-extra") == TRACE_ID


class TestGenerateTraceId:
    def test_returns_32_hex(self) -> None:
        generated = TraceIdParser.generate_trace_id()
        assert len(generated) == 32
        assert HEX32.match(generated)

    def test_two_calls_differ(self) -> None:
        assert TraceIdParser.generate_trace_id() != TraceIdParser.generate_trace_id()


class TestIsValidTraceId:
    def test_accepts_32_hex_in_any_case(self) -> None:
        assert TraceIdParser.is_valid_trace_id(TRACE_ID) is True
        assert TraceIdParser.is_valid_trace_id(TRACE_ID.upper()) is True

    def test_rejects_wrong_length(self) -> None:
        assert TraceIdParser.is_valid_trace_id("abc") is False
        assert TraceIdParser.is_valid_trace_id("a" * 33) is False

    def test_rejects_non_hex(self) -> None:
        assert TraceIdParser.is_valid_trace_id("z" * 32) is False

    def test_rejects_none(self) -> None:
        assert TraceIdParser.is_valid_trace_id(None) is False


class TestConstants:
    def test_header_names_match_java(self) -> None:
        assert TraceIdParser.TRACEPARENT_HEADER == "traceparent"
        assert TraceIdParser.X_REQUEST_ID_HEADER == "X-Request-Id"
        assert TraceIdParser.RESPONSE_TRACE_ID_HEADER == "X-Trace-Id"

    def test_version_and_length_match_java(self) -> None:
        assert TraceIdParser.TRACEPARENT_VERSION == "00"
        assert TraceIdParser.TRACE_ID_LENGTH == 32


class TestTraceIdInterceptor:
    def _ctx(self, **headers: str) -> MutableWebRequestContext:
        return MutableWebRequestContext("GET", "/api/v1/users", headers)

    def test_traceparent_sets_trace_id(self) -> None:
        ctx = self._ctx(traceparent=TRACEPARENT)
        TraceIdInterceptor().intercept(ctx, DefaultWebInterceptorChain([]))
        assert ctx.trace_id == TRACE_ID
        assert ctx.response_headers()[TraceIdParser.RESPONSE_TRACE_ID_HEADER] == TRACE_ID

    def test_request_id_header_sets_trace_id(self) -> None:
        ctx = self._ctx(**{"X-Request-Id": "client-trace-abc"})
        TraceIdInterceptor().intercept(ctx, DefaultWebInterceptorChain([]))
        assert ctx.trace_id is not None
        assert len(ctx.trace_id) == 32
        assert ctx.trace_id.startswith("client-trace-abc")

    def test_no_headers_generates_random(self) -> None:
        ctx = self._ctx()
        TraceIdInterceptor().intercept(ctx, DefaultWebInterceptorChain([]))
        assert ctx.trace_id is not None
        assert len(ctx.trace_id) == 32
        assert HEX32.match(ctx.trace_id)
        assert ctx.response_headers()[TraceIdParser.RESPONSE_TRACE_ID_HEADER] == ctx.trace_id

    def test_calls_chain_proceed(self) -> None:
        proceeded: list[bool] = []

        class _Tail:
            def intercept(self, ctx, chain) -> None:
                proceeded.append(True)

        TraceIdInterceptor().intercept(self._ctx(), DefaultWebInterceptorChain([_Tail()]))
        assert proceeded == [True]

    def test_order_is_50(self) -> None:
        assert TraceIdInterceptor.ORDER == 50

    def test_response_header_added_even_when_chain_not_called(self) -> None:
        ctx = self._ctx()
        TraceIdInterceptor().intercept(ctx, DefaultWebInterceptorChain([]))
        assert TraceIdParser.RESPONSE_TRACE_ID_HEADER in ctx.response_headers()

    def test_header_lookup_is_case_insensitive(self) -> None:
        ctx = MutableWebRequestContext("GET", "/", {"TRACEPARENT": TRACEPARENT})
        TraceIdInterceptor().intercept(ctx, DefaultWebInterceptorChain([]))
        assert ctx.trace_id == TRACE_ID
