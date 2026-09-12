# R-235 Handoff: `atlas-richie-secret-aws-kms` — AWS Secrets Manager + KMS backend

**Date:** 2026-09-12
**Owner:** Mavis
**Status:** **DONE** — 37/37 aws tests pass (11 properties unit + 6
configuration unit + 20 client integration), all **181/181 secret tests
pass** across all 5 secret wheels (62 core + 20 redis + 56 vault + 6
openbao + 37 aws), `atlas-richie-secret-aws-kms` 0.2.0 wheel built,
**14/14 isolated wheels install + import OK** in fresh venv.

## Motivation

R-233.x shipped the framework + in-process backends + three remote
backends (Redis, Vault, OpenBao). **R-235** adds the fourth remote
backend: **AWS Secrets Manager + AWS KMS**, on the public protocol
surface (KV v2-equivalent reads via SM + Transit-equivalent wrap/sign
via KMS), matching Java `atlas-richie-secret-provider-aws` 1:1.

Unlike Vault / OpenBao (single SDK + single protocol), AWS splits the
read and crypto sides across two services:

| Concern | Java | Python |
|---|---|---|
| Secret read (KV v2 equivalent) | AWS Secrets Manager | `boto3.client("secretsmanager")` |
| Key wrap / unwrap (Transit equivalent) | AWS KMS | `boto3.client("kms")` |
| Sign / verify (Transit sign equivalent) | AWS KMS asymmetric CMK | `boto3.client("kms")` |
| Auth (Token / Kubernetes / AppRole) | boto3 default chain + profile | same |

The `AwsSecretClient` is a **5-SPI composite** running on TWO boto3
clients, paralleling the Java `AwsSecretClient` exactly.

## Java → Python structural mapping

