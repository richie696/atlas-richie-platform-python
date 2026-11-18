"""Request protection contract tests.

The bot globs, IP/CIDR matching, nonce and login-tracker operation sequences are
additionally pinned by a 561-case differential run against the compiled Java
primitives (byte-identical). These tests cover the signing verifier, the size
guard, time-based behaviour via injected clocks, and the deliberate deviations.
"""

from __future__ import annotations

import pytest

from atlas_richie.web_protection import (
    ApiSignatureVerifier,
    BotUserAgentMatcher,
    IpBlacklistEntry,
    LoginAttemptTracker,
    NonceCache,
    RequestSizeGuard,
    canonicalize,
    glob_to_regex,
    hmac_sha256_hex,
)

pytestmark = pytest.mark.unit


class _Ctx:
    def __init__(self, headers: dict[str, list[str]]) -> None:
        self._headers = headers

    def header(self, name: str) -> str | None:
        values = self._headers.get(name)
        return values[0] if values else None

    def header_names(self) -> list[str]:
        return list(self._headers)

    def headers(self, name: str) -> list[str]:
        return self._headers.get(name, [])


class _Keys:
    def __init__(self, secrets: dict[str, bytes]) -> None:
        self._secrets = secrets

    def secret_for(self, client_key: str) -> bytes | None:
        return self._secrets.get(client_key)


SECRET = b"shared-secret"
NOW_MS = 1_700_000_000_000


def _signed(method="POST", path="/api/orders", ts=NOW_MS, nonce="n-1", key="partner"):
    signature = hmac_sha256_hex(SECRET, canonicalize(method, path, ts, nonce))
    return dict(
        method=method, path=path, client_key=key,
        timestamp=str(ts), nonce=nonce, signature=signature, now_millis=NOW_MS,
    )


def _verifier(skew=60, secrets=None):
    return ApiSignatureVerifier(
        _Keys(secrets if secrets is not None else {"partner": SECRET}),
        NonceCache(300),
        timestamp_skew_seconds=skew,
    )


class TestBotMatcher:
    @pytest.mark.parametrize(
        ("glob", "ua", "expected"),
        [
            ("*bot*", "Googlebot/2.1", True),
            ("*bot*", "Mozilla/5.0", False),
            ("Googlebot", "googlebot", True),
            ("", "anything", True),
            ("*", "", True),
            ("curl/*", "curl/8.4.0", True),
            ("Mozilla/?*", "Mozilla/5.0", True),
            ("a.b", "axb", False),
            ("path/*", "path/", True),
            ("path/?", "path/", False),
        ],
    )
    def test_matching(self, glob: str, ua: str, expected: bool) -> None:
        assert BotUserAgentMatcher(glob).matches(ua) is expected

    def test_none_user_agent_never_matches(self) -> None:
        assert BotUserAgentMatcher("*").matches(None) is False

    def test_trailing_slash_before_star_is_dropped(self) -> None:
        assert glob_to_regex("/path/*") == glob_to_regex("/path*")

    def test_trailing_slash_before_question_is_literal(self) -> None:
        assert glob_to_regex("/path/?") != glob_to_regex("/path?")

    def test_regex_metacharacters_are_literal(self) -> None:
        assert BotUserAgentMatcher("a.b").matches("a.b") is True
        assert BotUserAgentMatcher("[x]").matches("[x]") is True


class TestIpBlacklist:
    @pytest.mark.parametrize(
        ("source", "candidate", "expected"),
        [
            ("10.0.0.0/8", "10.255.255.255", True),
            ("10.0.0.0/8", "11.0.0.1", False),
            ("10.0.0.1", "10.0.0.1", True),
            ("10.0.0.1", "10.0.0.2", False),
            ("0.0.0.0/0", "8.8.8.8", True),
            ("0.0.0.0/0", "2001:db8::1", False),
            ("2001:db8::/32", "2001:db8::5", True),
            ("2001:db8::/32", "2001:db9::1", False),
            ("::1", "::1", True),
        ],
    )
    def test_matching(self, source: str, candidate: str, expected: bool) -> None:
        assert IpBlacklistEntry(source).matches(candidate) is expected

    def test_forwarded_chain_uses_first_hop(self) -> None:
        entry = IpBlacklistEntry("10.0.0.1")
        assert entry.matches("10.0.0.1, 8.8.8.8") is True
        assert entry.matches("8.8.8.8, 10.0.0.1") is False

    def test_blank_and_invalid_candidates(self) -> None:
        entry = IpBlacklistEntry("0.0.0.0/0")
        assert entry.matches(None) is False
        assert entry.matches("   ") is False
        assert entry.matches("not-an-ip") is False

    @pytest.mark.parametrize("source", ["999.1.1.1", "10.0.0.1/33", "2001:db8::1/129", "10.0.0.1/-1", "10.0.0.1/abc"])
    def test_invalid_sources_rejected(self, source: str) -> None:
        with pytest.raises(ValueError):
            IpBlacklistEntry(source)

    def test_hostname_is_not_resolved(self) -> None:
        """Hardening deviation: Java's getByName would do a DNS lookup."""
        assert IpBlacklistEntry("0.0.0.0/0").matches("localhost") is False


