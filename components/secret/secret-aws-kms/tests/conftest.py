"""Integration test fixtures for `atlas-richie-secret-aws-kms`.

中文
----
集成测试连真 localstack(`127.0.0.1:4566`,env
`ATLAS_RICHIE_SECRET_AWS_TEST_ENDPOINT_KMS` /
`_TEST_ENDPOINT_SM` 可覆盖,生产用真 AWS 时这俩是 `None`)。
localstack 必须启用 `kms` + `secretsmanager` 服务,默认凭证
`test/test`(`AWS_ACCESS_KEY_ID=test`,`AWS_SECRET_ACCESS_KEY=test`)。

每个 test 启动前:

1. 确认 localstack reachable(`curl /_localstack/health`,
   期望 `kms` + `secretsmanager` 都标 `available`);不可达
   整个 module skip
2. 创建一个**新的对称 CMK**(`CreateKey` 每次返回新 ARN,避免
   测试间 state leak)
3. 创建一个 RSA-2048 签名 CMK(用于 sign / verify 测试,
   对称 CMK 不支持 sign)

如果 localstack 不可达,所有 test 自动 skip(`pytest.skip`),
不阻塞没 localstack 的 CI。

English
--------
Integration fixtures for localstack on `127.0.0.1:4566`.
Tests skip when localstack is unreachable. Each test creates
its own KMS CMK (symmetric for wrap, RSA-2048 for sign) and
its own Secrets Manager secret to stay isolated.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator

import boto3
import botocore.exceptions
import pytest

from atlas_richie.secret_aws_kms import (
    AwsSecretProperties,
    AwsSecretProviderFactory,
    AwsSecretClient,
)

AWS_REGION = os.environ.get(
    "ATLAS_RICHIE_SECRET_AWS_TEST_REGION",
    "us-east-1",
)
AWS_ACCESS_KEY_ID = os.environ.get(
    "ATLAS_RICHIE_SECRET_AWS_TEST_ACCESS_KEY_ID",
    "test",
)
AWS_SECRET_ACCESS_KEY = os.environ.get(
    "ATLAS_RICHIE_SECRET_AWS_TEST_SECRET_ACCESS_KEY",
    "test",
)
ENDPOINT_KMS = os.environ.get(
    "ATLAS_RICHIE_SECRET_AWS_TEST_ENDPOINT_KMS",
    "http://127.0.0.1:4566",
)
ENDPOINT_SM = os.environ.get(
    "ATLAS_RICHIE_SECRET_AWS_TEST_ENDPOINT_SM",
    "http://127.0.0.1:4566",
)


def _localstack_reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/_localstack/health", timeout=2) as response:  # noqa: S310 - dev only
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _boto_kwargs() -> dict[str, object]:
    return {
        "region_name": AWS_REGION,
        "aws_access_key_id": AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
    }


@pytest.fixture
def aws_kms_client() -> Iterator[object]:
    if not _localstack_reachable(ENDPOINT_KMS):
        pytest.skip(f"localstack not reachable at {ENDPOINT_KMS}")
    client = boto3.client("kms", endpoint_url=ENDPOINT_KMS, **_boto_kwargs())
    try:
        yield client
    finally:
        # boto3 clients don't need explicit close, but we let
        # GC handle them. Keeping a teardown hook for clarity.
        _ = client


@pytest.fixture
def aws_symmetric_cmk(aws_kms_client) -> Iterator[str]:
    """A fresh symmetric CMK for wrap / unwrap tests.

    Each test gets its own key; this isolates test state and
    matches the Java side's `keyBindings` indirection (each
    logical key is bound to a physical CMK ARN that may
    rotate).
    """
    response = aws_kms_client.create_key(
        Description=f"r-235-wrap-{uuid.uuid4().hex[:8]}",
        KeyUsage="ENCRYPT_DECRYPT",
        Origin="AWS_KMS",
    )
    yield response["KeyMetadata"]["KeyId"]


@pytest.fixture
def aws_signing_cmk(aws_kms_client) -> Iterator[str]:
    """A fresh RSA-2048 CMK for sign / verify tests.

    AWS KMS asymmetric CMKs are first-class; RSA-2048 supports
    `RSASSA_PSS_SHA_256` and other signing algorithms.
    """
    response = aws_kms_client.create_key(
        Description=f"r-235-sign-{uuid.uuid4().hex[:8]}",
        KeyUsage="SIGN_VERIFY",
        CustomerMasterKeySpec="RSA_2048",
    )
    yield response["KeyMetadata"]["KeyId"]


@pytest.fixture
def aws_sm_client() -> Iterator[object]:
    if not _localstack_reachable(ENDPOINT_SM):
        pytest.skip(f"localstack not reachable at {ENDPOINT_SM}")
    client = boto3.client("secretsmanager", endpoint_url=ENDPOINT_SM, **_boto_kwargs())
    try:
        yield client
    finally:
        _ = client


@pytest.fixture
def aws_session(
    aws_kms_client,
    aws_sm_client,
) -> Iterator[AwsSecretClient]:
    """A fully-wired `AwsSecretClient` for integration tests.

    Uses pre-built boto3 clients (the `aws_kms_client` and
    `aws_sm_client` fixtures) via the factory's
    `client_factory` parameter; no real AWS account needed.
    """
    properties = AwsSecretProperties(
        region=AWS_REGION,
        endpoint_kms=ENDPOINT_KMS,
        endpoint_sm=ENDPOINT_SM,
    )
    provider_id = f"aws-test-{uuid.uuid4().hex[:8]}"
    factory = AwsSecretProviderFactory(
        properties=properties,
        name=provider_id,
        client_factory=lambda _p: (aws_kms_client, aws_sm_client),
    )
    session = factory.create(factory.default_configuration())
    assert isinstance(session, AwsSecretClient)
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def aws_secret_name_factory(aws_sm_client) -> Iterator[str]:
    """Yield a function that returns a fresh SM secret name + cleanup.

    Each test calls the factory to get a unique name; on
    teardown, the secret is force-deleted so the next test
    starts clean.
    """
    written: list[str] = []

    def _make(prefix: str = "test") -> str:
        name = f"r-235/{prefix}/{uuid.uuid4().hex[:10]}"
        written.append(name)
        return name

    yield _make
    for name in written:
        try:
            aws_sm_client.delete_secret(
                SecretId=name, ForceDeleteWithoutRecovery=True,
            )
        except botocore.exceptions.ClientError:
            pass
        except Exception:  # noqa: BLE001
            pass
