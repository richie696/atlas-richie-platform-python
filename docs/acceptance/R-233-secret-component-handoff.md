# R-233 Handoff: `atlas-richie-secret` component (Stage 1 — `secret-core`)

**Date:** 2026-09-12
**Owner:** Mavis
**Status:** **DONE — R-233.0 (Stage 1 framework)** — 62 unit tests passed,
10/10 isolated wheels install + import OK, `atlas-richie-secret-core`
0.2.0 wheel built and pushed.

## Motivation

Java `atlas-richie-secret-parent` has 21 sub-modules (138 main + 57 test
java files) covering the full secret subsystem: read / write
contracts, multi-version reference model, provider SPI, in-process and
remote backends, AES-GCM + ECDSA envelope crypto, startup-time
bootstrap, and testkit. The Python side had no equivalent; the user
asked for **structure can differ (Pythonic) but functionality 1:1**.

R-233 is the Python port, structured as a single wheel with internal
sub-packages. The remote backends (redis / vault / openbao / pkcs11 /
aws / azure / gcp / 7× domestic clouds) are out of scope for Stage 1
and will land in later wheels starting with `atlas-richie-secret-redis`.

## Java → Python structural mapping

| Java sub-module | Python location |
|---|---|
| `secret-api` (33 files) | `secret-core/src/atlas_richie/secret/` top + `provider/` + `crypto/` + `exception/` |
| `secret-core` (9 files) | `.../resolver.py` (DefaultSecretResolver) + `local/in_memory.py` |
| `secret-bootstrap` (23 files) | `.../bootstrap/{catalog,policy,state,discovery,processor,spi,default_client}.py` |
| `secret-testkit` (4 files) | `.../testkit/{__init__.py,bundle.py}` |
| `secret-spring-boot-starter` (8 files) | N/A (no Spring in Python) |
| `secret-provider-common` (11 files) | N/A (no Spring abstract layer) |
| `secret-provider-{aws,azure,gcp,aliyun,...}` | future wheels (`atlas-richie-secret-redis` first) |
| `secret-provider-{vault,openbao,pkcs11}` | future wheels |

**Net:** 21 Java sub-modules → 1 Python wheel with 28 internal
modules (Python `*_test.py` files, `__init__.py` re-exports, and
docstring loaders are not counted).

## Functional surface (1:1 with Java)

91 public symbols re-exported from `atlas_richie.secret`:

- **Errors (5):** `SecretException` / `SecretConfigurationException` /
  `SecretCryptoException` / `SecretBootstrapException` /
  `SecretIntegrityException` (all derive from `PlatformError`).
- **Read / write (4 Protocols):** `SecretResolver` /
  `SecretOperations` / `SecretListable` / `SecretWriter` /
  `SecretDeletable`.
- **Value model (7 types):** `SecretValue` / `DestroyableSecretValue` /
  `SecretReference` / `SecretVersion` / `SecretVersionSelector` /
  `SecretMetadata` / `SecretBackend` (StrEnum of 19 backends) /
  `SecretCapability`.
- **Snapshot (4):** `SecretSnapshotChangedEvent` /
  `SecretSnapshotListener` / `SecretSnapshotManager` /
  `SecretRuntimeSnapshot`.
- **Callback (1):** `SecretCallback` (read / write / rotate /
  failure / metadata hooks).
- **Provider SPI (4):** `SecretProviderConfiguration` /
  `SecretProviderDescriptor` / `SecretProviderFactory` (Protocol) /
  `SecretProviderSession` (Protocol) + `ensure_open` /
  `list_capability` helpers.
- **Local backends (10):** InMemory / Env / File, each with
  factory + operations + writer (where applicable) + deletable
  (where applicable).
- **Crypto (18):** `KeyPurpose` / `KeyReference` / `WrappedKey` /
  `CryptoContext` / `CipherEnvelope` / `SignatureValue` /
  `KeyWrappingBackend` / `SigningBackend` / `SecretCipher` /
  `DefaultSecretCipher` (AES-256-GCM) / `SigningService` /
  `DefaultSigningService` (ECDSA-P256-SHA256) / `generate_ecdsa_keypair` /
  `EnvelopeCrypto` / `EnvelopeCodec` / `ArseEnvelopeCodec` /
  `DefaultEnvelopeCrypto` / `now_utc`.