class TestNonceCache:
    def test_replay_detected(self) -> None:
        cache = NonceCache(300)
        assert cache.put_if_absent("n") is True
        assert cache.put_if_absent("n") is False
        assert cache.contains("n") is True

    def test_expiry_makes_nonce_fresh_again(self) -> None:
        clock = [0.0]
        cache = NonceCache(10, clock=lambda: clock[0])
        assert cache.put_if_absent("n") is True
        clock[0] = 10.0
        assert cache.put_if_absent("n") is False, "boundary is inclusive (now - prev > ttl)"
        clock[0] = 10.1
        assert cache.put_if_absent("n") is True

    def test_contains_purges_expired(self) -> None:
        clock = [0.0]
        cache = NonceCache(10, clock=lambda: clock[0])
        cache.put_if_absent("n")
        clock[0] = 11.0
        assert cache.contains("n") is False
        assert cache.size() == 0

    def test_invalid_ttl_rejected(self) -> None:
        with pytest.raises(ValueError):
            NonceCache(0)


class TestLoginAttemptTracker:
    def test_locks_at_threshold(self) -> None:
        tracker = LoginAttemptTracker(60, 3, 300)
        assert tracker.is_locked("u") is False
        assert tracker.record_failure("u") == 1
        assert tracker.record_failure("u") == 2
        assert tracker.is_locked("u") is False
        assert tracker.record_failure("u") == 3
        assert tracker.is_locked("u") is True

    def test_success_clears_window(self) -> None:
        tracker = LoginAttemptTracker(60, 2, 300)
        tracker.record_failure("u")
        tracker.record_failure("u")
        assert tracker.is_locked("u") is True
        tracker.record_success("u")
        assert tracker.is_locked("u") is False
        assert tracker.size() == 0

    def test_lockout_expires(self) -> None:
        clock = [0.0]
        tracker = LoginAttemptTracker(60, 1, 30, clock=lambda: clock[0])
        tracker.record_failure("u")
        assert tracker.is_locked("u") is True
        clock[0] = 31.0
        assert tracker.is_locked("u") is False

    def test_window_evicts_old_failures(self) -> None:
        clock = [0.0]
        tracker = LoginAttemptTracker(10, 3, 300, clock=lambda: clock[0])
        tracker.record_failure("u")
        clock[0] = 5.0
        tracker.record_failure("u")
        clock[0] = 11.0
        assert tracker.record_failure("u") == 2, "the first failure left the window"
        assert tracker.is_locked("u") is False

    def test_keys_are_independent(self) -> None:
        tracker = LoginAttemptTracker(60, 1, 300)
        tracker.record_failure("a")
        assert tracker.is_locked("a") is True
        assert tracker.is_locked("b") is False

    def test_none_key_is_ignored(self) -> None:
        tracker = LoginAttemptTracker(60, 1, 300)
        assert tracker.record_failure(None) == 0
        assert tracker.is_locked(None) is False
        tracker.record_success(None)

    @pytest.mark.parametrize("args", [(0, 3, 300), (60, 0, 300), (60, 3, 0)])
    def test_invalid_configuration_rejected(self, args) -> None:
        with pytest.raises(ValueError):
            LoginAttemptTracker(*args)


