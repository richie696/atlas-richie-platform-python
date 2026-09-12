# atlas-richie-secret-aliyun-kms

Alibaba Cloud KMS + Secrets Manager backend for the Atlas Richie
secret platform. Implements the **4-SPI composite** (`SecretOperations`
via Secrets Manager + `KeyWrappingBackend` via KMS +
`SecretBootstrapClient` + `SecretProviderSession`), mirroring Java
`atlas-richie-secret-provider-aliyun` 1:1.

## Two services, one wheel

| Concern | Alibaba service | SDK | Why |
|---|---|---|---|
| Secret reads | Secrets Manager | `alibabacloud_kms20160120` (the SDK exposes both SM and KMS under the 20160120 service version) | Stores plaintext-or-encrypted secrets with versions and stages |
| Key wrap / unwrap | KMS symmetric CMK | `alibabacloud_kms20160120.Encrypt` / `Decrypt` | Wraps DEKs without ever exposing the master key |

The split mirrors the Java side: Alibaba's `kms20160120` SDK
unifies SM and KMS API surface (it shares the same `Client` class
with `GetSecretValue` / `Encrypt` / `Decrypt` methods).

## Local development

The Alibaba Cloud SDK has no local emulator. Tests use a
`FakeAliyunGateway` (in-process, no network) for unit coverage.
Real-cloud integration requires a RAM user with `kms:Encrypt`,
`kms:Decrypt`, `secretsmanager:GetSecretValue` permissions
and a region with KMS enabled.

## Install

```bash
# SDK is optional; only needed when constructing a real gateway.
pip install 'atlas-richie-secret-aliyun-kms[kms]'
```

## Quick start

```python
from atlas_richie.secret_aliyun_kms import (
    AliyunSecretProperties,
    AliyunSecretProviderFactory,
)

properties = AliyunSecretProperties(
    region="cn-hangzhou",
    kms_key_bindings={"default-envelope": "alias/orders"},
)
factory = AliyunSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
assert session.descriptor.backend.value == "aliyun"
session.close()
```

## Environment

Prefix `ATLAS_RICHIE_SECRET_ALIYUN_`; fields cover
region / endpoint (override for VPC endpoint) / ca_file (required
for dedicated KMS endpoint) / Secrets Manager path prefix /
KMS key bindings / secret mappings.

## See also

- `atlas-richie-secret-core` — framework + Protocols
- `atlas-richie-secret-aws-kms` — sibling cloud backend wheel
- `docs/acceptance/R-240-secret-aliyun-kms-handoff.md` — design + verification
