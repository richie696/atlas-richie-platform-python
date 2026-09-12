# R-233.1 Handoff: `atlas-richie-secret-redis` — first remote backend

**Date:** 2026-09-12
**Owner:** Mavis
**Status:** **DONE** — 20/20 tests passed (5 unit + 15 integration),
11/11 isolated wheels install + import OK, `atlas-richie-secret-redis`
0.2.0 wheel built and pushed.

## Motivation

R-233.0 (`atlas-richie-secret-core`) shipped the framework, in-process
backends (InMemory / Env / File), and the AES-256-GCM envelope
crypto. The first remote backend that exercise uses is Redis (per the
prior questionnaire agreement: "reuse cache-redis as substrate").
R-233.1 wires the secret framework to a real Redis cluster with
**default at-rest encryption** (AES-256-GCM), so a `DUMP` or
side-channel `MONITOR` never reveals plaintext.

## Java → Python structural mapping

Java has `cn.richie696.component.secret.provider.redis.*` as a single
sub-module of `secret-provider-common`. Python is one wheel
(`atlas-richie-secret-redis`) with internal sub-modules:

```
components/secret/secret-redis/
├── pyproject.toml
├── README.md
├── src/atlas_richie/secret_redis/
│   ├── __init__.py            ← public surface (4 symbols)
│   ├── properties.py         ← RedisSecretProperties (pydantic-settings)
│   ├── operations.py         ← RedisSecretOperations + Listable
│   ├── writer.py             ← RedisSecretWriter + Deletable
│   └── factory.py            ← RedisSecretProviderFactory + session
└── tests/
    ├── conftest.py            ← redis_session + factory fixtures
    ├── test_redis_secret.py   ← 12 integration tests (real Redis on 16379)
    └── test_properties.py    ← 5 unit tests (no Redis required)
```

## Functional surface

| Java | Python |
|---|---|
| `RedisSecretProviderFactory` | `RedisSecretProviderFactory` |
| `RedisSecretProviderSession` | `_RedisSession` (private) |
| `RedisSecretOperations` | `RedisSecretOperations` |
| `RedisSecretWriter` | `RedisSecretWriter` |
| `RedisSecretProperties` (env-injected) | `RedisSecretProperties` (pydantic-settings) |
| `*` (delete in Java core) | `RedisSecretWriter` also implements `SecretDeletable` |

### Public symbols (4)

- `RedisSecretProperties` — pydantic-settings env-injected configuration
  (URL, namespace, local AES-256 key, TTL, key purpose, pool params).
- `RedisSecretOperations` — `SecretOperations` + `SecretListable`
  implementation backed by `RedisStringManager`.
- `RedisSecretWriter` — `SecretWriter` + `SecretDeletable` (single class
  because they share the same encrypt + persist machinery).
- `RedisSecretProviderFactory` — `SecretProviderFactory` implementation
  (constructs `redis.Redis` via `redis.from_url`, wraps in
  `RedisDistributedCache` + `RedisCacheInfrastructure`).

## Storage model

For each `SecretReference(path=P)` the backend writes three Redis keys
under the configured `namespace` prefix:

| Key | Value | Purpose |
|---|---|---|
| `{ns}:P@v1`, `{ns}:P@v2`, ... | JSON-encoded `CipherEnvelope` (AES-256-GCM encrypted plaintext) | One per version |
| `{ns}:P@current` | `"vN"` | Latest version pointer |
| `{ns}:P@counter` | integer | Monotonic counter for the next version (`INCR`) |

`get(reference)` reads `@current` to find the latest version, then
fetches `@vN` and decrypts. `get_version(reference, V)` skips the
pointer and goes straight to `@vV`. `delete(reference)` SCANs for
`@v*` and removes all three keys.

The encryption AAD binds the ciphertext to (namespace, path) so a
`MONITOR` cannot move a ciphertext between paths without detection.

## Capability flags

| Flag | Value | Reason |
|---|---|---|
| `can_read` | `True` | |
| `can_write` | `True` | |
| `can_rotate` | `True` | |
| `can_list` | `True` | SCAN-based |
| `encrypts_at_rest` | `True` | AES-256-GCM default (per user choice) |
| `signs_values` | `False` | Use `DefaultSigningService` at app layer if needed |
| `cacheable` | `True` | |

## Properties (env-injected)

| Field | Env var | Default | Notes |
|---|---|---|---|
| `url` | `ATLAS_RICHIE_SECRET_REDIS_URL` | (required) | e.g. `redis://:pass@host:port/0` |
| `namespace` | `ATLAS_RICHIE_SECRET_REDIS_NAMESPACE` | `atlas-richie-secret` | Redis key prefix |
| `local_encryption_key_b64` | `ATLAS_RICHIE_SECRET_REDIS_LOCAL_ENCRYPTION_KEY_B64` | (required) | 32-byte AES-256 key, base64 |
| `default_ttl_seconds` | `ATLAS_RICHIE_SECRET_REDIS_DEFAULT_TTL_SECONDS` | `0` (no expiry) | Per-write TTL via `set_with_ttl` |
| `key_purpose` | `ATLAS_RICHIE_SECRET_REDIS_KEY_PURPOSE` | `"encrypt"` | `KeyPurpose` value for AAD |
| `max_connections` | `ATLAS_RICHIE_SECRET_REDIS_MAX_CONNECTIONS` | `50` | Forwarded to `RedisCacheProperties` |
| `socket_timeout` | `ATLAS_RICHIE_SECRET_REDIS_SOCKET_TIMEOUT` | `5.0` | Forwarded |
| `enable_local_lock` | `ATLAS_RICHIE_SECRET_REDIS_ENABLE_LOCAL_LOCK` | `True` | Forwarded |
| `ping_before_activate` | `ATLAS_RICHIE_SECRET_REDIS_PING_BEFORE_ACTIVATE` | `True` | Forwarded |