class TestRequestSizeGuard:
    def test_body_over_limit_denied(self) -> None:
        guard = RequestSizeGuard(100, 10_000)
        decision = guard.check(_Ctx({"Content-Length": ["101"]}))
        assert decision is not None
        assert (decision.status, decision.reason, decision.limit, decision.actual) == (
            413, "REQUEST_BODY_TOO_LARGE", 100, 101
        )

    def test_body_at_limit_allowed(self) -> None:
        assert RequestSizeGuard(100, 10_000).check(_Ctx({"Content-Length": ["100"]})) is None

    @pytest.mark.parametrize("value", ["abc", "-5", "", "   "])
    def test_unparseable_or_negative_content_length_passes(self, value: str) -> None:
        assert RequestSizeGuard(100, 10_000).check(_Ctx({"Content-Length": [value]})) is None

    def test_missing_content_length_passes(self) -> None:
        assert RequestSizeGuard(100, 10_000).check(_Ctx({})) is None

    def test_header_over_limit_denied(self) -> None:
        guard = RequestSizeGuard(100, 20)
        decision = guard.check(_Ctx({"X-Long": ["a" * 30]}))
        assert decision is not None
        assert decision.reason == "REQUEST_HEADER_TOO_LARGE"
        assert decision.actual == len("X-Long") + 30 + 4

    def test_header_counts_characters_not_bytes(self) -> None:
        guard = RequestSizeGuard(100, 12)
        # name(1) + value(1 CJK char) + 4 = 6 characters, though 8 UTF-8 bytes
        assert guard.check(_Ctx({"X": ["中"]})) is None

    def test_multiple_values_are_summed(self) -> None:
        guard = RequestSizeGuard(100, 15)
        decision = guard.check(_Ctx({"A": ["12345", "12345"]}))
        assert decision is not None
        assert decision.actual == 2 * (1 + 5 + 4)

    def test_body_is_checked_before_headers(self) -> None:
        guard = RequestSizeGuard(1, 1)
        decision = guard.check(_Ctx({"Content-Length": ["99"], "X": ["y" * 99]}))
        assert decision.reason == "REQUEST_BODY_TOO_LARGE"

    @pytest.mark.parametrize("args", [(0, 100), (100, 0)])
    def test_invalid_limits_rejected(self, args) -> None:
        with pytest.raises(ValueError):
            RequestSizeGuard(*args)


class TestApiSignature:
    def test_valid_signature_allowed(self) -> None:
        assert _verifier().verify(**_signed()) is None

    @pytest.mark.parametrize(
        "signature",
        [
            "ab\xff",          # latin-1 decoded ASGI header byte
            "abc\u00ff",       # non-ASCII BMP
            "签名",             # multi-byte
            "\udcff",          # lone surrogate from surrogateescape decoding
            "deadbeef\u0000",  # embedded NUL
        ],
    )
    def test_non_ascii_signature_is_a_mismatch_not_a_crash(self, signature: str) -> None:
        """Regression: compare_digest(str, str) raises TypeError on non-ASCII,
        which turned a hostile signature header into a 500 instead of a 401."""
        kwargs = _signed()
        kwargs["signature"] = signature
        decision = _verifier().verify(**kwargs)
        assert decision is not None
        assert decision.reason == "signature_mismatch"

    def test_valid_signature_still_matches_after_byte_comparison(self) -> None:
        assert _verifier().verify(**_signed(nonce="n-utf8-✓")) is None

    def test_blank_client_key_allowed_through(self) -> None:
        kwargs = _signed()
        kwargs["client_key"] = "  "
        assert _verifier().verify(**kwargs) is None

    def test_gateway_bypass_allowed_through(self) -> None:
        kwargs = _signed()
        kwargs["signature"] = "wrong"
        assert _verifier().verify(gateway_bypassed=True, **kwargs) is None

    @pytest.mark.parametrize(
        ("field", "value", "reason"),
        [
            ("timestamp", None, "missing_header"),
            ("timestamp", "not-a-number", "bad_timestamp"),
            ("nonce", None, "missing_header"),
            ("signature", None, "missing_header"),
            ("signature", "deadbeef", "signature_mismatch"),
        ],
    )
    def test_deny_reasons(self, field: str, value, reason: str) -> None:
        kwargs = _signed()
        kwargs[field] = value
        decision = _verifier().verify(**kwargs)
        assert decision is not None
        assert decision.reason == reason

    def test_timestamp_skew(self) -> None:
        kwargs = _signed(ts=NOW_MS - 61_000)
        decision = _verifier().verify(**kwargs)
        assert decision.reason == "timestamp_skew"

    def test_timestamp_within_skew_allowed(self) -> None:
        kwargs = _signed(ts=NOW_MS - 60_000)
        assert _verifier().verify(**kwargs) is None

    def test_nonce_replay(self) -> None:
        verifier = _verifier()
        assert verifier.verify(**_signed()) is None
        decision = verifier.verify(**_signed())
        assert decision.reason == "nonce_replay"

    def test_missing_secret(self) -> None:
        decision = _verifier(secrets={}).verify(**_signed())
        assert decision.reason == "no_secret"

    def test_empty_secret_is_no_secret(self) -> None:
        decision = _verifier(secrets={"partner": b""}).verify(**_signed())
        assert decision.reason == "no_secret"

    def test_signature_covers_method_and_path(self) -> None:
        verifier = _verifier()
        kwargs = _signed()
        assert verifier.verify(**kwargs) is None
        tampered = _signed(nonce="n-2")
        tampered["method"] = "GET"
        assert verifier.verify(**tampered).reason == "signature_mismatch"

    def test_canonical_string_format(self) -> None:
        assert canonicalize("POST", "/a", 123, "n") == "POST\n/a\n123\nn"

    def test_hex_is_lowercase(self) -> None:
        digest = hmac_sha256_hex(b"k", "m")
        assert digest == digest.lower()
        assert len(digest) == 64
