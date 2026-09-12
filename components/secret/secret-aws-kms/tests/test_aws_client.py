"""`AwsSecretClient` integration tests — Secrets Manager + KMS vs localstack.

中文
----
覆盖 5 个 SPI 角色:
- `SecretOperations` — get / get_version / get_metadata / exists / list
- `KeyWrappingBackend` — wrap_key (GenerateDataKey) / unwrap_key (Decrypt)
- `SigningBackend` — sign / verify (RSA-2048 CMK, RSASSA_PSS_SHA_256)
- `SecretBootstrapClient` — STARTUP 必填 + optional 容忍
- `SecretProviderSession` — close idempotent + post-close raises

`aws_secret_name_factory` fixture 自动清理(force delete),
测试间互不污染。

English
--------
End-to-end integration tests against localstack on
`127.0.0.1:4566`. Covers all 5 SPI roles of the composite
`AwsSecretClient`. Per-test CMKs and secret names are
isolated and torn down by fixtures.
"""

from __future__ import annotations

import pytest

from atlas_richie.secret import (
    SecretException,
    SecretIntegrityException,
    SecretReference,
    SecretVersion,
    SecretVersionSelector,
)
from atlas_richie.secret.bootstrap.catalog import (
    RequiredWhen,
    SecretBinding,
    SecretBindingCatalog,
)
from atlas_richie.secret.bootstrap.spi import (
    DefaultBootstrapContext,
    SecretBootstrapRequest,
)
from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyPurpose,
    KeyReference,
)
from atlas_richie.secret.metadata import SecretBackend


pytestmark = pytest.mark.integration


# --- Secrets Manager: SecretOperations -----------------------------------


def test_sm_get_roundtrip(aws_session, aws_sm_client, aws_secret_name_factory) -> None:
    name = aws_secret_name_factory("get")
    aws_sm_client.create_secret(Name=name, SecretString='{"password":"s3cret"}')
    ref = SecretReference(provider=aws_session.descriptor.name, path=name)
    value = aws_session.get(ref)
    assert value.plaintext == b'{"password":"s3cret"}'
    assert value.metadata.backend is SecretBackend.AWS


def test_sm_get_versioned_roundtrip(aws_session, aws_sm_client, aws_secret_name_factory) -> None:
    name = aws_secret_name_factory("versioned")
    aws_sm_client.create_secret(Name=name, SecretString='{"v":"1"}')
    aws_sm_client.put_secret_value(SecretId=name, SecretString='{"v":"2"}')
    ref = SecretReference(provider=aws_session.descriptor.name, path=name)
    latest = aws_session.get(ref)
    assert latest.plaintext == b'{"v":"2"}'
    # Find the version that is NOT the AWSCURRENT stage; pin
    # to it via `get_version` and assert we recover v1.
    versions = aws_sm_client.list_secret_version_ids(SecretId=name)["Versions"]
    v1_id = next(
        v["VersionId"] for v in versions
        if "AWSCURRENT" not in v.get("VersionStages", [])
    )
    pinned = ref.with_version(
        SecretVersionSelector.of_static(SecretVersion(number=v1_id)),
    )
    old = aws_session.get(pinned)
    assert old.plaintext == b'{"v":"1"}'


def test_sm_get_metadata(aws_session, aws_sm_client, aws_secret_name_factory) -> None:
    name = aws_secret_name_factory("meta")
    aws_sm_client.create_secret(Name=name, SecretString='{"x":1}')
    ref = SecretReference(provider=aws_session.descriptor.name, path=name)
    md = aws_session.get_metadata(ref)
    assert md.backend is SecretBackend.AWS
    assert md.version.number  # version id assigned by SM


def test_sm_exists_true_and_false(aws_session, aws_sm_client, aws_secret_name_factory) -> None:
    name = aws_secret_name_factory("exists")
    aws_sm_client.create_secret(Name=name, SecretString='{"x":1}')
    ref_present = SecretReference(provider=aws_session.descriptor.name, path=name)
    ref_absent = SecretReference(
        provider=aws_session.descriptor.name,
        path=f"r-235/missing/{name.split('/')[-1]}",
    )
    assert aws_session.exists(ref_present) is True
    assert aws_session.exists(ref_absent) is False


