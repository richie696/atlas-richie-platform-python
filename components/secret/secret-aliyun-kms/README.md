# atlas-richie-secret-aliyun-kms

Alibaba Cloud **Secrets Manager + KMS** backend for the Atlas Richie
secret platform. Implements the **4-SPI composite** on top of the
official Alibaba Cloud Python SDK (`alibabacloud_kms20160120`),
mirroring Java `atlas-richie-secret-provider-aliyun` 1:1.

## Two services, one wheel

| Concern | Alibaba service | SDK entry point | Why |
|---|---|---|---|
| Secret reads (versioned) | Secrets Manager | `KmsClient.get_secret_value` | Stores versioned secrets, supports `VersionStage` (e.g. `ACSCurrent`) and `VersionId` |
| Key wrap / unwrap (symmetric envelope) | KMS | `KmsClient.encrypt` / `KmsClient.decrypt` | Server-side AES wrap with `EncryptionContext` AAD binding; the master key never leaves KMS |

Alibaba's KMS is **symmetric only** (no native sign / verify API on
the `kms20160120` endpoint) — this wheel exposes `KeyWrappingBackend`
**without** `SigningBackend`, matching the Java 4-SPI scope
(`SECRET_READ` / `SECRET_VERSIONING` / `KEY_WRAP` / `KEY_UNWRAP`).

## Install

```bash
pip install "atlas-richie-secret-aliyun-kms[kms]"
```

The Alibaba SDK (`alibabacloud_kms20160120`,
`alibabacloud_tea_openapi`, `alibabacloud_credentials`) is an
**optional `[kms]` extra** so developers can `import
atlas_richie.secret_aliyun_kms.properties` and run unit tests
without installing it. The real `AliyunClientFactory.create_gateway(...)`
fails with `SecretConfigurationException("SEC-BOOT-003", ...)` if the
SDK is missing.

## Quick start

```python
from atlas_richie.secret_aliyun_kms import (
    AliyunSecretProperties,
    AliyunSecretProviderFactory,
    MissingPolicy,
)

properties = AliyunSecretProperties(
    region="cn-hangzhou",
    secrets_manager_path_prefix="my-team",
    kms_key_bindings={"cmk-a": "alias/my-team/cmk-a"},
    secrets={"db.password": {"secret_name": "prod/db"}},
)
factory = AliyunSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
secret = session.operations.get(reference)
session.close()
```

The bootstrap `load(request, missing_policy=MissingPolicy.FAIL)` method
flattens JSON secrets (recursive dot-notation for dicts, `[i]` for
lists), merges them into a single key/value map, and raises
`SEC-STORE-001` for missing required secrets or `SEC-STORE-003` for
conflicting keys.

## Environment

Prefix `ATLAS_RICHIE_SECRET_ALIYUN_`; fields cover region / endpoint
override / CA bundle for dedicated KMS / KMS key bindings / Secrets
Manager path prefix / per-logical-name secret mapping / SDK timeouts /
retry. The full list is documented in `AliyunSecretProperties`.

## See also

- `atlas-richie-secret-core` — framework + Protocols
- `atlas-richie-secret-aws-kms` — sibling remote backend wheel
  (5-SPI; this wheel is the 4-SPI variant for symmetric-only vendors)
- `docs/acceptance/R-240-secret-aliyun-kms-handoff.md` — design +
  verification + Java→Python translation table
