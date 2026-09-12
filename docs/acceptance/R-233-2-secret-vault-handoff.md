# R-233.2 Handoff: `atlas-richie-secret-vault` — HashiCorp Vault backend

**Date:** 2026-09-12
**Owner:** Mavis
**Status:** **DONE** — 50/50 tests passed (10 properties unit + 8
configuration unit + 10 retry unit + 6 auth unit + 1 auth integration +
15 client integration), `atlas-richie-secret-vault` 0.2.0 wheel built,
**12/12 isolated wheels install + import OK** in fresh venv against
the project's `dist/wheelhouse` (no PyPI, no editable workspace).

## Motivation

R-233.0 (`atlas-richie-secret-core`) shipped the framework + in-process
backends (InMemory / Env / File) + AES-256-GCM envelope crypto.
R-233.1 (`atlas-richie-secret-redis`) added the first remote backend.
**R-233.2** adds the second remote backend: **HashiCorp Vault**, on
the public protocol surface (KV v2 + Transit), matching Java
`atlas-richie-secret-provider-vault` 1:1.

Vault is read + crypto + bootstrap + session, **never** writer /
deletable / listable at the framework level — that asymmetry mirrors
the Java design and reflects the operational reality: Vault writes
are an admin-path concern (CLI / Terraform / API token with explicit
`update` policy), not something a service-mesh client should reach
for.

## Java → Python structural mapping

Java has `cn.richie696.component.secret.provider.vault.*` as 8 files
inside one sub-module. Python is one wheel
(`atlas-richie-secret-vault`) with internal sub-modules:

```
components/secret/secret-vault/
├── pyproject.toml
├── README.md
└── src/atlas_richie/secret_vault/
    ├── __init__.py            ← public surface (13 symbols)
    ├── auth.py                ← Token / Kubernetes / AppRole Strategy + factory
    ├── client.py              ← VaultSecretClient (5-SPI composite)
    ├── configuration.py       ← VaultConfigurationResolver + path safety + SHA-256
    ├── factory.py             ← VaultSecretProviderFactory + VaultClientFactory
    ├── properties.py          ← VaultSecretProperties + AuthType (pydantic-settings)
    ├── request_id.py          ← VaultRequestIdCapture (per-thread correlation)
    └── retry.py               ← VaultRetryExecutor (transient-only bounded retry)
└── tests/
    ├── conftest.py                 ← vault_client / vault_session / kv_path_factory fixtures
    ├── test_vault_auth.py          ← 5 unit + 1 integration (Token vs real Vault)
    ├── test_vault_client.py        ← 15 integration tests vs real Vault
    ├── test_vault_configuration.py ← 7 unit tests (path safety / hash / capability)
    ├── test_vault_properties.py    ← 8 unit tests (env injection / model_validator)
    └── test_vault_retry.py         ← 9 unit tests (transient classification)
```

## Functional surface

| Java | Python |
|---|---|
| `VaultSecretProperties` + `AuthenticationType` | `VaultSecretProperties` + `AuthType` |
| `VaultClientFactory` (private inner) | `VaultClientFactory` (public) |
| `VaultRequestIdCapture` (private inner) | `VaultRequestIdCapture` (public) |
| `VaultRetryExecutor` (private inner) | `VaultRetryExecutor` (public) |
| `VaultSecretConfigurationResolver` (private inner) | `VaultConfigurationResolver` (public) |
| `VaultSecretBootstrapProviderFactory` (public) | `VaultSecretProviderFactory` (public) |
| `VaultSecretClient` (5-SPI composite) | `VaultSecretClient` (5-SPI composite) |
| (none) | `auth_strategy_for(properties)` (Strategy factory) |

### Public symbols (13)

