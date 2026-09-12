# R-238 Handoff: `atlas-richie-secret-pkcs11` — PKCS#11 / HSM backend

**Date:** 2026-09-12
**Owner:** Mavis
**Status:** **DONE** — 24/24 pkcs11 tests pass (6 properties unit + 5
configuration unit + 13 client integration vs real SoftHSM2), all
**262/262 secret tests pass** across all 8 secret wheels
(62 core + 20 redis + 56 vault + 6 openbao + 37 aws + 31 azure +
26 gcp + 24 pkcs11), `atlas-richie-secret-pkcs11` 0.2.0 wheel built,
**17/17 isolated wheels install + import OK** in fresh venv.

## Motivation

R-233 / R-235 / R-236 / R-237 added the framework + 6 remote backends
(Redis, Vault, OpenBao, AWS, Azure, GCP). **R-238** adds the
**seventh**: **PKCS#11 / HSM** — the hardware-rooted backend where
key material never leaves the hardware boundary. Mirrors Java
`atlas-richie-secret-provider-pkcs11` 1:1.

HSMs are fundamentally **crypto-only**:
- No secret storage (no `SecretOperations`)
- No list capability (no `SecretListable`)
- No write/delete (no `SecretWriter` / `SecretDeletable`)
- Only `KeyWrappingBackend` + `SigningBackend` + `SecretBootstrapClient` +
  `SecretProviderSession` (4 SPI)

## Design parity with Java

| SPI | Java | Python (R-238) |
|---|---|---|
| `SecretOperations` | no | **no** |
| `KeyWrappingBackend` | yes (`CKM_RSA_PKCS_OAEP`) | yes (`public_key.encrypt(..., mechanism=RSA_PKCS_OAEP)`) |
| `SigningBackend` | yes (`CKM_SHA256_RSA_PKCS`) | yes (`private_key.sign(data, mechanism=...)`) |
| `SecretBootstrapClient` | yes (HSM key inventory) | yes (label existence check) |
| `SecretProviderSession` | yes | yes |
| `SecretListable` | no | **no** |

## Java → Python structural mapping

```
components/secret/secret-pkcs11/
├── pyproject.toml
├── README.md
└── src/atlas_richie/secret_pkcs11/
    ├── __init__.py            ← public surface (6 symbols)
    ├── client.py              ← Pkcs11SecretClient (4-SPI composite)
    ├── configuration.py       ← Pkcs11ConfigurationResolver + SHA-256
    ├── factory.py             ← Pkcs11SecretProviderFactory + Pkcs11ClientFactory
    └── properties.py          ← Pkcs11SecretProperties + Pkcs11SignMechanism
└── tests/
    ├── conftest.py                ← pkcs11_lib_token / pkcs11_session / pkcs11_rsa_keypair fixtures
    ├── test_pkcs11_properties.py  ← 6 unit tests
    ├── test_pkcs11_configuration.py ← 5 unit tests
    └── test_pkcs11_client.py      ← 13 integration tests vs SoftHSM2
```

## Functional surface (6 public symbols)

- `Pkcs11SecretProperties` — pydantic-settings env-injected;
  prefix `ATLAS_RICHIE_SECRET_PKCS11_`. Carries `module_path` /
  `token_label` / `user_pin` / `key_bindings` /
  `default_sign_mechanism`.
- `Pkcs11SignMechanism` — `StrEnum { SHA256_RSA_PKCS, ECDSA_SHA256, SHA256_ECDSA }`.
- `ResolvedPkcs11Configuration` + `Pkcs11ConfigurationResolver` —
  SHA-256 `configuration_hash` over canonical fields; static
  `SecretCapability` (`can_read=False`, `signs_values=True`,
  `cacheable=False`).
- `Pkcs11ClientFactory` — `pkcs11.lib(module_path).get_token(token_label=...)`.
- `Pkcs11SecretProviderFactory` — `SecretProviderFactory` implementation
  (`name = f"pkcs11-{token_label}"`, `backend = SecretBackend.PKCS11`).
