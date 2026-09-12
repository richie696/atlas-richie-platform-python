# atlas-richie-secret-aws-kms

AWS Secrets Manager + AWS KMS backend for the Atlas Richie
secret platform. Implements the **5-SPI composite** on top of
two `boto3` clients (`secretsmanager` for read-side, `kms` for
crypto), mirroring Java `atlas-richie-secret-provider-aws` 1:1.

## Two backends, one wheel

| Concern | AWS service | boto3 client | Why |
|---|---|---|---|
| Secret reads (KV v2 equivalent) | Secrets Manager | `boto3.client("secretsmanager")` | Stores plaintext-or-encrypted secrets with versions and labels |
| Key wrap / unwrap (Transit equivalent) | KMS | `boto3.client("kms")` | Generates + decrypts DEKs without ever exposing the master key |
| Sign / verify (Transit sign equivalent) | KMS asymmetric CMK | `boto3.client("kms")` | ECDSA / RSA signing keys are first-class in KMS |

The split mirrors the Java side: Secrets Manager handles
`SecretOperations` (read), KMS handles
`KeyWrappingBackend` + `SigningBackend`.

## Local development

```bash
docker run -d --name localstack \
  -p 4566:4566 \
  -e SERVICES=kms,secretsmanager \
  -e AWS_DEFAULT_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID=test \
  -e AWS_SECRET_ACCESS_KEY=test \
  localstack/localstack:3
```

The `tests/conftest.py` fixture is configured for
`http://127.0.0.1:4566`; tests `pytest.skip` if unreachable.

## Quick start

```python
from atlas_richie.secret_aws_kms import (
    AwsSecretProperties,
    AwsSecretProviderFactory,
)

properties = AwsSecretProperties(
    region="us-east-1",
    profile_name="my-app",  # or env / IAM role
)
factory = AwsSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
assert session.descriptor.backend.value == "aws"
session.close()
```

## Environment

Prefix `ATLAS_RICHIE_SECRET_AWS_`; fields cover
region / auth (default chain / profile) / KMS signing algorithm /
KMS key bindings / Secrets Manager path prefix / endpoints
override (for localstack).

## See also

- `atlas-richie-secret-core` — framework + Protocols
- `atlas-richie-secret-vault` — sibling remote backend wheel
- `docs/acceptance/R-235-secret-aws-kms-handoff.md` — design + verification
