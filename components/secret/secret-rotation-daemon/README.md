# atlas-richie-secret-rotation-daemon

Background daemon that watches secret metadata for version
changes and invokes registered callbacks when a rotation is
detected.

## Motivation

Most cloud secret backends (AWS Secrets Manager, Vault, Azure Key
Vault, GCP Secret Manager) support **automatic rotation**: an
operator can rotate the underlying value, the backend persists a
new version, and downstream clients transparently see the new
value the next time they read. But the framework's
`SecretOperations.get` call may be cached at the consumer side
(config files, in-memory state, etc.). The framework has no way
to *push* the change to those caches.

`SecretRotationDaemon` is the missing piece:

- Periodically polls `get_metadata(reference)` for each registered
  `SecretReference`
- Compares the returned version against the last-seen version
- When the version changes, invokes the registered callback
  with `(reference, new_version)` so the consumer can re-resolve
  its cache

The daemon works against any backend that implements
`SecretOperations` (Vault / OpenBao / AWS / Azure / GCP / Redis
*Local* providers, but not HSM / pure-crypto providers).

## Quick start

```python
from atlas_richie.secret_rotation_daemon import SecretRotationDaemon

# `operations` is a `SecretOperations` (e.g. the `.operations`
# property of any `SecretProviderSession`).
daemon = SecretRotationDaemon(operations=operations, poll_interval_seconds=30.0)

def on_rotate(reference, new_version):
    print(f"{reference.path} rotated to {new_version.number}")

daemon.register(SecretReference(provider="x", path="db"), on_rotate)
daemon.start()
# ... daemon runs in a background thread ...
daemon.stop()
```

## Environment

No env vars — all config is passed to the `SecretRotationDaemon`
constructor.

## See also

- `atlas-richie-secret-core` — framework + `SecretOperations` /
  `SecretMetadata` types
- `docs/acceptance/R-239-secret-rotation-daemon-handoff.md`
