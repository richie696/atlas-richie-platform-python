"""Trace ID 归一化（对位 Java `web.core.tracing` 包）。

Java 侧两个类：
- `TraceIdParser` —— 纯算法：解析 W3C `traceparent` / `X-Request-Id`，归一成
  32 位 hex trace id；都没有则自生成。
- `OtelTracingInterceptor` —— SPI 拦截器：把归一后的 trace id 写进 ctx 与
  响应头 `X-Trace-Id`。它**不**依赖 OTel SDK（R3 倾向 optional），本移植同样
  零依赖，因此类名取 `TraceIdInterceptor`（Java 的 `Otel...` 前缀名不副实）。

解析顺序
    ` `traceparent`（W3C：版本 00 + 32-hex trace-id + 16-hex parent-id + flags）
    ` `X-Request-Id`（业务侧兜底）
    ` 自生成 32-hex UUID v4

与 Java 的两处已知差异
    ①Java 的 `String.trim()` 只裁剪码位 ≤ U+0020 的字符、`isBlank()` 按
      `Character.isWhitespace` 判定；本移植统一按 ASCII 空白裁剪。现实输入
      等价，仅在 U+00A0 等不换行空格上有别。
    ②Java README 记录的 `tracing.prefer-w3c` 开关在 Java **源码里并不存在**
      （`TraceIdParser.resolve` 永远优先 traceparent）；本移植对位源码。

另注：Java 的 web trace 拦截器是**旧路径**——`TracingAutoConfiguration` 上有
`ConditionalOnMissingClass(ObservabilityState)`，即统一 observability starter
在场时不装配它，避免 `ctx.traceId` 与活动的 OTel SpanContext 分叉。Python 仓
尚无 observability 组件，本移植按独立路径落地；届时需沿用同一条互斥规则。
"""

from __future__ import annotations

import uuid

from .spi import WebInterceptorChain, WebRequestContext

_ASCII_WHITESPACE = " \t\n\r\v\f"
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _trim(value: str) -> str:
    """裁剪首尾 ASCII 空白（对位 Java `String.trim()` 的常用子集）。"""
    return value.strip(_ASCII_WHITESPACE)


def _is_blank(value: str) -> bool:
    """空串或全是 ASCII 空白（对位 Java `String.isBlank()`）。"""
    return _trim(value) == ""


class TraceIdParser:
    """Trace ID 解析器（对位 Java `TraceIdParser`）。

    全部方法都是无状态静态方法，类本身不实例化。
    """

    #: W3C traceparent header 名。
    TRACEPARENT_HEADER = "traceparent"

    #: 业务侧常用 Request ID header。
    X_REQUEST_ID_HEADER = "X-Request-Id"

    #: 响应头：让下游链路可关联。
    RESPONSE_TRACE_ID_HEADER = "X-Trace-Id"

    #: traceparent 协议版本（当前固定 00）。
    TRACEPARENT_VERSION = "00"

    #: trace-id 长度（W3C 标准 16 字节 = 32 hex char）。
    TRACE_ID_LENGTH = 32

    @staticmethod
    def resolve(traceparent_value: str | None, request_id_value: str | None) -> str:
        """从上游 header 解析或自生成 trace ID（32 位 hex，永不为 None）。"""
        if traceparent_value is not None and not _is_blank(traceparent_value):
            parsed = TraceIdParser.parse_traceparent(traceparent_value)
            if parsed is not None:
                return parsed
        if request_id_value is not None and not _is_blank(request_id_value):
            trimmed = _trim(request_id_value)
            if TraceIdParser.is_valid_trace_id(trimmed):
                # 合法 32-hex 原样返回（**保留原大小写**，与 Java 一致）
                return trimmed
            return TraceIdParser._pad_or_generate(trimmed)
        return TraceIdParser.generate_trace_id()

    @staticmethod
    def parse_traceparent(traceparent: str | None) -> str | None:
        """解析 W3C traceparent，返回小写 trace id；不合法返回 None。"""
        if traceparent is None:
            return None
        parts = _trim(traceparent).split("-")
        if len(parts) < 2:
            return None
        if parts[0] != TraceIdParser.TRACEPARENT_VERSION:
            return None
        trace_id = parts[1]
        if not TraceIdParser.is_valid_trace_id(trace_id):
            return None
        return trace_id.lower()

    @staticmethod
    def generate_trace_id() -> str:
        """自生成 32 位小写 hex（UUID v4，去掉分隔符）。"""
        return uuid.uuid4().hex

    @staticmethod
    def is_valid_trace_id(value: str | None) -> bool:
        """是否是 32 位 hex（大小写皆可）。"""
        if value is None or len(value) != TraceIdParser.TRACE_ID_LENGTH:
            return False
        return all(char in _HEX_DIGITS for char in value)

    @staticmethod
    def _pad_or_generate(candidate: str) -> str:
        """把非标准长度的 id 补齐到 32 位。

        注意：补的是**随机 hex**，不是补零 —— 与 Java 的 `padOrGenerate` 一致。
        超长则截断到 32 位并转小写。
        """
        length = TraceIdParser.TRACE_ID_LENGTH
        if len(candidate) >= length:
            return candidate[:length].lower()
        return candidate.lower() + TraceIdParser.generate_trace_id()[: length - len(candidate)]


class TraceIdInterceptor:
    """Trace ID 归一拦截器（对位 Java `OtelTracingInterceptor`）。

    拦截器链**最早期**（`ORDER` = 50，早于 Java `PlatformProtection` 的 100），
    让 trace id 尽早进 ctx，后续拦截器可读取并写进响应头。

    不依赖 OTel SDK：只解析 W3C 字符串。
    """

    #: 与 Java 一致：早于防护 A 组。
    ORDER = 50

    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        trace_id = TraceIdParser.resolve(
            ctx.header(TraceIdParser.TRACEPARENT_HEADER),
            ctx.header(TraceIdParser.X_REQUEST_ID_HEADER),
        )
        ctx.set_trace_id(trace_id)
        ctx.add_response_header(TraceIdParser.RESPONSE_TRACE_ID_HEADER, trace_id)
        chain.proceed(ctx)


__all__ = ["TraceIdInterceptor", "TraceIdParser"]
