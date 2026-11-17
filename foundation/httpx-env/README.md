# atlas-richie-httpx-env

Zero-dependency compatibility shims for the process environment HTTPX reads at
client construction.

## Why a separate leaf

The shim is ~60 lines of standard library only. Components that build an
`httpx.Client` directly (secret providers, the `http` facade) all need it, but
none of them should have to install the whole `atlas-richie-http` facade —
interceptor chain, SSE parser, models, errors — just to obtain a context
manager. This package carries **no runtime dependencies**, so depending on it
adds no transitive weight.

## Usage

```python
from atlas_richie.httpx_env import no_proxy_ipv6_guard

with no_proxy_ipv6_guard():
    client = httpx.Client(timeout=...)
```

Wrap the construction call only. Clients built with an explicit `transport=`
never read environment proxies and do not need the guard.

## `no_proxy_ipv6_guard`

httpx 0.28.1 does not recognise `[::1]` in `NO_PROXY` as an IPv6 address. The
entry falls through to the domain-wildcard branch and produces the unparseable
pattern `all://*[::1]`, so **any** client construction raises
`httpx.InvalidURL: Invalid port: ':1]'`.

The guard strips the redundant brackets from IPv6 entries in `NO_PROXY` and
`no_proxy` for the duration of the construction, then restores the original
values. Brackets carry no meaning for host classification, so proxy-bypass
semantics are unchanged. The transformation is idempotent and
semantics-preserving, which is why a concurrent construction observing the
normalised value behaves identically.

Only entries that actually parse as IPv6 are rewritten; anything else
(including non-IP bracketed text) is left untouched. When no entry needs
rewriting the environment is not modified at all.

## Contract

- Runtime dependencies: **none**. Standard library only.
- Must never import `httpx` — enforced by `tools/dependency-check/check_core_imports.py`.
- Remove this package once a released httpx version handles bracketed IPv6
  `NO_PROXY` entries; 0.28.1 is the latest stable at the time of writing.
