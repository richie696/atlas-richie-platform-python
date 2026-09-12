# R-239 Handoff: `atlas-richie-secret-rotation-daemon` — background rotation watcher

**Date:** 2026-09-12
**Owner:** Mavis
**Status:** **DONE** — 15/15 rotation daemon tests pass (12 daemon
lifecycle + 3 event tests), all `components/secret/` wheels pass
their full test suites, `atlas-richie-secret-rotation-daemon` 0.2.0
wheel built, **18/18 isolated wheels install + import OK** in fresh
venv.

## Motivation

R-233 / R-235 / R-236 / R-237 / R-238 added the framework + 7
remote backends. **R-239** adds the **first non-backend wheel**:
a background watcher that polls `SecretOperations.get_metadata`
for version changes and invokes registered callbacks so
consumers can re-resolve their caches.

This is the missing piece for "secret rotation" — backends
support automatic rotation (AWS Secrets Manager, Vault, Azure
Key Vault, GCP Secret Manager all have rotation policies) but
the framework has no way to **push** a rotation event to
consumers. The daemon fills that gap.

## Design

The daemon works against **any** backend that implements
`SecretOperations` (the storage-side protocol). It does **not**
work with pure-crypto providers (`KeyWrappingBackend`-only —
no metadata endpoint). The 7 existing backends that work:
- `secret-redis` (KV-only, no versioning — but `get_metadata`
  still works for change detection)
- `secret-vault`, `secret-openbao` (KV v2 with versioning)
- `secret-aws-kms` (Secrets Manager with versioning)
- `secret-azure-keyvault`, `secret-gcp-kms` (cloud KMS+SM)
- `secret-core` (in-memory / env / file providers)

The 1 backend that does **not** work: `secret-pkcs11` (HSM has no
secret storage / no metadata API).

## Java → Python structural mapping

Java's `RotationPublisher` hook is inside
`AbstractRemoteProviderFactory` (R-237 + R-238 only had
thin-stub providers; rotation was published only by remote
backends). Python extracts the hook to a **standalone wheel**
that works with any backend implementing `SecretOperations`.

```
components/secret/secret-rotation-daemon/
├── pyproject.toml
├── README.md
└── src/atlas_richie/secret_rotation_daemon/
    ├── __init__.py            ← public surface (3 symbols)
    ├── daemon.py              ← SecretRotationDaemon
    └── events.py              ← SecretRotated event + SecretRotationCallback type
└── tests/
    ├── conftest.py
    ├── test_rotation_daemon.py ← 12 lifecycle + behavior tests
    └── test_events.py         ← 3 event dataclass tests
```

## Functional surface (3 public symbols)

- `SecretRotationDaemon` — background polling daemon.
- `SecretRotated` — frozen event dataclass
  (`reference` / `old_version` / `new_version`).
- `SecretRotationCallback` — `Callable[[SecretRotated], None]`.

## Lifecycle

- `register(reference, callback)` — start watching.
- `start()` / `stop()` — start/stop the polling thread
  (`threading.Thread(daemon=True)`). Both are idempotent.
- `poll_once()` — public method to drive a single tick
  synchronously (useful for tests / manual drive).
- `unregister(reference)` — stop watching.
- `close()` — `stop()` + clear all registrations.

## Thread safety

- `register` / `unregister` lock a mutex (`threading.Lock`); safe
  to call concurrently with the polling thread.
- Callbacks run on the polling thread. They may block briefly
  but should not run for seconds (the daemon's tick holds the
  polling loop).
- `poll_interval_seconds=30.0` by default; lower for faster
  detection at the cost of more API calls.

## Version comparison

The daemon compares `SecretVersion.number` strings (not the
full `SecretVersion` object). Backends return a fresh
`created_at` on every read, so equality of the full object
would always be False and fire on every poll.

## Error isolation

- A `get_metadata` failure for one reference logs a warning and
  skips that tick; other references are unaffected.
- A callback exception logs an error and continues; the daemon
  keeps polling.

## Test results

- **Daemon lifecycle** (12 tests): first poll fires, second poll
  with same version is idempotent, version change fires, multiple
  references independent, `get_metadata` failure doesn't kill
  other references, callback exception doesn't kill daemon,
  unregister stops firing, start/stop lifecycle, register
  rejects non-callable, `poll_interval` validation, close blocks
  further register, registered_count bookkeeping.
- **Event dataclass** (3 tests): construction + equality + hash,
  `old_version=None` allowed, frozen.
- **Total per wheel**: 15/15 in 0.09s
- **Total `components/secret/`**: unchanged (no other tests
  affected)

## Isolated-wheel verification (18/18)

```
atlas-richie-secret-rotation-daemon==0.2.0
  → atlas-richie-secret-core==0.2.0
  → atlas-richie-contracts==0.2.0
```

The rotation daemon has **no third-party runtime deps** beyond
`atlas-richie-secret-core`. 18/18 packages successfully import
their public module in fresh `python -m venv`.

## Workspace integration

- `pyproject.toml` — added `components/secret/secret-rotation-daemon`
  to workspace members + sources.
- `versions.toml` — added `atlas-richie-secret-rotation-daemon = "0.2.0"`.
- `foundation/platform/pyproject.toml` — added the dep constraint.
- `tools/release/verify_isolated_wheels.py` — added the new entry.
- `tools/sync_versions.py` — synced 19 `pyproject.toml` files
  clean.

## Acceptance checklist

- [x] Standalone wheel; no cloud SDK dependency
- [x] Polls `SecretOperations.get_metadata` (works with any backend)
- [x] Per-reference last-seen version + version-change detection
- [x] `start()` / `stop()` / `unregister()` / `close()` lifecycle
- [x] Per-callback error isolation
- [x] `pytest` 15/15 pass for the daemon
- [x] `tools/release/verify_isolated_wheels.py` 18/18 OK
- [x] `tools/sync_versions.py` 19/19 syncs clean
- [x] Wheel built and present in `dist/`
- [x] `pyproject.toml` / `versions.toml` / `foundation/platform` /
      `verify_isolated_wheels.py` updated
- [x] Handoff doc written
- [ ] Single commit + push
