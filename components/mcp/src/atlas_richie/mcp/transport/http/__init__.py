"""HTTP transport adapter for the MCP client facade."""

from .exchange import (
    SSE_CONTENT_TYPE,
    AsyncHttpExecutor,
    AuthorizationProvider,
    McpHttpExchange,
)
from .sse_consumer import (
    ProgressCallback,
    SseConsumerError,
    SseConsumerState,
    SseMcpMessage,
    consume_sse_response,
)

__all__ = [
    "AsyncHttpExecutor",
    "AuthorizationProvider",
    "McpHttpExchange",
    "ProgressCallback",
    "SSE_CONTENT_TYPE",
    "SseConsumerError",
    "SseConsumerState",
    "SseMcpMessage",
    "consume_sse_response",
]