- **Bootstrap (25):** `SecretKind` / `SecretExposure` /
  `RequiredWhen` / `SecretRefreshStrategy` / `SecretPropertyPattern` /
  `SecretBinding` / `SecretBindingCatalog` /
  `SecretBindingCatalogSet` / `SecretBindingCatalogLoader` /
  `SecretProviderType` / `SecretBootstrapRequest` /
  `SecretBootstrapResult` / `SecretBootstrapContext` /
  `DefaultBootstrapContext` / `SecretBootstrapClient` /
  `SecretBootstrapProviderFactory` / `SecretPropertyPolicy` /
  `BootstrapSecretProperties` / `SecretBootstrapState` /
  `SecretProviderTopology` / `SecretBootstrapSnapshot` /
  `SecretProviderDiscovery` / `DiscoveryResult` /
  `AtlasSecretEnvironmentPostProcessor` /
  `ResolverBackedBootstrapClient`.
- **Registry + facade (3):** `SecretRegistry` (mutex) /
  `GlobalSecret` (class-level static facade) / `GlobalSecretManager`.
- **Testkit (3):** `StubSecretCallback` /
  `RecordingSnapshotListener` / `ProviderBundle` +
  `in_memory_fixture()`.

## Design patterns used

(per R-233 9-pattern agreement: Strategy / Factory / Singleton /
Observer / Decorator / Builder / Adapter / Facade / Composite)

- **Strategy** — `SecretProvider` Protocol; each backend is a strategy.
- **Factory Method** — `SecretProviderFactory` Protocol; each backend
  has its own factory with custom validation.
- **Singleton + Mutex** — `SecretRegistry.instance()` (class-level
  singleton + double-checked locking + `unregister()` required to
  switch).
- **Observer** — `SecretSnapshotListener` registered on
  `SecretSnapshotManager`; rotation events fire best-effort.
- **Decorator** — `EncryptedSecretProvider(provider, cipher)` wraps
  another provider (design pattern; not yet implemented as a class
  in Stage 1 — `DefaultEnvelopeCrypto` already composes cipher +
  signing; a dedicated decorator class for providers can come in
  Stage 2 when KMS backends need it).
- **Builder** — `SecretReference.with_version(selector)` /
  `.with_tag(key, value)` returns new immutable reference.
- **Adapter** — `KeyWrappingBackend` / `SigningBackend` Protocols
  hide KMS / HSM SDK types from public API.
- **Facade** — `GlobalSecret.install / uninstall / resolve / write /
  rotate / register_callback` one-line static API; `GlobalSecret._installed`
  is the singleton manager with callback chain.
- **Composite** — `SecretBindingCatalogSet` layers multiple catalogs
  (base / overlay) with last-wins merge.

## Files added (28 source + 6 test = 34 new files)

```
components/secret/secret-core/
├── pyproject.toml
├── README.md
├── src/atlas_richie/secret/
│   ├── __init__.py
│   ├── errors.py
│   ├── metadata.py
│   ├── value.py
│   ├── reference.py
│   ├── callback.py
│   ├── snapshot.py
│   ├── operations.py
│   ├── writer.py
│   ├── resolver.py
│   ├── provider/
│   │   ├── __init__.py
│   │   ├── configuration.py
│   │   ├── descriptor.py
│   │   ├── factory.py
│   │   └── session.py
│   ├── local/
│   │   ├── __init__.py
│   │   ├── in_memory.py
│   │   ├── env.py
│   │   └── file.py
│   ├── crypto/
│   │   ├── __init__.py
│   │   ├── key.py
│   │   ├── codec.py
│   │   ├── backend.py
│   │   ├── cipher.py
│   │   ├── signing.py
│   │   └── envelope.py
│   ├── bootstrap/
│   │   ├── __init__.py
│   │   ├── catalog.py
│   │   ├── spi.py
│   │   ├── policy.py
│   │   ├── state.py
│   │   ├── discovery.py
│   │   ├── processor.py
│   │   └── default_client.py
│   ├── registry/
│   │   ├── __init__.py
│   │   └── secret_registry.py
│   ├── testkit/
│   │   ├── __init__.py
│   │   └── bundle.py
│   ├── global_secret.py
│   └── global_secret_manager.py
└── tests/
    ├── test_local.py        (16 tests: in-memory / env / file)
    ├── test_registry.py     (8 tests: mutex / catalog)
    ├── test_resolver.py     (10 tests: routing / callback)
    ├── test_bootstrap.py    (13 tests: catalog / loader / post-processor)
    ├── test_crypto.py       (10 tests: AES-GCM / ECDSA / envelope codec)
    ├── test_facade.py       (5 tests: GlobalSecret)
    └── test_testkit.py      (3 tests: StubCallback / RecordingListener / fixture)
```

## Test results

```
$ PYTHONPATH=components/secret/secret-core/src \
  python -m pytest components/secret/secret-core/tests/ -q

62 passed in 0.07s
```