def test_sm_missing_raises_integrity(aws_session) -> None:
    ref = SecretReference(
        provider=aws_session.descriptor.name,
        path="r-235/definitely/missing/path",
    )
    with pytest.raises(SecretIntegrityException):
        aws_session.get(ref)


def test_sm_list(aws_session, aws_sm_client, aws_secret_name_factory) -> None:
    created = []
    for i in range(2):
        name = aws_secret_name_factory(f"list{i}")
        aws_sm_client.create_secret(Name=name, SecretString=f'{{"i":{i}}}')
        created.append(name)
    # Broad listing (boto3's `list_secrets` `Filters` requires
    # the prefix to be a complete secret-name segment, not a
    # path prefix; client-side filter is simpler).
    all_secrets = aws_session.list()
    names = {item.path for item in all_secrets}
    for name in created:
        assert name in names


# --- KMS: KeyWrappingBackend ----------------------------------------------


def test_kms_wrap_unwrap_roundtrip(aws_session, aws_symmetric_cmk) -> None:
    kek = KeyReference(provider="aws", key_id=aws_symmetric_cmk)
    dek = b"a-32-byte-data-encryption-key"
    wrapped = aws_session.wrap_key(dek, kek)
    assert wrapped.algorithm == "aws-kms-symmetric-default"
    assert wrapped.ciphertext  # non-empty KMS CiphertextBlob
    back = aws_session.unwrap_key(
        wrapped, CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP),
    )
    assert back == dek


def test_kms_wrap_rejects_empty_dek(aws_session, aws_symmetric_cmk) -> None:
    kek = KeyReference(provider="aws", key_id=aws_symmetric_cmk)
    with pytest.raises(Exception):
        aws_session.wrap_key(b"", kek)


def test_kms_unwrap_rejects_wrong_algorithm(aws_session, aws_symmetric_cmk) -> None:
    from atlas_richie.secret.crypto import WrappedKey
    bogus = WrappedKey(
        kek_reference=KeyReference(provider="aws", key_id=aws_symmetric_cmk),
        ciphertext=b"dummy",
        algorithm="wrong-alg",
    )
    with pytest.raises(Exception) as exc:
        aws_session.unwrap_key(
            bogus,
            CryptoContext(
                primary_key=KeyReference(provider="aws", key_id=aws_symmetric_cmk),
                purpose=KeyPurpose.WRAP,
            ),
        )
    assert "wrong-alg" in str(exc.value) or "algorithm" in str(exc.value)


# --- KMS: SigningBackend --------------------------------------------------


def test_kms_sign_verify_roundtrip(aws_session, aws_signing_cmk) -> None:
    key = KeyReference(provider="aws", key_id=aws_signing_cmk)
    sig = aws_session.sign(b"hello-aws", key)
    assert sig.algorithm == "RSASSA_PSS_SHA_256"
    assert sig.signature  # non-empty RSA-PSS signature
    assert aws_session.verify(b"hello-aws", sig) is True


def test_kms_verify_rejects_tampered_payload(aws_session, aws_signing_cmk) -> None:
    key = KeyReference(provider="aws", key_id=aws_signing_cmk)
    sig = aws_session.sign(b"original", key)
    assert aws_session.verify(b"tampered", sig) is False


def test_kms_sign_rejects_empty_payload(aws_session, aws_signing_cmk) -> None:
    key = KeyReference(provider="aws", key_id=aws_signing_cmk)
    with pytest.raises(Exception):
        aws_session.sign(b"", key)


# --- Key bindings (logical -> physical) ----------------------------------


def test_kms_key_bindings_resolves_logical_to_physical(
    aws_session, aws_kms_client, aws_symmetric_cmk,
) -> None:
    from atlas_richie.secret_aws_kms import (
        AwsSecretProperties,
        AwsSecretProviderFactory,
    )
    properties = AwsSecretProperties(
        region="us-east-1",
        endpoint_kms="http://127.0.0.1:4566",
        endpoint_sm="http://127.0.0.1:4566",
        kms_key_bindings={"logical-master": aws_symmetric_cmk},
    )
    factory = AwsSecretProviderFactory(
        properties=properties,
        name="aws-key-bindings",
        client_factory=lambda _p: (aws_kms_client, _dummy_sm()),
    )
    session = factory.create(factory.default_configuration())
    try:
        kek = KeyReference(provider="aws", key_id="logical-master")
        dek = b"a-32-byte-data-encryption-key"
        wrapped = session.wrap_key(dek, kek)
        back = session.unwrap_key(
            wrapped, CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP),
        )
        assert back == dek
    finally:
        session.close()


