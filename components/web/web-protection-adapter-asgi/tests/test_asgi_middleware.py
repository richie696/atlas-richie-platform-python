"""ASGI middleware tests, driven with raw scope/receive/send (no framework)."""

from __future__ import annotations

import asyncio
import json

import pytest

from atlas_richie.web_protection import (
    ApiSignatureVerifier,
    BotUserAgentMatcher,
    IpBlacklistEntry,
    LoginAttemptTracker,
    NonceCache,
    RequestSizeGuard,
    canonicalize,
    hmac_sha256_hex,
)
from atlas_richie.web_protection_adapter_asgi import (
    ProtectionASGIMiddleware,
    client_ip,
    header_map,
)

pytestmark = pytest.mark.unit

SECRET = b"shared-secret"
NOW_MS = 1_700_000_000_000


class _App:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls = 0

    async def __call__(self, scope, receive, send) -> None:
        self.calls += 1
        await send({"type": "http.response.start", "status": self.status, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})


def _scope(path="/", method="GET", headers=None, client=("203.0.113.9", 1234), type_="http"):
    return {
        "type": type_,
        "method": method,
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": client,
    }


async def _run(middleware, scope):
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


def _call(middleware, scope):
    return asyncio.run(_run(middleware, scope))


def _status(sent):
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def _body(sent):
    return b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


class _Keys:
    def secret_for(self, client_key: str) -> bytes | None:
        return SECRET if client_key == "partner" else None


def _signed_headers(path="/api/orders", method="POST", nonce="n-1"):
    ts = NOW_MS
    signature = hmac_sha256_hex(SECRET, canonicalize(method, path, ts, nonce))
    return {
        "x-client-key": "partner",
        "x-timestamp": str(ts),
        "x-nonce": nonce,
        "x-signature": signature,
    }


def _verifier():
    return ApiSignatureVerifier(_Keys(), NonceCache(300), 60, clock=lambda: NOW_MS / 1000)


class TestPassthrough:
    def test_no_guards_is_passthrough(self) -> None:
        app = _App()
        sent = _call(ProtectionASGIMiddleware(app), _scope())
        assert app.calls == 1
        assert _status(sent) == 200

    @pytest.mark.parametrize("type_", ["lifespan", "websocket"])
    def test_non_http_scopes_pass_through(self, type_: str) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")])
        _call(middleware, _scope(type_=type_))
        assert app.calls == 1, "guards must not apply to non-http scopes"


class TestIpBlacklist:
    def test_blacklisted_ip_denied(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, ip_blacklist=[IpBlacklistEntry("203.0.113.0/24")])
        sent = _call(middleware, _scope())
        assert _status(sent) == 403
        assert json.loads(_body(sent)) == {"error": "ip_blacklisted"}
        assert app.calls == 0

    def test_other_ip_allowed(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, ip_blacklist=[IpBlacklistEntry("10.0.0.0/8")])
        _call(middleware, _scope())
        assert app.calls == 1

    def test_forwarded_first_hop_used_when_trusted(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app, ip_blacklist=[IpBlacklistEntry("198.51.100.7")], trust_forwarded=True
        )
        sent = _call(middleware, _scope(headers={"x-forwarded-for": "198.51.100.7, 10.0.0.1"}))
        assert _status(sent) == 403

    def test_forwarded_ignored_by_default(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, ip_blacklist=[IpBlacklistEntry("198.51.100.7")])
        _call(middleware, _scope(headers={"x-forwarded-for": "198.51.100.7"}))
        assert app.calls == 1, "client-supplied XFF must not be trusted by default"


class TestBotMatcher:
    def test_bot_denied(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, bot_matchers=[BotUserAgentMatcher("*curl*")])
        sent = _call(middleware, _scope(headers={"user-agent": "curl/8.4.0"}))
        assert _status(sent) == 403
        assert json.loads(_body(sent)) == {"error": "bot_detected"}

    def test_normal_agent_allowed(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, bot_matchers=[BotUserAgentMatcher("*curl*")])
        _call(middleware, _scope(headers={"user-agent": "Mozilla/5.0"}))
        assert app.calls == 1


class TestSizeGuard:
    def test_oversized_body_denied(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, size_guard=RequestSizeGuard(100, 10_000))
        sent = _call(middleware, _scope(headers={"content-length": "500"}))
        assert _status(sent) == 413
        assert json.loads(_body(sent)) == {"error": "REQUEST_BODY_TOO_LARGE"}
        assert app.calls == 0

    def test_oversized_headers_denied(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, size_guard=RequestSizeGuard(1000, 10))
        sent = _call(middleware, _scope(headers={"x-long": "a" * 50}))
        assert _status(sent) == 431

    def test_body_is_not_consumed(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, size_guard=RequestSizeGuard(1000, 10_000))
        _call(middleware, _scope(headers={"content-length": "10"}))
        assert app.calls == 1


