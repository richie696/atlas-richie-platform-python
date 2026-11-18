"""幂等防重与长连接路径豁免（对位 Java `IdempotencyInterceptor` /
`LongLivedPathBypass`）。

幂等：请求带 `X-Idempotency-Key` 时，TTL 内重复键拒绝（409），防重复提交。
无该 header 的请求直接放行——幂等是 opt-in 契约，不是强制。

存储注入：默认进程内 TTL 缓存（对位 Java ConcurrentHashMap）；多实例部署
需注入共享存储（如 cache-redis），否则各实例独立去重。Protocol 保持
web-protection 零第三方依赖。

长连接豁免：SSE/WebSocket 路径不应被请求级防护（签名/限流/体积）拦截——
它们是长流而非一次性请求。匹配用 Ant 模式（复用 rate_limit 的转换器）。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, runtime_checkable

from .rate_limit import ant_pattern_to_regex


@runtime_checkable
class IdempotencyStore(Protocol):
    def put_if_absent(self, key: str) -> bool:
        """True when the key was newly claimed; False when it is a replay."""
        ...


class InMemoryIdempotencyStore:
    """Per-process TTL dedup (对位 Java `IdempotencyCache`)."""

    def __init__(
        self,
        ttl_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        self._ttl = ttl_seconds
        self._clock = clock
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def put_if_absent(self, key: str) -> bool:
        if key is None:
            raise ValueError("idempotency key must not be None")
        now = self._clock()
        with self._lock:
            previous = self._seen.get(key)
            if previous is None or now - previous > self._ttl:
                self._seen[key] = now
                return True
            return False

    def size(self) -> int:
        now = self._clock()
        with self._lock:
            live = {k: v for k, v in self._seen.items() if now - v <= self._ttl}
            self._seen = live
            return len(live)


@dataclass(frozen=True, slots=True)
class IdempotencyDecision:
    reason: str
    status: int = 409
    code: str = "idempotent_replay"
    message: str = ""
    key: str | None = None


class IdempotencyGuard:
    def __init__(
        self,
        store: IdempotencyStore,
        *,
        header_name: str = "X-Idempotency-Key",
        deny_status: int = 409,
        deny_code: str = "idempotent_replay",
        deny_message: str = "重复请求，请勿重复提交 (reason={reason})",
    ) -> None:
        if store is None:
            raise ValueError("store must not be None")
        self._store = store
        self._header = header_name.lower()
        self._deny_status = deny_status
        self._deny_code = deny_code
        self._deny_message = deny_message

    def check(self, headers: Mapping[str, str]) -> IdempotencyDecision | None:
        """None = 放行（无幂等键或首次提交）；decision = 重复提交拒绝。"""
        # ASGI 的 header_map 已小写；独立使用时统一一次，不依赖调用方大小写。
        lowered = {k.lower(): v for k, v in headers.items()}
        key = lowered.get(self._header)
        if key is None or not key.strip():
            return None
        trimmed = key.strip()
        if not self._store.put_if_absent(trimmed):
            return IdempotencyDecision(
                reason="idempotent_replay",
                status=self._deny_status,
                code=self._deny_code,
                message=self._deny_message.replace("{reason}", "idempotent_replay"),
                key=trimmed,
            )
        return None


class LongLivedPathBypass:
    """Ant-pattern matcher for SSE/WS paths exempt from request-level guards."""

    def __init__(self, path_patterns: tuple[str, ...] | list[str]) -> None:
        if path_patterns is None:
            raise ValueError("path_patterns must not be None")
        self._patterns = tuple(path_patterns)
        self._compiled = [ant_pattern_to_regex(p) for p in self._patterns]

    def matches(self, path: str | None) -> bool:
        if path is None:
            return False
        return any(compiled.match(path) for compiled in self._compiled)

    def patterns(self) -> tuple[str, ...]:
        return self._patterns


__all__ = [
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "IdempotencyDecision",
    "IdempotencyGuard",
    "LongLivedPathBypass",
]