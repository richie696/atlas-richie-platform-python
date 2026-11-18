"""幂等防重与长连接路径豁免。"""

from __future__ import annotations

import pytest

from atlas_richie.web_protection import (
    IdempotencyGuard,
    InMemoryIdempotencyStore,
    LongLivedPathBypass,
)

pytestmark = pytest.mark.unit


class TestInMemoryStore:
    def test_first_claim_succeeds(self) -> None:
        store = InMemoryIdempotencyStore(60)
        assert store.put_if_absent("k") is True

    def test_replay_rejected(self) -> None:
        store = InMemoryIdempotencyStore(60)
        store.put_if_absent("k")
        assert store.put_if_absent("k") is False

    def test_ttl_expiry_allows_reclaim(self) -> None:
        clock = [0.0]
        store = InMemoryIdempotencyStore(10, clock=lambda: clock[0])
        assert store.put_if_absent("k") is True
        clock[0] = 11.0
        assert store.put_if_absent("k") is True

    def test_within_ttl_still_rejected(self) -> None:
        clock = [0.0]
        store = InMemoryIdempotencyStore(10, clock=lambda: clock[0])
        store.put_if_absent("k")
        clock[0] = 9.0
        assert store.put_if_absent("k") is False

    def test_size_counts_live_only(self) -> None:
        clock = [0.0]
        store = InMemoryIdempotencyStore(10, clock=lambda: clock[0])
        store.put_if_absent("a")
        store.put_if_absent("b")
        clock[0] = 11.0
        store.put_if_absent("c")
        assert store.size() == 1

    def test_none_key_rejected(self) -> None:
        with pytest.raises(ValueError):
            InMemoryIdempotencyStore(60).put_if_absent(None)

    @pytest.mark.parametrize("ttl", [0, -1])
    def test_invalid_ttl_rejected(self, ttl) -> None:
        with pytest.raises(ValueError):
            InMemoryIdempotencyStore(ttl)

    def test_distinct_keys_independent(self) -> None:
        store = InMemoryIdempotencyStore(60)
        assert store.put_if_absent("a") is True
        assert store.put_if_absent("b") is True


class TestIdempotencyGuard:
    def _guard(self, **kwargs):
        return IdempotencyGuard(InMemoryIdempotencyStore(60), **kwargs)

    def test_no_header_passes(self) -> None:
        assert self._guard().check({}) is None

    def test_blank_header_passes(self) -> None:
        assert self._guard().check({"x-idempotency-key": "  "}) is None

    def test_first_submission_passes(self) -> None:
        assert self._guard().check({"x-idempotency-key": "abc"}) is None

    def test_replay_denied_with_409(self) -> None:
        guard = self._guard()
        guard.check({"x-idempotency-key": "abc"})
        decision = guard.check({"x-idempotency-key": "abc"})
        assert decision is not None
        assert decision.status == 409
        assert decision.code == "idempotent_replay"
        assert decision.key == "abc"
        assert "idempotent_replay" in decision.message

    def test_key_is_trimmed(self) -> None:
        guard = self._guard()
        guard.check({"x-idempotency-key": " abc "})
        assert guard.check({"x-idempotency-key": "abc"}) is not None

    def test_header_name_case_insensitive(self) -> None:
        guard = self._guard()
        guard.check({"X-Idempotency-Key": "abc"})
        assert guard.check({"x-idempotency-key": "abc"}) is not None

    def test_custom_header_name(self) -> None:
        guard = self._guard(header_name="X-Request-Id")
        assert guard.check({"x-request-id": "r1"}) is None
        assert guard.check({"x-request-id": "r1"}) is not None

    def test_custom_deny_response(self) -> None:
        guard = self._guard(deny_status=429, deny_code="DUP", deny_message="dup {reason}")
        guard.check({"x-idempotency-key": "k"})
        decision = guard.check({"x-idempotency-key": "k"})
        assert decision.status == 429
        assert decision.code == "DUP"
        assert decision.message == "dup idempotent_replay"

    def test_shared_store_injection(self) -> None:
        class _Shared:
            def __init__(self):
                self.keys = set()

            def put_if_absent(self, key):
                if key in self.keys:
                    return False
                self.keys.add(key)
                return True

        shared = _Shared()
        first = IdempotencyGuard(shared)
        second = IdempotencyGuard(shared)
        assert first.check({"x-idempotency-key": "k"}) is None
        assert second.check({"x-idempotency-key": "k"}) is not None, "共享存储跨实例去重"

    def test_none_store_rejected(self) -> None:
        with pytest.raises(ValueError):
            IdempotencyGuard(None)


class TestLongLivedPathBypass:
    def test_exact_match(self) -> None:
        bypass = LongLivedPathBypass(["/events"])
        assert bypass.matches("/events") is True
        assert bypass.matches("/events/extra") is False

    def test_ant_patterns(self) -> None:
        bypass = LongLivedPathBypass(["/sse/**", "/ws/*", "/stream/{id}"])
        assert bypass.matches("/sse/orders/1") is True
        assert bypass.matches("/ws/chat") is True
        assert bypass.matches("/ws/chat/extra") is False
        assert bypass.matches("/stream/42") is True
        assert bypass.matches("/api/orders") is False

    def test_none_path_is_false(self) -> None:
        assert LongLivedPathBypass(["/sse/**"]).matches(None) is False

    def test_empty_patterns_match_nothing(self) -> None:
        assert LongLivedPathBypass([]).matches("/anything") is False

    def test_patterns_accessor(self) -> None:
        assert LongLivedPathBypass(["/a", "/b"]).patterns() == ("/a", "/b")

    def test_none_patterns_rejected(self) -> None:
        with pytest.raises(ValueError):
            LongLivedPathBypass(None)