# --- Bootstrap ------------------------------------------------------------


def test_bootstrap_resolves_all(aws_session, aws_sm_client, aws_secret_name_factory) -> None:
    n1 = aws_secret_name_factory("boot/db")
    n2 = aws_secret_name_factory("boot/api")
    aws_sm_client.create_secret(Name=n1, SecretString='{"password":"db"}')
    aws_sm_client.create_secret(Name=n2, SecretString='{"token":"abc"}')
    catalog = SecretBindingCatalog(
        name="boot",
        bindings=(
            SecretBinding(
                name="DB_PASSWORD",
                reference=SecretReference(
                    provider=aws_session.descriptor.name, path=n1,
                ),
                required_when=RequiredWhen.STARTUP,
            ),
            SecretBinding(
                name="API_TOKEN",
                reference=SecretReference(
                    provider=aws_session.descriptor.name, path=n2,
                ),
                required_when=RequiredWhen.STARTUP,
            ),
        ),
    )
    result = aws_session.bootstrap(
        SecretBootstrapRequest(catalog=catalog),
        DefaultBootstrapContext(),
    )
    assert set(result.resolved.keys()) == {"DB_PASSWORD", "API_TOKEN"}
    assert result.missing == ()


def test_bootstrap_raises_on_missing_startup(aws_session) -> None:
    catalog = SecretBindingCatalog(
        name="boot-missing",
        bindings=(
            SecretBinding(
                name="NEVER",
                reference=SecretReference(
                    provider=aws_session.descriptor.name,
                    path="r-235/never/exists",
                ),
                required_when=RequiredWhen.STARTUP,
            ),
        ),
    )
    with pytest.raises(SecretException) as exc:
        aws_session.bootstrap(
            SecretBootstrapRequest(catalog=catalog),
            DefaultBootstrapContext(),
        )
    assert "NEVER" in str(exc.value)


def test_bootstrap_tolerates_missing_optional(aws_session) -> None:
    catalog = SecretBindingCatalog(
        name="boot-optional",
        bindings=(
            SecretBinding(
                name="MAYBE",
                reference=SecretReference(
                    provider=aws_session.descriptor.name,
                    path="r-235/maybe/exists",
                ),
                required_when=RequiredWhen.OPTIONAL,
            ),
        ),
    )
    result = aws_session.bootstrap(
        SecretBootstrapRequest(catalog=catalog),
        DefaultBootstrapContext(),
    )
    assert result.resolved == {}
    assert result.missing == ("MAYBE",)


# --- Session lifecycle ---------------------------------------------------


def test_session_close_is_idempotent(aws_session) -> None:
    aws_session.close()
    aws_session.close()
    assert aws_session.is_closed


def test_post_close_raises(aws_session) -> None:
    aws_session.close()
    ref = SecretReference(
        provider=aws_session.descriptor.name, path="any",
    )
    with pytest.raises(SecretException) as exc:
        aws_session.get(ref)
    assert "is closed" in str(exc.value)


def test_descriptor_and_configuration(aws_session) -> None:
    d = aws_session.descriptor
    cfg = aws_session.configuration
    assert d.name == aws_session.descriptor.name
    assert d.backend is SecretBackend.AWS
    assert d.version == "0.2.0"
    assert cfg.namespace == "us-east-1"


def test_writer_and_deletable_are_none(aws_session) -> None:
    """`AwsSecretClient` is read-only at the framework level,
    matching Java's `AwsSecretClient` (which does not
    implement `SecretWriter` / `SecretDeletable`)."""
    assert aws_session.writer is None
    assert aws_session.deletable is None


# --- Helper --------------------------------------------------------------


def _dummy_sm():
    """Return a stub Secrets Manager client. The key-bindings
    test only exercises `wrap_key` / `unwrap_key`, so the SM
    client is never called."""
    from unittest.mock import MagicMock
    return MagicMock()
