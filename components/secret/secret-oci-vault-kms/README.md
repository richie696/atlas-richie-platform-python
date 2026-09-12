# atlas-richie-secret-oci-vault-kms

Oracle Cloud Infrastructure (OCI) Vault + KMS backend for the
Atlas Richie secret platform. Implements a **3-SPI composite**
(`SecretOperations` via Vault `getSecretBundle` +
`KeyWrappingBackend` via KMS `Encrypt` / `Decrypt` +
`SecretBootstrapClient` + `SecretProviderSession`); 1:1
functional parity with Java
`atlas-richie-secret-provider-oci` (post-SDK-refactor).

## Capability matrix (mirrors Java SDK transport)

| Capability            | OCI backend |
|-----------------------|----------------|
| `SECRET_READ`         | ✅ Vault `getSecretBundle` |
| `SECRET_VERSIONING`   | ✅ Vault `versionNumber` / `stage` / `secretVersionName` |
| `KEY_WRAP`            | ✅ KMS `Encrypt` |
| `KEY_UNWRAP`          | ✅ KMS `Decrypt` |
| `KEY_SIGN`            | ❌ no Sign operation |
| AAD on `unwrap_key`   | ✅ `associatedData` map (Base64 + sorted JSON) |
| `SECRET_LIST`         | ❌ no list API |
| `SECRET_WRITE`        | ❌ no write API |
| `SECRET_DELETE`       | ❌ no delete API |

## SDK approach

The `oci` package is the official OCI Python SDK. Two
clients are used:

- `oci.secrets.SecretsClient` — `get_secret_bundle`
- `oci.key_management.KmsCryptoClient` — `encrypt` /
  `decrypt`

Authentication uses the OCI **Instance Principal**
(`NONE` auth type) or **Resource Principal**
(`WORKLOAD_IDENTITY_TOKEN_FILE` auth type). API-key auth
is rejected (`SEC-BOOT-003`) because the OCI SDK does not
support it in the same way as a stand-alone REST client.

The SDK is opt-in via the `optional-dependency [sdk]`
extra. Importing the wheel does NOT require the SDK;
`OciClientFactory.create` raises
`SecretConfigurationException("SEC-BOOT-003", ...)` with a
hint to `pip install
'atlas-richie-secret-oci-vault-kms[sdk]'` if the SDK is
missing.

## SDK type isolation

The wheel defines two `runtime_checkable` Protocols:

- `VaultLike` —
  `get_secret_bundle(secret_id, version_number, stage,
  secret_version_name) -> OciVaultSecret | None`
- `KmsLike` — `encrypt(key_id, plaintext_b64, associated_data) ->
  OciKmsEncryptResponse` / `decrypt(key_id, ciphertext,
  associated_data) -> OciKmsDecryptResponse`

The real SDK clients are wrapped in private
`_OciVaultAdapter` / `_OciKmsAdapter` (in `factory.py`)
that translate SDK Request / Response model fields to the
framework's frozen-dataclass responses. SDK types never
cross the public boundary.

## AAD handling

OCI KMS `associatedData` is a `dict(str, str)`. The
framework's AAD `Mapping[str, str]` is passed through
unchanged (sorted by key for stability). **Unlike Tencent
or Huawei**, no base64 encoding is applied — both sides
already agree on the string-map shape.

## NotFound boundary (mirrors Java SDK transport)

The OCI Python SDK raises `oci.exceptions.BmcException`
with `.status == 404` when a Secret does not exist. The
client maps this to `SecretIntegrityException`; the
framework treats this as a hard error (no silent `None`
return — the Java transport also returns `null` from
`read()`, but the Python side reports the missing Secret
as integrity failure to match the unified framework
contract).

## Install

```bash
pip install 'atlas-richie-secret-oci-vault-kms[sdk]'
```

## Quick start

```python
from atlas_richie.secret_oci_vault_kms import (
    AuthType,
    OciSecretProperties,
    OciSecretProviderFactory,
)

properties = OciSecretProperties(
    region="us-ashburn-1",
    auth_type=AuthType.NONE,  # Instance Principal
    secret_endpoint="https://secrets.us-ashburn-1.oraclecloud.com",
    kms_endpoint="https://kms.us-ashburn-1.oraclecloud.com",
    secrets={"db-password": "ocid1.vaultsecret.oc1..abcd"},
    kms_key_bindings={"envelope": "ocid1.key.oc1..deadbeef"},
)
factory = OciSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
value = session.read(SecretReference(path="db-password"))
session.close()
```

## Environment

Prefix `ATLAS_RICHIE_SECRET_OCI_`; fields cover region /
secret_endpoint / kms_endpoint / auth_type /
workload_identity_token_file / secrets /
kms_key_bindings / timeouts.

## Legacy REST config rejected

The wheel does NOT accept the legacy `wire.*` / `tls.*`
/ `proxy.*` fields — those are not part of this
Provider's contract. Configuring them is silently
ignored on the Java side too (R-242 SDK refactor
mandate). Python's `OciSecretProperties` simply has
no such fields.

## See also

- `atlas-richie-secret-core` — framework + Protocols +
  `crypto.capability` AAD gate (R-242)
- `atlas-richie-secret-tencent-ssm-kms` — sibling
  3-SPI scope backend (also Vault + KMS)
- `docs/acceptance/R-246-secret-oci-vault-kms-handoff.md`
  — design + verification