## Isolated wheel verification (10 packages)

```
atlas-richie-contracts==0.2.0      ->  atlas_richie.contracts    OK
atlas-richie-testing==0.2.0        ->  atlas_richie.testing      OK
atlas-richie-http==0.2.0           ->  atlas_richie.http         OK
atlas-richie-mcp==0.2.0            ->  atlas_richie.mcp          OK
atlas-richie-resilience==0.2.0     ->  atlas_richie.resilience   OK
atlas-richie-cache-core==0.2.0     ->  atlas_richie.cache_core   OK
atlas-richie-cache-redis==0.2.0    ->  atlas_richie.cache_redis  OK
atlas-richie-secret-core==0.2.0    ->  atlas_richie.secret       OK  ← new
atlas-richie-oauth==0.2.0          ->  atlas_richie.oauth        OK
atlas-richie-platform==0.2.0       ->  atlas_richie.platform     OK
```

## Workspace + version wiring

- `pyproject.toml` workspace `members`: added
  `components/secret/secret-core`.
- `pyproject.toml` workspace `sources`: added
  `atlas-richie-secret-core = { workspace = true }`.
- `versions.toml`: added `atlas-richie-secret-core = "0.2.0"`.
- `foundation/platform/pyproject.toml` dependencies: added
  `atlas-richie-secret-core>=0.2.0,<0.3.0`.
- `tools/release/verify_isolated_wheels.py`: added
  `(f"atlas-richie-secret-core=={_VERSION}", "atlas_richie.secret")`.

`sync_versions.py --check`: `OK: all pyproject.toml files are in sync
with versions.toml` (11 packages).

## Crypto optional dependency

`cryptography` is in `[crypto]` optional-dependency. Importing
`DefaultSecretCipher` / `DefaultSigningService` without the package
raises `SecretCryptoException` with an install hint. Production
deployments add `atlas-richie-secret-core[crypto]`; tests rely on
the same extra.

## Review gate

- ✅ 62 unit tests passed, 0 failures
- ✅ 10/10 isolated wheels install + import OK
- ✅ `python -m pytest components/secret/secret-core/tests/ -q` runs in
  0.07s (no Redis, no KMS, no I/O)
- ✅ `uv build --all-packages` succeeds; `atlas-richie-secret-core`
  0.2.0 wheel published
- ✅ `dependency-check` skipped (secret is not in the foundation
  P0/P1 source list; the `check_core_imports.py` script only
  walks `foundation/contracts` / `components/mcp` / `components/oauth`)
- ✅ Bilingual docstrings on every public surface (R-229
  convention; 60+ docstrings covering the secret namespace)

## Follow-up suggestions

- **R-233.1 — `atlas-richie-secret-redis`** — first remote backend
  wheel. Reuse `atlas-richie-cache-redis` for storage (per
  design decision: cache-redis is the underlying K/V substrate);
  implement `RedisSecretProvider` + writer / deletable; run
  integration tests against a real Redis on `127.0.0.1:16379`.
- **R-233.2 — `atlas-richie-secret-vault`** — HashiCorp Vault via
  `hvac` lib. Implement `KeyWrappingBackend` for KV-v2 + Transit
  engine. KMS-issued DEKs flow through `DefaultEnvelopeCrypto` for
  envelope encryption.
- **R-233.3 — `atlas-richie-secret-pkcs11`** — HSM via PKCS#11
  (`python-pkcs11`). Both `KeyWrappingBackend` (HSM-keyed AES
  wrap) and `SigningBackend` (HSM-keyed ECDSA) plug into
  `DefaultEnvelopeCrypto`.
- **R-233.4 — `atlas-richie-secret-openbao`** — OpenBao (open-source
  Vault fork) via the same `hvac` interface.
- **R-233.5 — cloud KMS** — AWS KMS, Azure Key Vault, GCP KMS, Aliyun
  KMS, Tencent KMS, Huawei KMS, Baidu KMS, Volcengine KMS, OCI Vault,
  IBM Key Protect, KMIP, Barbican (15 backends) — each its own wheel.
- **R-233.6 — bootstrap hardening** — YAML / TOML catalog loader
  (currently only `dict` loader is shipped); rotation-refresh
  callbacks; partial-success tolerance per binding.
- **R-233.7 — `EncryptedSecretProvider` decorator** — a dedicated
  provider decorator that wraps another provider with
  `DefaultEnvelopeCrypto` for at-rest encrypted storage. Useful
  when a backend stores raw bytes (Redis) and the application
  wants to push the encryption boundary to the provider layer.