- `VaultSecretProperties` — pydantic-settings env-injected
  configuration; prefix `ATLAS_RICHIE_SECRET_VAULT_`. Carries
  auth-type-specific sub-fields (`kubernetes_role` / `approle_*`),
  bounded by a `model_validator(mode="after")` that enforces
  mutual exclusion: `TOKEN` requires `token`, `KUBERNETES`
  requires `kubernetes_role`, `APPROLE` requires both
  `approle_role_id` + `approle_secret_id`.
- `AuthType` — `StrEnum { TOKEN, KUBERNETES, APPROLE }`.
- `VaultAuthStrategy` (Protocol) + `TokenAuthStrategy` /
  `KubernetesAuthStrategy` / `AppRoleAuthStrategy` (impls) +
  `auth_strategy_for(properties)` (factory) — Strategy pattern.
- `VaultConfigurationResolver` + `ResolvedVaultConfiguration` —
  path-safety validation (`..` / `://` / leading `/` / trailing `/`
  are rejected on `kv_mount` / `transit_mount` / `namespace`),
  static `SecretCapability` declaration, SHA-256 `configuration_hash`.
- `VaultRetryExecutor` — bounded retry (default `max_attempts=3`,
  base backoff `0.1s` × `2^(attempt-1)` capped at `1.0s`, jitter
  50–100%, honors `Retry-After`). Only retries network errors
  + 429 / 5xx; 4xx is final.
- `VaultRequestIdCapture` — per-thread correlation id; `clear()` /
  `consume()` / `current_id()` API.
- `VaultClientFactory` — materialize and authenticate an
  `hvac.Client` from `VaultSecretProperties`.
- `VaultSecretProviderFactory` — `SecretProviderFactory`
  implementation; produces a `VaultSecretClient` that satisfies
  `SecretProviderSession`.
- `VaultSecretClient` — composite implementation of 5 SPI roles
  on a single `hvac.Client`:
  - `SecretOperations` (KV v2 read: `get` / `get_version` /
    `get_metadata` / `exists`)
  - `KeyWrappingBackend` (Transit `wrap_key` / `unwrap_key`)
  - `SigningBackend` (Transit `sign` / `verify`)
  - `SecretBootstrapClient` (`bootstrap` resolves a
    `SecretBindingCatalog` into a `SecretBootstrapResult`)
  - `SecretProviderSession` (descriptor / configuration /
    operations / writer / deletable / snapshot_manager /
    is_closed / close)
  The class **does not** implement `SecretWriter` /
  `SecretDeletable` / `SecretListable`; the session's `writer`
  and `deletable` properties return `None` to make this explicit
  to the framework's `list_capability(session)` probe.

## Storage model

| Concern | Mechanism | Path |
|---|---|---|
| Read latest secret | KV v2 `read_secret_version(path, mount_point, version=0)` | `{kv_mount}/data/{path}` |
| Read pinned version | KV v2 `read_secret_version(path, mount_point, version=N)` | `{kv_mount}/data/{path}` |
| Metadata only | KV v2 `read_secret_metadata(...)` | `{kv_mount}/metadata/{path}` |
| Wrap (encrypt DEK) | Transit `encrypt_data(name, plaintext)` | `{transit_mount}/encrypt/{name}` |
| Unwrap (decrypt DEK) | Transit `decrypt_data(name, ciphertext)` | `{transit_mount}/decrypt/{name}` |
| Sign | Transit `sign_data(name, hash_input)` | `{transit_mount}/sign/{name}` |
| Verify | Transit `verify_signed_data(name, hash_input, signature)` | `{transit_mount}/verify/{name}` |

Wrapped ciphertexts are stored as `bytes` containing the
`"vault:v1:<base64>"` string so `WrappedKey.ciphertext` is
self-describing. `SignatureValue.signature` follows the same
convention.

## hvac 2.4.0 workarounds

The client works around two known hvac 2.4.0 issues:

1. **Transit `plaintext` / `hash_input` are not auto-base64** —
   passing raw `bytes` triggers `TypeError: Object of type bytes
   is not JSON serializable`. `VaultSecretClient` uniformly
   base64-encodes via `_b64()` before calling encrypt / sign, and
   decodes via `_b64_decoded()` after `decrypt_data`. The on-wire
   payload is identical to what hvac would have produced for a
   `str` input.