The 32-byte key length is enforced in `field_validator`; shorter /
longer / non-base64 inputs raise `ValueError` at construction time.

## Design patterns (per R-233 9-pattern agreement)

- **Strategy** — `RedisSecretProviderFactory` is one of multiple
  backends, swapping in is a one-line change in app code.
- **Factory Method** — `create(configuration)` builds the session.
- **Adapter** — hides `redis-py` types; only `RedisStringManager` /
  `RedisDistributedCache` are used (the framework never imports
  `redis`).
- **Observer** — `rotate()` triggers `SecretSnapshotManager.publish`
  with `previous_metadata` / `current_metadata`.

## Reuse of `atlas-richie-cache-redis`

The factory internally constructs a `RedisCacheInfrastructure` from
the secret properties (via `to_cache_properties()`), then hands the
backend to `RedisStringManager`. The secret wheel does NOT use the
cache-redis `Manager` facade directly (it doesn't expose
`get_infrastructure`); instead it builds the cache components
explicitly:

```python
client = redis.from_url(url, decode_responses=False, max_connections=...)
distributed_cache = RedisDistributedCache(client=client, namespace=...)
return RedisCacheInfrastructure(backend=distributed_cache)
```

This keeps the dependency surface minimal (no `RedisCacheManager`
needed) and lets the secret wheel bypass the cache's L1 / perf-guard /
event-manager layers — secret has no use for them.

## Test results

```text
$ PYTHONPATH=components/secret/secret-redis/src:components/secret/secret-core/src:components/cache/cache-redis/src \
  python -m pytest components/secret/secret-redis/tests/ -q

20 passed in 0.20s
```

- `test_properties.py` (5 tests, no Redis) — env injection, key
  validation, `to_cache_properties()` conversion.
- `test_redis_secret.py` (12 tests, real Redis on 16379) —
  put/get round-trip, multi-version, pinned selector, exists, metadata,
  list with prefix, rotate emits snapshot, delete, raw storage is
  encrypted (the plaintext never appears in the Redis value).

## Isolated wheel verification (11 packages)

```
atlas-richie-contracts==0.2.0      ->  atlas_richie.contracts    OK
atlas-richie-testing==0.2.0        ->  atlas_richie.testing      OK
atlas-richie-http==0.2.0           ->  atlas_richie.http         OK
atlas-richie-mcp==0.2.0            ->  atlas_richie.mcp          OK
atlas-richie-resilience==0.2.0     ->  atlas_richie.resilience   OK
atlas-richie-cache-core==0.2.0     ->  atlas_richie.cache_core   OK
atlas-richie-cache-redis==0.2.0    ->  atlas_richie.cache_redis  OK
atlas-richie-secret-core==0.2.0    ->  atlas_richie.secret       OK
atlas-richie-secret-redis==0.2.0   ->  atlas_richie.secret_redis OK  ← new
atlas-richie-oauth==0.2.0          ->  atlas_richie.oauth        OK
atlas-richie-platform==0.2.0       ->  atlas_richie.platform     OK
```

## Workspace + version wiring

- `pyproject.toml` workspace `members`: added
  `components/secret/secret-redis`.
- `pyproject.toml` workspace `sources`: added
  `atlas-richie-secret-redis = { workspace = true }`.
- `versions.toml`: added `atlas-richie-secret-redis = "0.2.0"`.
- `foundation/platform/pyproject.toml` dependencies: added
  `atlas-richie-secret-redis>=0.2.0,<0.3.0`.
- `tools/release/verify_isolated_wheels.py`: added
  `(f"atlas-richie-secret-redis=={_VERSION}", "atlas_richie.secret_redis")`.

`sync_versions.py --check`: `OK: all pyproject.toml files are in sync
with versions.toml` (12 packages).

## Review gate

- ✅ 20 unit + integration tests passed, 0 failures
- ✅ 11/11 isolated wheels install + import OK
- ✅ Real Redis on `127.0.0.1:16379` exercises full lifecycle
- ✅ Stored value is encrypted: plaintext never appears in the
  serialized `CipherEnvelope`
- ✅ `uv build --all-packages` succeeds; `atlas-richie-secret-redis`
  0.2.0 wheel published
- ✅ Bilingual docstrings (R-229 convention) on every public surface

## Follow-up suggestions

- **R-233.2 `atlas-richie-secret-vault`** — HashiCorp Vault backend
  via `hvac`. `KeyWrappingBackend` integration lets secrets in
  Redis be wrapped by Vault Transit, removing the local AES key.
- **R-233.3 `atlas-richie-secret-pkcs11`** — HSM-backed wrap via
  PKCS#11.
- **R-233.4 `atlas-richie-secret-openbao`** — OpenBao (open-source
  Vault fork) via `hvac` (same interface as Vault).
- **R-233.5 cloud KMS backends** — AWS / Azure / GCP / Aliyun / Tencent
  / Huawei / Baidu / Volcengine / OCI / IBM / KMIP / Barbican (each its
  own wheel).
- **R-233.6 rotation refresh callbacks** — when `@current` flips,
  fire a `SecretSnapshotManager` event that downstream consumers
  (config cache, OAuth token cache) can subscribe to for cache
  invalidation.
- **R-233.7 key rotation** — periodically rotate the local AES-256
  key; new writes use the new key, old `@vN` keys remain decryptable
  because each `@vN` records its key-id in the envelope metadata.