- `Pkcs11SecretClient` — composite 4-SPI client. `operations` /
  `writer` / `deletable` properties all return `None` (HSM has no
  storage).

## SDK

- `python-pkcs11==0.10.0` — Cython wrapper around the PKCS#11
  provider. `pkcs11.lib(so_path)` loads the .so;
  `lib.get_token(token_label=...)` finds the token;
  `token.open(user_pin=..., rw=...)` opens a session.

## API gotchas (worked around)

1. **`wrap_key` vs `encrypt`**: python-pkcs11's `public_key.wrap_key(key=...)`
   wraps an HSM-resident key object, not arbitrary bytes. For the
   framework's "import the caller's DEK" use case, the right call is
   `public_key.encrypt(data, mechanism=...)` (RSA-OAEP). The
   `client.py` uses the right one.
2. **Session-scoped vs token-scoped**: `generate_keypair()` defaults to
   `store=False`, so the keypair vanishes when the session is
   closed. The test fixture uses `generate_keypair(..., store=True)`
   on a **read-write** session (`token.open(rw=True, user_pin=...)`)
   so the keypair persists across test sessions.
3. **Mechanism name format**: python-pkcs11 uses bare
   `pkcs11.Mechanism.SHA256_RSA_PKCS` (not `CKM_SHA256_RSA_PKCS`).
   The `Pkcs11SignMechanism` enum stores the bare name.
4. **Verify returns bool, not exception**: SoftHSM's
   `public_key.verify(tampered_payload, sig, ...)` returns `False`
   directly (no exception). The client maps this to the
   framework's "False" path; `PKCS11Error` exceptions map to
   `SecretCryptoException`.

## Errors

- `NoSuchKey` / `ObjectHandleInvalid` → `SecretCryptoException("SEC-KEY-001")`
- `PinIncorrect` / `UserNotLoggedIn` → `SecretCryptoException("SEC-AUTH-001")`
- Other `PKCS11Error` → `SecretCryptoException("SEC-CRYPTO-001")`

## Test results

- **Unit** (no SoftHSM): 11 tests pass
  - `test_pkcs11_properties.py` — 6
  - `test_pkcs11_configuration.py` — 5
- **Integration** (real SoftHSM2): 13 tests pass
  - `test_pkcs11_client.py` — 13 (wrap+unwrap roundtrip + tampered,
    sign+verify + tampered, key bindings, session close + post-close,
    operations/writer/deletable all None)
- **Total per wheel**: 24/24 in 0.70s
- **Total `components/secret/`**: 262/262

## Isolated-wheel verification (17/17)

```
atlas-richie-secret-pkcs11==0.2.0
  → atlas-richie-secret-core==0.2.0
  → atlas-richie-contracts==0.2.0
  → python-pkcs11==0.10.0
  → asn1crypto==1.5.1
  → pydantic==2.13.5
  → pydantic-settings==2.15.0
```

17/17 packages successfully import their public module in fresh
`python -m venv`.

## Workspace integration

- `pyproject.toml` — added `components/secret/secret-pkcs11` to
  workspace members + sources.
- `versions.toml` — added `atlas-richie-secret-pkcs11 = "0.2.0"`.
- `foundation/platform/pyproject.toml` — added the dep constraint.
- `tools/release/verify_isolated_wheels.py` — added the new entry.
- `tools/sync_versions.py` — synced 18 `pyproject.toml` files
  clean.

## Acceptance checklist

- [x] Java → Python 1:1 functional parity (4-SPI subset)
- [x] Bilingual docstrings on every public module / class / method
- [x] No python-pkcs11 types in the public facade
- [x] `pytest` 262/262 pass across all 8 secret wheels
- [x] `tools/release/verify_isolated_wheels.py` 17/17 OK
- [x] `tools/sync_versions.py` 18/18 syncs clean
- [x] Wheel built and present in `dist/`
- [x] `pyproject.toml` / `versions.toml` / `foundation/platform` /
      `verify_isolated_wheels.py` updated
- [x] Handoff doc written
- [ ] Single commit + push