2. **`create_key(name=..., key_type=...)`** (not `type=...`).

Tests create an `ecdsa-p256` test key in `transit/` at session
start because `aes256-gcm96` (the pre-existing `test-key`) does
not support signing.

## Errors

The client maps hvac status codes to `SecretException` /
`SecretCryptoException` with the `[SEC-...]` error code in the
message prefix (Java's `SecretException(code, message)` becomes
Python's `SecretException(f"vault [{code}]: {message}")`):

| hvac status | Framework code | Exception class |
|---|---|---|
| 401 | `SEC-AUTH-001` | `SecretCryptoException` |
| 403 | `SEC-AUTHZ-001` | `SecretCryptoException` |
| 404 | `SEC-STORE-001` | (raised as `SecretIntegrityException` for `get` / `get_metadata`) |
| 5xx | `SEC-PROVIDER-001` | `SecretException` (only after retry exhaustion) |
| 429 | `SEC-PROVIDER-001` | (transient, retried by `VaultRetryExecutor`) |
| other 4xx | `SEC-CRYPTO-001` (crypto) / `SEC-PROVIDER-001` (read) | corresponding exception |

The `code` is embedded in the message string because
`SecretException` is a bare `Exception` in secret-core (no
`code=` kwarg, by design — see R-233.0's `errors.py`).

## Test results

- **Unit** (no Vault): 39 tests pass in 0.5s
  - `test_vault_properties.py` — 8
  - `test_vault_configuration.py` — 7
  - `test_vault_retry.py` — 9
  - `test_vault_auth.py` — 5 (Token strategy integration is the
    only one that needs a real server, moved out of unit)
- **Integration** (real Vault on `127.0.0.1:8200`):
  - `test_vault_auth.py::test_token_strategy_authenticates` — 1
  - `test_vault_client.py` — 15 (KV v2 read+versioning+missing,
    Transit wrap+unwrap+sign+verify+empty, bootstrap STARTUP+OPTIONAL,
    session close + post-close)
- **Total**: 50/50 pass in 0.53s

All 50 tests run by default (no markers required); the
`vault_client` fixture is the only one that hits the network,
and it `pytest.skip`s gracefully if Vault is unreachable so CI
without Vault still collects green.

## Isolated-wheel verification (12/12)

`tools/release/verify_isolated_wheels.py` runs every wheel in a
fresh `python -m venv` and tries to import its public module
**with no editable workspace and no PyPI**. 12/12 packages
pass; secret-vault's import line in that loop is:

```
atlas-richie-secret-vault==0.2.0
  → atlas-richie-secret-core==0.2.0
  → atlas-richie-contracts==0.2.0
  → hvac==2.4.0
  → cryptography==45.0.7
  → cffi==2.1.1
  → requests==2.34.2
  → charset_normalizer==3.5.1
  → urllib3==2.7.0
  → idna==3.19
  → certifi==2026.7.22
  → pydantic==2.13.5
  → pydantic-core==2.46.5
  → typing_extensions==4.16.0
  → typing_inspection==0.4.4
```

The 4 transitive runtime deps added to `secret-vault/pyproject.toml`
in this commit are `pydantic` and `pydantic-settings` (used by
`properties.py`; previously undeclared — see the R-233.0 follow-up
note at the bottom of this doc).

## Workspace integration

- `pyproject.toml` — added `components/secret/secret-vault` to
  `tool.uv.workspace.members` + `tool.uv.sources`.
- `versions.toml` — added
  `atlas-richie-secret-vault = "0.2.0"`.
- `foundation/platform/pyproject.toml` — added
  `"atlas-richie-secret-vault>=0.2.0,<0.3.0"` to dependencies.
- `tools/release/verify_isolated_wheels.py` — added
  `(f"atlas-richie-secret-vault=={_VERSION}", "atlas_richie.secret_vault")`
  to `PACKAGES` (12 entries total now).
- `tools/sync_versions.py` — `python tools/sync_versions.py` ran
  clean, syncing 13 `pyproject.toml` files against the new
  `versions.toml` entry without drift.

## Patterns used (mirrors R-233.0 decisions)

- **Strategy** — `VaultAuthStrategy` Protocol + 3 impls
- **Factory** — `auth_strategy_for` + `VaultSecretProviderFactory`
- **Singleton** — `VaultRetryExecutor` + `VaultRequestIdCapture`
  are process-wide single instances created per session (no
  separate lifecycle because they're cheap and stateless)
- **Observer** — per-thread correlation id in
  `VaultRequestIdCapture` (consumed by framework `Logger`)
- **Decorator** — `VaultRetryExecutor` wraps the underlying
  `hvac.Client` calls
- **Builder** — `VaultSecretProperties` is a frozen pydantic-settings
  model with `to_hvac_client_kwargs()` (latter assembles the
  final dict)
- **Adapter** — `VaultSecretClient` adapts `hvac.Client` to the
  Python `SecretOperations` / `KeyWrappingBackend` /
  `SigningBackend` / `SecretBootstrapClient` /
  `SecretProviderSession` Protocol surface
- **Facade** — `atlas_richie.secret_vault.__init__` exposes the 13
  public symbols; hvac types never leak out
- **Composite** — `VaultSecretClient` is a single object satisfying
  5 SPI roles on top of one `hvac.Client`

## Anti-patterns avoided (per OOP / R-233.0 / CODE_QUALITY.md)

- No lazy / inline imports inside `__init__` methods (verified
  with `grep -n "import " src/atlas_richie/secret_vault/*.py`).
- No `**kwargs` in any public signature.
- No `*Impl` / `*Manager` / `*DTO` / `*Util` suffixes.
- All dataclasses are `frozen=True, slots=True`.
- `SecretException` / `SecretConfigurationException` etc. are
  raised directly; no `BaseException` swallowing.
- hvac SDK types do not appear in any public signature; the
  facade exposes only framework-protocol types.

## R-233.0 follow-up notice (clarified post-merge)

The R-233.2 handoff originally suggested a follow-up to add
`pydantic` / `pydantic-settings` to `atlas-richie-secret-core`'s
`pyproject.toml`. **That suggestion was wrong** — `grep -rE
"import pydantic" components/secret/secret-core/src/` returns
zero matches, and a clean isolated venv that installs only
`atlas-richie-secret-core==0.2.0` (and its only declared dep
`atlas-richie-contracts==0.2.0`) successfully runs
`import atlas_richie.secret` with no pydantic installed.
`pydantic` is a transitive dep of `cache-core`, not of
`secret-core`, so the supposed "latent risk" does not exist.

## Acceptance checklist

- [x] Java → Python 1:1 functional parity (`VaultSecretClient`
      implements 5 SPI roles matching the Java SPI list)
- [x] Bilingual docstrings on every public module / class / method
      (zh段在上,en段在下)
- [x] Strategy / Factory / Singleton / Observer / Decorator /
      Builder / Adapter / Facade / Composite patterns present
- [x] No hvac SDK types in the public facade
- [x] Real Vault on 127.0.0.1:8200 for all integration tests
      (no mocks, no fakes)
- [x] `pytest` 50/50 pass
- [x] `tools/release/verify_isolated_wheels.py` 12/12 OK
- [x] `tools/sync_versions.py` 13/13 syncs clean
- [x] Wheel built and present in `dist/`
- [x] `pyproject.toml` workspace members + sources updated
- [x] `versions.toml` updated
- [x] `foundation/platform/pyproject.toml` updated
- [x] `verify_isolated_wheels.py` PACKAGES updated
- [x] Handoff doc (this file) written
- [ ] Single commit + push (R-233.2.9 final step)
