# atlas-richie-secret-core

Framework-neutral secret management core. 1:1 functional parity with
the Java `atlas-richie-secret-parent` (api / core / bootstrap /
testkit / provider SPI / crypto envelope / local providers).

The Python side consolidates the Java 21 sub-modules into one wheel
with internal sub-packages. Remote backends (redis / vault / openbao /
pkcs11 / aws / azure / gcp / aliyun / tencent / huawei / baidu / volcengine
/ oci / ibm-key-protect / kmip / barbican) live in separate wheels
starting with `atlas-richie-secret-redis`.

## Quick start

```python
from atlas_richie.secret import (
    GlobalSecret,
    GlobalSecretManager,
    InMemorySecretProviderFactory,
    SecretProviderConfiguration,
    SecretReference,
)

factory = InMemorySecretProviderFactory(name="in-process")
session = factory.create(SecretProviderConfiguration(name="in-process"))
manager = GlobalSecretManager.from_sessions([session], factories={"in-process": factory})
GlobalSecret.install(manager)

# write
GlobalSecret.write(SecretReference(provider="in-process", path="db.password"), b"sup3rs3cr3t")

# read
value = GlobalSecret.resolve(SecretReference(provider="in-process", path="db.password"))
assert value.plaintext == b"sup3rs3cr3t"

# rotate
GlobalSecret.rotate(SecretReference(provider="in-process", path="db.password"), b"n3wsup3rs3cr3t")
```

## Optional: crypto envelope

```bash
pip install atlas-richie-secret-core[crypto]
```

Provides AES-256-GCM `SecretCipher`, ECDSA-P256-SHA256 `SigningService`,
and the `ArseEnvelopeCodec` (base64 + JSON) for at-rest envelope
encryption. KMS / HSM backends (AWS KMS / Vault Transit / PKCS#11)
implement `KeyWrappingBackend` / `SigningBackend` and compose with
the local primitives.

## Bootstrap (startup-time secret injection)

```python
from atlas_richie.secret import (
    AtlasSecretEnvironmentPostProcessor,
    BootstrapSecretProperties,
    SecretBinding,
    SecretBindingCatalog,
    SecretBindingCatalogLoader,
    SecretReference,
)

catalog = SecretBindingCatalogLoader({
    "name": "default",
    "bindings": [
        {"name": "db.password", "provider": "vault", "path": "db/password"},
    ],
}).load()

processor = AtlasSecretEnvironmentPostProcessor(
    registry=SecretRegistry.instance(),
    properties=BootstrapSecretProperties(),
)
processor.post_process(catalog)
# os.environ["DB.PASSWORD"] now holds the resolved secret
```

## Components

- `atlas_richie.secret.resolver` — `SecretResolver` / `DefaultSecretResolver`
- `atlas_richie.secret.operations` / `writer` — read / write contracts
- `atlas_richie.secret.metadata` / `value` / `reference` / `callback` — value model
- `atlas_richie.secret.provider` — `SecretProviderFactory` / `Session` / `Configuration` / `Descriptor`
- `atlas_richie.secret.local` — InMemory / Env / File backends
- `atlas_richie.secret.crypto` — cipher / signing / envelope / codec / backend SPI
- `atlas_richie.secret.bootstrap` — catalog / policy / state / discovery / SPI / processor / default client
- `atlas_richie.secret.snapshot` — rotation event / listener / manager
- `atlas_richie.secret.registry` — `SecretRegistry` (mutex over active providers)
- `atlas_richie.secret.global_secret` / `global_secret_manager` — facade
- `atlas_richie.secret.testkit` — `StubSecretCallback` / `RecordingSnapshotListener` / `in_memory_fixture`

## License

Apache-2.0