Java has `cn.richie696.component.secret.provider.aws.*` as 6 files
inside one sub-module. Python is one wheel
(`atlas-richie-secret-aws-kms`) with 4 source files (auth / request-id
/ retry are absorbed by boto3's defaults):

```
components/secret/secret-aws-kms/
├── pyproject.toml
├── README.md
└── src/atlas_richie/secret_aws_kms/
    ├── __init__.py            ← public surface (6 symbols)
    ├── client.py              ← AwsSecretClient (5-SPI composite)
    ├── configuration.py       ← AwsConfigurationResolver + path safety + SHA-256
    ├── factory.py             ← AwsSecretProviderFactory + AwsClientFactory
    └── properties.py          ← AwsSecretProperties + AwsAuthType
└── tests/
    ├── conftest.py                 ← aws_kms_client / aws_session / localstack fixtures
    ├── test_aws_properties.py      ← 11 unit tests (env injection + auth)
    ├── test_aws_configuration.py  ← 6 unit tests (path safety + hash)
    └── test_aws_client.py          ← 20 integration tests vs localstack on 4566
```

## Functional surface (6 public symbols)

- `AwsSecretProperties` — pydantic-settings env-injected configuration;
  prefix `ATLAS_RICHIE_SECRET_AWS_`. Carries region / auth (default
  chain / profile) / KMS signing algorithm / KMS key bindings /
  Secrets Manager path prefix / endpoint overrides.
- `AwsAuthType` — `StrEnum { DEFAULT_CHAIN, PROFILE }`.
- `ResolvedAwsConfiguration` + `AwsConfigurationResolver` — path
  safety validation (no `..` / `://` / leading `/` / trailing `/` on
  the path prefix), static `SecretCapability` declaration
  (`can_list=True`, the only cloud backend with this), SHA-256
  `configuration_hash` that includes the key-bindings map.
- `AwsClientFactory` — build `(kms_client, sm_client)` from
  `AwsSecretProperties`.
- `AwsSecretProviderFactory` — `SecretProviderFactory` implementation
  (`name = f"aws-{region}"`, `backend = SecretBackend.AWS`).
- `AwsSecretClient` — composite implementation of 5 SPI roles on
  two boto3 clients:
  - `SecretOperations` — SM reads
  - `KeyWrappingBackend` (duck-typed) — KMS `encrypt` / `decrypt`
  - `SigningBackend` (duck-typed) — KMS `sign` / `verify`
  - `SecretBootstrapClient` (`bootstrap` resolves a
    `SecretBindingCatalog` into a `SecretBootstrapResult`)
  - `SecretProviderSession` (descriptor / configuration /
    operations / writer / deletable / snapshot_manager /
    is_closed / close)
  The class **does not** implement `SecretWriter` /
  `SecretDeletable`; the session's `writer` and `deletable`
  properties return `None`, mirroring the Java
  `AwsSecretClient`.

## KMS key bindings (logical → physical)

Mirrors the vault wheel's R-233.3 `transit_key_bindings`. The
`KeyReference.key_id` is a logical name; the resolved physical CMK
ARN lives in `properties.kms_key_bindings[logical]`. If no binding
is present, `key_id` is used as the physical CMK ARN directly
(Pythonic backward-compat).

## Local development: localstack

```bash
docker run -d --name localstack \
  -p 4566:4566 \
  -e SERVICES=kms,secretsmanager \
  -e AWS_DEFAULT_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID=test \
  -e AWS_SECRET_ACCESS_KEY=test \
  localstack/localstack:3
```

The test fixtures point at `http://127.0.0.1:4566` by default; tests
`pytest.skip` if unreachable.

## boto3 API choices

| Operation | boto3 call | Why |
|---|---|---|
| `wrap_key(dek, kek)` | `kms.encrypt(Plaintext=dek, KeyId=cmk)` | The framework's `wrap_key` **imports** the caller's DEK as a wrapped blob. `kms.encrypt` is the right tool for "import existing DEK". `kms.generate_data_key` would generate a fresh DEK (wrong — caller owns the DEK). |
| `unwrap_key(wrapped, ctx)` | `kms.decrypt(CiphertextBlob=blob, KeyId=cmk)` | Inverse of `encrypt`. |
| `sign(payload, key)` | `kms.sign(KeyId=cmk, Message=payload, SigningAlgorithm=algo)` | Asymmetric CMK required; tests create a per-test RSA-2048 CMK. |
| `verify(payload, signature)` | `kms.verify(...)` | boto3 raises `KMSInvalidSignatureException` for mismatch; the client maps this to `False` (per the framework's `verify` contract). |
| `get(reference)` | `sm.get_secret_value(SecretId=path)` | STATIC `version_selector` → pass `VersionId=...`; LATEST → omit. |
| `list_secrets` | `sm.list_secrets()` | `Filters` requires exact segment match; the client surfaces a broad listing, framework callers filter client-side. |

## Errors

- SM `ResourceNotFoundException` → `SecretIntegrityException` (404
  equivalent)
- SM / KMS `AccessDeniedException` → `SecretException` /
  `SecretCryptoException` with `SEC-AUTHZ-001`
- KMS `InvalidKeyId` / `NotFoundException` → `SecretCryptoException`
  with `SEC-KEY-001`
- KMS `KMSInvalidSignatureException` (verify only) → return `False`
- 5xx / throttling → boto3 standard-mode retry (3 attempts) handles
  them; anything that escapes is mapped to
  `SEC-PROVIDER-001`

## Test results

- **Unit** (no localstack): 17 tests pass
  - `test_aws_properties.py` — 11
  - `test_aws_configuration.py` — 6
- **Integration** (real localstack on `127.0.0.1:4566`):
  - `test_aws_client.py` — 20 (SM get / versioned-get / metadata /
    exists / list, KMS wrap+unwrap roundtrip + tampered, KMS
    sign+verify roundtrip + tampered, key-bindings resolution,
    bootstrap STARTUP+OPTIONAL, session close + post-close, writer /
    deletable = None)
- **Total per wheel**: 37/37 in 0.74s
- **Total `components/secret/`**: 181/181 in 1.71s (62 core + 20
  redis + 56 vault + 6 openbao + 37 aws)

## Isolated-wheel verification (14/14)

`tools/release/verify_isolated_wheels.py` now has 14 entries. The
new one:

```
atlas-richie-secret-aws-kms==0.2.0
  → atlas-richie-secret-core==0.2.0
  → atlas-richie-contracts==0.2.0
  → boto3==1.43.93
  → botocore==1.43.93
  → jmespath==1.1.0
  → s3transfer==0.19.2
  → python-dateutil==2.9.0.post0
  → six==1.17.0
  → urllib3==2.7.0
  → pydantic==2.13.5
  → pydantic-core==2.46.5
  → typing_extensions==4.16.0
  → typing_inspection==0.4.4
  → pydantic-settings==2.15.0
  → python-dotenv==1.2.3
```

14/14 packages successfully import their public module in fresh
`python -m venv` against `dist/wheelhouse` (no PyPI, no editable
workspace).

## Workspace integration

- `pyproject.toml` — added `components/secret/secret-aws-kms` to
  `tool.uv.workspace.members` + `tool.uv.sources`.
- `versions.toml` — added `atlas-richie-secret-aws-kms = "0.2.0"`.
- `foundation/platform/pyproject.toml` — added
  `"atlas-richie-secret-aws-kms>=0.2.0,<0.3.0"` to dependencies.
- `tools/release/verify_isolated_wheels.py` — added
  `(f"atlas-richie-secret-aws-kms=={_VERSION}", "atlas_richie.secret_aws_kms")`
  to `PACKAGES` (14 entries total).
- `tools/sync_versions.py` — synced clean, 15 `pyproject.toml`
  files (the 14 prior + the new aws-kms one).

## Patterns used

- **Adapter** — `AwsSecretClient` adapts two boto3 clients to the
  framework's Protocol surface
- **Composite** — single `AwsSecretClient` instance satisfies 5 SPI
  roles
- **Strategy** — `AwsAuthType` (default chain vs profile) with
  boto3's default credential chain as the dispatcher
- **Factory** — `AwsClientFactory` + `AwsSecretProviderFactory`
- **Facade** — `atlas_richie.secret_aws_kms.__init__` exposes the
  6 public symbols; boto3 client types never leak out
- **Template Method** — `AwsSecretProviderFactory.create` follows
  the same pattern as `VaultSecretProviderFactory.create`

## Anti-patterns avoided (per OOP / CODE_QUALITY.md)

- No `*Impl` / `*Manager` / `*DTO` / `*Util` suffixes.
- No `**kwargs` in any public signature.
- No lazy / inline imports inside `__init__` methods.
- All dataclasses are `frozen=True, slots=True`.
- boto3 client types are typed in the public surface as
  `object` (they're test seams — tests inject `MagicMock` /
  pre-built clients via the `client_factory` parameter).
- `AwsSecretProperties` is `frozen=True`; `ResolvedAwsConfiguration`
  is `frozen=True, slots=True`.
- No copy-paste of `secret-vault`'s path safety validator — the
  `_safe_path` helper is inlined in `configuration.py` so
  `secret-aws-kms` does not have a runtime dependency on
  `secret-vault`. (Same approach the OpenBao wheel uses for
  `OpenBaoSecretProperties` — a wheel that re-uses a sibling
  wheel's helper must own the helper, not import it.)

## Acceptance checklist

- [x] Java → Python 1:1 functional parity (5 SPI composite on SM
      + KMS, matching Java `AwsSecretClient`)
- [x] Bilingual docstrings on every public module / class / method
- [x] Real localstack on 127.0.0.1:4566 for all integration tests
      (no mocks, no fakes, no moto)
- [x] `pytest` 181/181 pass across all 5 secret wheels
- [x] `tools/release/verify_isolated_wheels.py` 14/14 OK
- [x] `tools/sync_versions.py` 15/15 syncs clean
- [x] Wheel built and present in `dist/`
- [x] `pyproject.toml` workspace members + sources updated
- [x] `versions.toml` updated
- [x] `foundation/platform/pyproject.toml` updated
- [x] `verify_isolated_wheels.py` PACKAGES updated
- [x] Handoff doc (this file) written
- [ ] Single commit + push (final step)
