# atlas-richie-secret-redis

Redis backend for the [atlas-richie-secret-core](../secret-core) secret
platform. Stores AES-256-GCM envelope-encrypted secret values in
Redis, reusing the
[atlas-richie-cache-redis](../cache/cache-redis) infrastructure for
connection pooling, `RedisStringManager`, and `RedisDistributedCache`.

## Why default at-rest encryption

Cache-redis stores plaintext values (cache is performance-oriented, not
security-oriented). Secrets are security-sensitive: a Redis `DUMP` or
side-channel `MONITOR` should never reveal plaintext. R-233.1 therefore
defaults to AES-256-GCM encryption on every `put` / `rotate` and
decryption on every `get`. The encryption key is a 32-byte
locally-managed key loaded via env injection
(`ATLAS_RICHIE_SECRET_REDIS_LOCAL_ENCRYPTION_KEY`).

Future backends (Vault Transit, AWS KMS, PKCS#11 HSM) will replace the
local key with a KMS-wrapped DEK via `KeyWrappingBackend`; the
application code does not change.

## Quick start

```python
import base64
import os

from atlas_richie.secret import (
    GlobalSecret,
    GlobalSecretManager,
    SecretProviderConfiguration,
    SecretReference,
)
from atlas_richie.secret_redis import (
    RedisSecretProperties,
    RedisSecretProviderFactory,
)

# 1. Set a 32-byte AES-256 key (base64) via env injection.
os.environ["ATLAS_RICHIE_SECRET_REDIS_URL"] = "redis://127.0.0.1:16379"
os.environ["ATLAS_RICHIE_SECRET_REDIS_LOCAL_ENCRYPTION_KEY"] = base64.b64encode(
    b"\x00" * 32,
).decode("ascii")

# 2. Build the properties + factory.
properties = RedisSecretProperties()  # env-injected
factory = RedisSecretProviderFactory(properties=properties)

# 3. Construct a session and install via the secret facade.
session = factory.create(SecretProviderConfiguration(name=factory.name))
manager = GlobalSecretManager.from_sessions(
    [session], factories={factory.name: factory},
)
GlobalSecret.install(manager)

# 4. Round-trip a secret.
GlobalSecret.write(
    SecretReference(provider=factory.name, path="db.password"),
    b"sup3rs3cr3t",
)
value = GlobalSecret.resolve(
    SecretReference(provider=factory.name, path="db.password"),
)
assert value.plaintext == b"sup3rs3cr3t"
```

## Key layout

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

## Properties

| Field | Env var | Default | Notes |
|---|---|---|---|
| `url` | `ATLAS_RICHIE_SECRET_REDIS_URL` | (required) | Redis server URL |
| `namespace` | `ATLAS_RICHIE_SECRET_REDIS_NAMESPACE` | `atlas-richie-secret` | Key prefix |
| `local_encryption_key_b64` | `ATLAS_RICHIE_SECRET_REDIS_LOCAL_ENCRYPTION_KEY` | (required) | 32-byte AES-256 key, base64 |
| `default_ttl_seconds` | `ATLAS_RICHIE_SECRET_REDIS_DEFAULT_TTL_SECONDS` | `0` (no expiry) | Per-write TTL |
| `key_purpose` | `ATLAS_RICHIE_SECRET_REDIS_KEY_PURPOSE` | `"encrypt"` | `KeyPurpose` value for AAD |
| `max_connections` | `ATLAS_RICHIE_SECRET_REDIS_MAX_CONNECTIONS` | `50` | Forwarded to `RedisCacheProperties` |
| `socket_timeout` | `ATLAS_RICHIE_SECRET_REDIS_SOCKET_TIMEOUT` | `5.0` | Forwarded |
| `enable_local_lock` | `ATLAS_RICHIE_SECRET_REDIS_ENABLE_LOCAL_LOCK` | `True` | Forwarded |
| `ping_before_activate` | `ATLAS_RICHIE_SECRET_REDIS_PING_BEFORE_ACTIVATE` | `True` | Forwarded |

## Operations

- `put(reference, plaintext) -> SecretValue` — generates a new
  monotonic version via `INCR @counter`, encrypts, persists.
- `rotate(reference, new_plaintext) -> SecretValue` — like `put`, but
  fires a `SecretSnapshotChangedEvent` with the previous metadata.
- `get(reference) -> SecretValue` — reads `@current`, fetches the
  envelope, decrypts.
- `get_version(reference, version) -> SecretValue` — bypasses the
  `@current` pointer and reads a specific version.
- `get_metadata(reference) -> SecretMetadata` — fetches and decrypts;
  metadata (version number, created_at) is part of the encrypted
  envelope so it cannot be tampered with.
- `exists(reference) -> bool` — non-IO-blowing existence check.
- `list(prefix=None) -> list[SecretReference]` — `SCAN`-based
  enumeration of all references whose path starts with `prefix`.
- `delete(reference) -> None` — hard-delete: removes the pointer, the
  counter, and every `@vN` discovered via `SCAN`.

## Capability flags

| Flag | Value |
|---|---|
| `can_read` | `True` |
| `can_write` | `True` |
| `can_rotate` | `True` |
| `can_list` | `True` |
| `encrypts_at_rest` | `True` |
| `signs_values` | `False` (use `DefaultSigningService` to layer ECDSA at app level) |
| `cacheable` | `True` |

## Tests

```bash
# 1. Start a local Redis on port 16379
docker run --rm -p 16379:6379 redis:7-alpine

# 2. Run integration tests
PYTHONPATH=components/secret/secret-redis/src \
PYTHONPATH=components/secret/secret-core/src \
PYTHONPATH=components/cache/cache-redis/src \
python -m pytest components/secret/secret-redis/tests/ -v
```

## License

Apache-2.0