class TestSignature:
    def test_valid_signature_passes(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        _call(middleware, _scope("/api/orders", "POST", _signed_headers()))
        assert app.calls == 1

    def test_missing_headers_denied(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        sent = _call(middleware, _scope("/api/orders", "POST", {"x-client-key": "partner"}))
        assert _status(sent) == 401
        assert json.loads(_body(sent)) == {"error": "missing_header"}

    def test_bad_signature_denied(self) -> None:
        app = _App()
        headers = _signed_headers()
        headers["x-signature"] = "deadbeef"
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        sent = _call(middleware, _scope("/api/orders", "POST", headers))
        assert json.loads(_body(sent)) == {"error": "signature_mismatch"}

    def test_replayed_nonce_denied(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        _call(middleware, _scope("/api/orders", "POST", _signed_headers()))
        sent = _call(middleware, _scope("/api/orders", "POST", _signed_headers()))
        assert json.loads(_body(sent)) == {"error": "nonce_replay"}

    def test_gateway_bypass_header_skips_signature(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        _call(middleware, _scope("/api/orders", "POST", {"x-gateway-verified": "1"}))
        assert app.calls == 1

    def test_gateway_bypass_can_be_disabled(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app, signature_verifier=_verifier(), gateway_bypass_header=None
        )
        # A client key is present but no signature: with bypass disabled this must deny.
        sent = _call(
            middleware,
            _scope("/api/orders", "POST", {"x-gateway-verified": "1", "x-client-key": "partner"}),
        )
        assert _status(sent) == 401
        assert app.calls == 0

    def test_blank_client_key_passes_through(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        _call(middleware, _scope("/api/orders", "POST"))
        assert app.calls == 1


class TestLoginTracker:
    def test_locked_key_rejected_before_app(self) -> None:
        app = _App()
        tracker = LoginAttemptTracker(300, 1, 900)
        tracker.record_failure("203.0.113.9")
        middleware = ProtectionASGIMiddleware(app, login_tracker=tracker)
        sent = _call(middleware, _scope("/login"))
        assert _status(sent) == 429
        assert json.loads(_body(sent)) == {"error": "account_locked"}
        assert app.calls == 0

    def test_downstream_401_records_failure(self) -> None:
        app = _App(status=401)
        tracker = LoginAttemptTracker(300, 2, 900)
        middleware = ProtectionASGIMiddleware(app, login_tracker=tracker)
        _call(middleware, _scope("/login"))
        assert tracker.is_locked("203.0.113.9") is False
        _call(middleware, _scope("/login"))
        assert tracker.is_locked("203.0.113.9") is True

    def test_downstream_2xx_records_success(self) -> None:
        tracker = LoginAttemptTracker(300, 2, 900)
        tracker.record_failure("203.0.113.9")
        middleware = ProtectionASGIMiddleware(_App(status=200), login_tracker=tracker)
        _call(middleware, _scope("/login"))
        assert tracker.size() == 0

    def test_non_login_path_is_not_tracked(self) -> None:
        tracker = LoginAttemptTracker(300, 1, 900)
        middleware = ProtectionASGIMiddleware(_App(status=401), login_tracker=tracker)
        _call(middleware, _scope("/other"))
        assert tracker.is_locked("203.0.113.9") is False

    def test_custom_login_key(self) -> None:
        tracker = LoginAttemptTracker(300, 1, 900)
        middleware = ProtectionASGIMiddleware(
            _App(status=401), login_tracker=tracker,
            login_key=lambda scope, headers: headers.get("x-user"),
        )
        _call(middleware, _scope("/login", headers={"x-user": "alice"}))
        assert tracker.is_locked("alice") is True
        assert tracker.is_locked("203.0.113.9") is False


class TestOrderingAndRendering:
    def test_ip_is_checked_before_bot_and_signature(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app,
            ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")],
            bot_matchers=[BotUserAgentMatcher("*")],
            signature_verifier=_verifier(),
        )
        sent = _call(middleware, _scope(headers={"user-agent": "curl"}))
        assert json.loads(_body(sent)) == {"error": "ip_blacklisted"}

    def test_bot_is_checked_before_size(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app, bot_matchers=[BotUserAgentMatcher("*")], size_guard=RequestSizeGuard(1, 1)
        )
        sent = _call(middleware, _scope(headers={"user-agent": "x", "content-length": "99"}))
        assert json.loads(_body(sent)) == {"error": "bot_detected"}

    def test_custom_deny_renderer_and_status(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app,
            ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")],
            deny_status_ip=418,
            deny_renderer=lambda status, reason: f"{status}:{reason}".encode(),
        )
        sent = _call(middleware, _scope())
        assert _status(sent) == 418
        assert _body(sent) == b"418:ip_blacklisted"

    def test_deny_sets_content_length(self) -> None:
        middleware = ProtectionASGIMiddleware(_App(), ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")])
        sent = _call(middleware, _scope())
        start = next(m for m in sent if m["type"] == "http.response.start")
        headers = dict(start["headers"])
        assert int(headers[b"content-length"]) == len(_body(sent))


class TestHelpers:
    def test_header_map_lowercases_and_decodes(self) -> None:
        scope = _scope(headers={"X-Client-Key": "partner"})
        assert header_map(scope) == {"x-client-key": "partner"}

    def test_client_ip_from_scope(self) -> None:
        assert client_ip(_scope(), {}) == "203.0.113.9"

    def test_client_ip_absent(self) -> None:
        scope = _scope()
        scope["client"] = None
        assert client_ip(scope, {}) is None
