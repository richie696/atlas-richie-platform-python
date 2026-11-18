# atlas-richie-web-protection-adapter-asgi

ASGI middleware that wires the `atlas-richie-web-protection` guards into incoming
request handling. Pure ASGI — no Starlette or framework dependency.

These guards are **server-side** protections, so ASGI middleware is the correct
integration point. The `atlas_richie.http` interceptor chain is a *client* facade
and is deliberately not used.

Depends only on `atlas-richie-web-protection`; the zero-dependency core is not
polluted by adapter concerns.

## Usage

```python
from atlas_richie.web_protection import (
    ApiSignatureVerifier, BotUserAgentMatcher, IpBlacklistEntry,
    LoginAttemptTracker, NonceCache, RequestSizeGuard,
)
from atlas_richie.web_protection_adapter_asgi import ProtectionASGIMiddleware

app = ProtectionASGIMiddleware(
    my_asgi_app,
    ip_blacklist=[IpBlacklistEntry("10.0.0.0/8")],
    bot_matchers=[BotUserAgentMatcher("*curl*")],
    size_guard=RequestSizeGuard(max_body_bytes=1_048_576, max_header_bytes=16_384),
    signature_verifier=ApiSignatureVerifier(key_provider, NonceCache(300), 60),
    login_tracker=LoginAttemptTracker(window_seconds=300, max_attempts=5, lockout_seconds=900),
)
```

Every guard is optional; with none configured the middleware is a passthrough.
Non-`http` scopes (including `lifespan` and `websocket`) pass straight through.

## Check order

Cheap to expensive, so a rejected request costs as little as possible:

1. **IP blacklist** → 403 `ip_blacklisted`
2. **Bot User-Agent** → 403 `bot_detected`
3. **Request size** → the guard's own status (413 body / 431 headers)
4. **Login lockout** → 429 `account_locked`
5. **HMAC signature** → 401 with the verifier's reason (`missing_header`,
   `bad_timestamp`, `timestamp_skew`, `nonce_replay`, `no_secret`,
   `signature_mismatch`)

The size guard reads `Content-Length` only — it never consumes the request body,
so downstream handlers still see the full stream.

## Login attempt tracking

For paths in `login_paths` (default `/login`, `/api/user/login`, `/oauth2/token`),
the middleware wraps `send` and learns from the downstream response:
2xx → `record_success`, 401/403 → `record_failure`. A locked key is rejected before
the app is called. The tracking key defaults to the client IP; supply `login_key`
to key on a username or tenant instead.

## Client IP and proxies

`scope["client"][0]` is used by default. Set `trust_forwarded=True` to take the
first hop of `X-Forwarded-For` instead — only do this behind a proxy you control,
since the header is client-supplied otherwise.

## Gateway bypass

If `gateway_bypass_header` (default `x-gateway-verified`) is present, signature
verification is skipped, matching the Java interceptor's gateway-bypass behaviour.
Set it to `None` to disable. **Only enable this when a trusted gateway strips or
sets the header**, otherwise a client can forge it.

## Deny responses

Default body is `{"error": "<reason>"}` as JSON with a correct `Content-Length`.
Customise with `deny_renderer(status, reason) -> bytes`, and per-guard statuses via
`deny_status_ip` / `deny_status_bot` / `deny_status_signature` / `deny_status_locked`.
