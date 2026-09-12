# R-233.4 + R-234 Handoff: `atlas-richie-secret-openbao` — OpenBao backend (thin wrapper)

**Date:** 2026-09-12
**Owner:** Mavis
**Status:** **DONE** — 6/6 openbao integration tests pass, all 144 secret
tests pass (R-233.0 core + R-233.1 redis + R-233.2 vault + R-233.3
key-bindings + R-233.4 openbao), `atlas-richie-secret-openbao` 0.2.0
wheel built, **13/13 isolated wheels install + import OK** in fresh venv.

## Motivation

R-233.2 shipped `atlas-richie-secret-vault`. **R-233.4 + R-234** add
the OpenBao backend as a **thin wrapper** over that wheel, because
OpenBao is API-compatible with HashiCorp Vault (KV v2 + Transit + the
Token / Kubernetes / AppRole auth methods are all 1:1).

The wrapper exists for three reasons:

1. **Brand attribution** — `SecretProviderDescriptor.backend` carries
   the actual deployment brand (`vault` vs `openbao`), so observability
   / policy tooling can distinguish them.
2. **Future OpenBao-specific features** — once OpenBao diverges from
   Vault (e.g. `bao_namespace` multi-tenant, hardware seal-wrap root
   tokens, server-side rate-limit hints), they can land in this wheel
   without polluting `atlas-richie-secret-vault`.
3. **Per-deployment wiring** — separate wheel = separate
   `provider_id` prefix (`openbao-*` vs `vault-*`), which makes the
   secret registry's listing cleaner when both engines are used in the
   same cluster.

## Design decision: thin wrapper, NOT mirror copy

Two designs were considered for this wheel:

| Design | What | Cost | Benefit |
|---|---|---|---|
| **(A) thin wrapper** ✓ chosen | `OpenBaoSecretProviderFactory` is a `VaultSecretProviderFactory` subclass that only overrides `name` / `backend` / `version` branding. The produced session is a real `VaultSecretClient`. | Tiny (one subclass + a properties subclass with zero new fields) | Zero code duplication; future OpenBao divergence is a localized override, not a fork |
| (B) mirror copy | Full copy of 7 vault files with `OpenBao*` prefixes | ~90% duplicated code, must maintain parity forever | Total runtime decoupling (hypothetically useful only if OpenBao ever ships a non-`hvac` SDK, which hasn't happened) |

OpenBao is committed to API parity with Vault for the KV v2 / Transit
surface (their stated mission). When they diverge, it will be in
**additive** ways (new auth methods, new mount types), not by
re-writing existing endpoints. (A) is the right call.

## Java → Python structural mapping

Java has `cn.richie696.component.secret.provider.openbao.*` as a
sub-module that re-uses the vault module's classes with
`@ConditionalOnClass(name = "openbao")` style wiring. Python follows
the same pattern through inheritance:

```
components/secret/secret-openbao/
├── pyproject.toml
├── README.md
└── src/atlas_richie/secret_openbao/
    ├── __init__.py        ← public surface (3 symbols)
    ├── factory.py         ← OpenBaoSecretProviderFactory (subclass of VaultSecretProviderFactory)
    └── properties.py      ← OpenBaoSecretProperties (subclass of VaultSecretProperties, zero new fields)
└── tests/
    ├── conftest.py             ← openbao_hvac_client / openbao_session fixtures
    └── test_openbao.py         ← 6 integration tests
```

## Functional surface (3 public symbols)

- `OpenBaoSecretProperties` — subclass of `VaultSecretProperties`.
  No new fields. Kept as a distinct type so the secret registry
  can differentiate OpenBao sessions at the static-type level,
  and so future OpenBao-specific fields can land here without
  touching `atlas-richie-secret-vault`.
- `OpenBaoSecretProviderFactory` — subclass of
  `VaultSecretProviderFactory` with three overrides:
  - `name` → `f"openbao-{namespace}"` (instead of `f"vault-{namespace}"`)
  - `backend` → `SecretBackend.OPENBAO` (instead of `SecretBackend.VAULT`)
  - `version` → `f"{version}-openbao"` (default `"0.2.0-openbao"`)
- `VaultSecretClient` — re-exported so callers don't have to import
  the underlying wheel directly. The runtime object IS a
  `VaultSecretClient`; only `descriptor.backend` differs.

## Required change in the upstream vault wheel

`atlas-richie-secret-vault@0.2.0` previously hardcoded
`SecretBackend.VAULT` in two places:

1. `VaultSecretClient.__init__` constructor (used by the
   `descriptor` property)
2. `VaultSecretClient._read` and `get_metadata` (used by the
   `SecretValue.metadata.backend` and `SecretMetadata.backend`)

The change adds an optional `descriptor_backend: SecretBackend =
SecretBackend.VAULT` keyword argument to `VaultSecretClient.__init__`
and a matching `descriptor_backend` keyword to
`VaultSecretProviderFactory.__init__` (with the same default). When
the OpenBao factory passes `SecretBackend.OPENBAO`, every
`SecretMetadata.backend` and `SecretProviderDescriptor.backend`
in the resulting session reports `SecretBackend.OPENBAO`. Default
behaviour is unchanged (existing 50 vault tests still pass).

This is an additive change — no call site, test, or downstream
consumer in the Vault path is affected. The 56 vault tests
(including the 6 new key-bindings tests from R-233.3) and 6
OpenBao tests together are 62 / 62 pass.

## Test results

| Suite | Count | Status |
|---|---|---|
| `components/secret/secret-vault/tests/` (R-233.2 + R-233.3) | 56 | ✓ |
| `components/secret/secret-openbao/tests/` (R-233.4) | 6 | ✓ |
| `components/secret/secret-redis/tests/` (R-233.1) | 20 | ✓ |
| `components/secret/secret-core/tests/` (R-233.0) | 62 | ✓ |
| **Total `components/secret/`** | **144** | **✓ 144/144 in 1.14s** |

The 6 OpenBao integration tests run against the existing
`vault-dev` container on `127.0.0.1:8200` because OpenBao is
API-compatible with Vault. Set `OPENBAO_TEST_URL` env var to point
at a real OpenBao instance when one is available.

## Isolated-wheel verification (13/13)

`tools/release/verify_isolated_wheels.py` now has 13 entries. The
two new ones:

- `atlas-richie-secret-vault==0.2.0` → re-built with the
  `descriptor_backend` addition; transitive deps unchanged
  (hvac + cryptography + pydantic + pydantic-settings + cffi +
  pycparser + requests + charset_normalizer + urllib3 + idna +
  certifi + typing-extensions + typing-inspection + pydantic-core)
- `atlas-richie-secret-openbao==0.2.0` → `atlas-richie-secret-vault`
  + `atlas-richie-contracts`. **No new transitive runtime deps**
  beyond what `atlas-richie-secret-vault` already requires.

13/13 packages successfully import their public module in fresh
`python -m venv` against `dist/wheelhouse` (no PyPI, no editable
workspace).

## Workspace integration

- `pyproject.toml` — added `components/secret/secret-openbao` to
  `tool.uv.workspace.members` + `tool.uv.sources`.
- `versions.toml` — added `atlas-richie-secret-openbao = "0.2.0"`.
- `foundation/platform/pyproject.toml` — added
  `"atlas-richie-secret-openbao>=0.2.0,<0.3.0"` to dependencies.
- `tools/release/verify_isolated_wheels.py` — added
  `(f"atlas-richie-secret-openbao=={_VERSION}", "atlas_richie.secret_openbao")`
  to `PACKAGES` (13 entries total).
- `tools/sync_versions.py` — synced clean, 14 `pyproject.toml`
  files (the 13 prior + the new openbao one).

## Patterns used

- **Adapter** — `OpenBaoSecretProviderFactory` adapts a
  Vault-shaped `VaultSecretClient` to an OpenBao-shaped
  `SecretProviderFactory` interface
- **Decorator** (conceptual) — the OpenBao factory *brands* the
  underlying vault session with `SecretBackend.OPENBAO`, like a
  metadata decorator around a `SecretProviderDescriptor`
- **Inheritance / Template Method** — `OpenBaoSecretProviderFactory`
  inherits the create() workflow from `VaultSecretProviderFactory`,
  overriding only the three branding methods

## Anti-patterns avoided (per OOP / CODE_QUALITY.md)

- No `*Impl` / `*Manager` / `*DTO` / `*Util` suffixes in the
  public facade.
- No `**kwargs` in any public signature.
- No copy-paste of the 7 vault files into a parallel openbao
  implementation (the 90% duplication anti-pattern).
- `OpenBaoSecretProperties` is `frozen=True, slots=True` (inherited
  from `VaultSecretProperties`).
- hvac SDK types do not appear in the public facade.
- No lazy / inline imports inside `__init__` methods.

## Acceptance checklist

- [x] Java → Python 1:1 functional parity (OpenBao is re-use of Vault)
- [x] Bilingual docstrings on every public module / class / method
- [x] Adapter + Template Method + Decorator patterns present
- [x] No hvac SDK types in the public facade
- [x] Real Vault-on-8200 (API-compatible with OpenBao) for all integration
- [x] `pytest` 144/144 pass across all 4 secret wheels
- [x] `tools/release/verify_isolated_wheels.py` 13/13 OK
- [x] `tools/sync_versions.py` 14/14 syncs clean
- [x] Both wheels built and present in `dist/`
- [x] `pyproject.toml` workspace members + sources updated
- [x] `versions.toml` updated
- [x] `foundation/platform/pyproject.toml` updated
- [x] `verify_isolated_wheels.py` PACKAGES updated
- [x] Handoff doc (this file) written
- [ ] Single commit + push (R-233.4 / R-234 final step)
