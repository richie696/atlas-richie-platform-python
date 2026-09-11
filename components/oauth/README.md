# Atlas Richie OAuth Component

Framework-neutral OAuth 2.1 client and resource-server contracts.  It owns
metadata parsing, secure endpoint policy, PKCE S256, token lifecycle and
resource/audience/scope checks.  It does not host an Authorization Server,
store refresh tokens, render login/consent pages, or depend on a Python web
framework.

`atlas-richie-oauth-jose` is the explicit JOSERFC-based JWT/JWKS
adapter.  The core package intentionally exposes no JOSE-library types.
