"""Unit tests for `AliyunSecretClient`。

中文
----
覆盖 4-SPI composite 行为 + 错误映射 + lifecycle:

- `read` 走 mapping 路径(JSON 字段抽取) / fallback 路径(物理名拼
  接) / binary 路径(base64 解码) / 非 scalar 字段 SEC-STORE-003
- `metadata` 返回 version + created_at + tags
- `wrap_key` 空明文 SEC-CRYPTO-001;无 key binding SEC-KEY-001;
  wrap+unwrap 往返保留 bytes
- `unwrap_key` algorithm 不匹配 SEC-CRYPTO-002;`key_id` 不匹配
  SEC-CRYPTO-002
- `load(request, missing_policy)` 合并 + flatten;key 冲突 SEC-STORE-003;
  MissingPolicy.LOCAL 静默;MissingPolicy.FAIL 抛 SEC-STORE-001
- `descriptor` 4 capabilities
- `close()` 幂等

English
--------
4-SPI composite behaviour + error translation + lifecycle. Each
test uses a real `FakeAliyunGateway` (no `MagicMock`) so the data
flow is exercised end-to-end. The Alibaba SDK is not required for
this suite.
"""

from __future__ import annotations

import base64

import pytest

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
from atlas_richie.secret.errors import (
    SecretBootstrapException,
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret.reference import SecretReference

from atlas_richie.secret_aliyun_kms.client import (
    AliyunBootstrapLoadResult,
    AliyunSecretClient,
    MissingPolicy,
)
from atlas_richie.secret_aliyun_kms.properties import AliyunSecretMapping

from tests.conftest import (  # type: ignore[import-not-found]
    FakeAliyunGateway,
    decode_base64,
    fake_aliyun_gateway,
    make_resolved,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reference(path: str) -> SecretReference:
    return SecretReference(provider="aliyun", path=path)


def _build_client(
    gateway: FakeAliyunGateway,
    *,
    properties=None,
    **overrides,
) -> AliyunSecretClient:
    resolved = make_resolved(**(properties or overrides))
    return AliyunSecretClient(resolved=resolved, gateway=gateway)


def _bootstrap_request(
    bindings: tuple[SecretBinding, ...],
    *,
    environment: str = "default",
    required_when_override: str | None = None,
) -> SecretBootstrapRequest:
    catalog = SecretBindingCatalog(name="test", bindings=bindings)
    return SecretBootstrapRequest(
        catalog=catalog,
        environment=environment,
        required_when_override=required_when_override,
    )


# ---------------------------------------------------------------------------
# `read` — field extraction / fallback / binary
# ---------------------------------------------------------------------------


class TestRead:
    def test_read_mapped_secret_with_field_extraction(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        # physical secret: prod/db (a JSON document with `password`).
        fake_aliyun_gateway.put(
            "prod/db",
            secret_data='{"username": "app", "password": "s3cret"}',
            version_id="v3",
        )
        client = _build_client(
            fake_aliyun_gateway,
            secrets={"db.password": AliyunSecretMapping(
                secret_name="prod/db", field="password"
            )},
        )
        with client.read(_reference("db.password")) as handle:
            assert handle.value.plaintext == b"s3cret"
            assert handle.value.metadata.version.number == "v3"

    def test_read_unmapped_secret_falls_back_to_path_prefix(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        # No `secrets` mapping → build physical name as
        # `<path_prefix>/atlas-richie/<env>/<logical>/runtime`.
        fake_aliyun_gateway.put(
            "my-team/atlas-richie/default/api-token/runtime",
            secret_data="raw-token-bytes",
            version_id="v1",
        )
        client = _build_client(
            fake_aliyun_gateway,
            secrets_manager_path_prefix="my-team",
        )
        with client.read(_reference("api-token")) as handle:
            assert handle.value.plaintext == b"raw-token-bytes"

    def test_read_unmapped_secret_fallback_no_prefix(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        # No `secrets_manager_path_prefix` → physical name is
        # `atlas-richie/<env>/<logical>/runtime`.
        fake_aliyun_gateway.put(
            "atlas-richie/default/api-token/runtime",
            secret_data="raw-token-bytes",
            version_id="v1",
        )
        client = _build_client(fake_aliyun_gateway)
        with client.read(_reference("api-token")) as handle:
            assert handle.value.plaintext == b"raw-token-bytes"

    def test_read_binary_secret_base64_decoding(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        # Binary payload: the SDK stores the base64 form on the wire.
        original = b"\x00\x01\x02\x03binary\xff"
        fake_aliyun_gateway.put(
            "prod/binary",
            secret_data=base64.b64encode(original).decode("ascii"),
            secret_data_type="Binary",
            version_id="v1",
        )
        client = _build_client(
            fake_aliyun_gateway,
            secrets={"blob": AliyunSecretMapping(secret_name="prod/binary")},
        )
        with client.read(_reference("blob")) as handle:
            assert handle.value.plaintext == original

    def test_read_json_field_not_scalar_raises_store_003(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        fake_aliyun_gateway.put(
            "prod/db",
            secret_data='{"creds": {"user": "a", "pass": "b"}}',
            version_id="v1",
        )
        client = _build_client(
            fake_aliyun_gateway,
            secrets={"db.password": AliyunSecretMapping(
                secret_name="prod/db", field="creds"
            )},
        )
        with pytest.raises(SecretBootstrapException) as exc:
            client.read(_reference("db.password"))
        assert "SEC-STORE-003" in str(exc.value)

    def test_read_not_found_raises_integrity(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        # Gateway returns `None` for a missing secret.
        client = _build_client(fake_aliyun_gateway)
        with pytest.raises(SecretIntegrityException) as exc:
            client.read(_reference("missing"))
        assert "not found" in str(exc.value).lower()

    def test_read_session_closed_raises(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        client = _build_client(fake_aliyun_gateway)
        client.close()
        with pytest.raises(SecretException):
            client.read(_reference("anything"))


# ---------------------------------------------------------------------------
# `metadata` — version + created_at
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_metadata_returns_version_and_created_at(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        fake_aliyun_gateway.put(
            "prod/db",
            secret_data="v",
            version_id="v42",
            version_stages=("ACSCurrent", "ACSPrevious"),
        )
        client = _build_client(
            fake_aliyun_gateway,
            secrets={"db": AliyunSecretMapping(secret_name="prod/db")},
        )
        metadata = client.get_metadata(_reference("db"))
        assert metadata.version.number == "v42"
        assert metadata.created_at is not None
        assert metadata.backend is SecretBackend.ALIYUN
        assert metadata.tags["provider"] == "aliyun"
        assert "ACSCurrent" in metadata.tags["stages"]

    def test_exists_returns_false_when_missing(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        client = _build_client(fake_aliyun_gateway)
        assert client.exists(_reference("nope")) is False

    def test_exists_returns_true_when_present(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        fake_aliyun_gateway.put("prod/db", secret_data="v")
        client = _build_client(
            fake_aliyun_gateway,
            secrets={"db": AliyunSecretMapping(secret_name="prod/db")},
        )
        assert client.exists(_reference("db")) is True


# ---------------------------------------------------------------------------
# `wrap_key` / `unwrap_key` — symmetric envelope
# ---------------------------------------------------------------------------


class TestWrapUnwrap:
    def test_wrap_empty_plaintext_raises_crypto_001(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        client = _build_client(
            fake_aliyun_gateway,
            kms_key_bindings={"cmk-a": "id-a"},
        )
        with pytest.raises(SecretCryptoException) as exc:
            client.wrap_key(
                dek=b"",
                kek=KeyReference(provider="aliyun", key_id="cmk-a"),
            )
        assert "SEC-CRYPTO-001" in str(exc.value)

    def test_wrap_no_key_binding_raises_key_001(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        client = _build_client(fake_aliyun_gateway)
        with pytest.raises(SecretConfigurationException) as exc:
            client.wrap_key(
                dek=b"some-dek",
                kek=KeyReference(provider="aliyun", key_id="missing-key"),
            )
        assert "SEC-KEY-001" in str(exc.value)

    def test_wrap_and_unwrap_round_trip_preserves_plaintext(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        # Use a custom `encrypt` echo that records the physical key id
        # in the response so `unwrap` can verify it.
        original_plaintext = b"my-secret-dek-bytes-32-bytes!!"  # 28 bytes
        client = _build_client(
            fake_aliyun_gateway,
            kms_key_bindings={"cmk-a": "id-a"},
        )
        kek = KeyReference(provider="aliyun", key_id="cmk-a")
        wrapped = client.wrap_key(dek=original_plaintext, kek=kek)
        assert wrapped.algorithm == "aliyun-kms-symmetric-default"
        assert wrapped.kek_reference == kek
        # The fake gateway produces a `cipher:` prefix; decoding must
        # round-trip back to the original bytes.
        plaintext = client.unwrap_key(
            wrapped=wrapped,
            context=CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP),
        )
        assert plaintext == original_plaintext

    def test_unwrap_wrong_algorithm_raises_crypto_002(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        from atlas_richie.secret.crypto import WrappedKey

        client = _build_client(
            fake_aliyun_gateway,
            kms_key_bindings={"cmk-a": "id-a"},
        )
        wrapped = WrappedKey(
            kek_reference=KeyReference(provider="aliyun", key_id="cmk-a"),
            ciphertext=b"x",
            algorithm="aws-kms-symmetric-default",
        )
        with pytest.raises(SecretCryptoException) as exc:
            client.unwrap_key(
                wrapped=wrapped,
                context=CryptoContext(
                    primary_key=KeyReference(provider="aliyun", key_id="cmk-a"),
                    purpose=KeyPurpose.WRAP,
                ),
            )
        assert "SEC-CRYPTO-002" in str(exc.value)

    def test_unwrap_key_id_mismatch_raises_crypto_002(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        # Override `decrypt` to return a different `key_id` than the
        # one we asked for. The client must catch the mismatch and
        # raise SEC-CRYPTO-002.
        from atlas_richie.secret_aliyun_kms.client import AliyunDecryptResponse

        class MismatchedGateway(FakeAliyunGateway):
            def decrypt(self, ciphertext_blob, encryption_context):
                self.decrypt_calls.append(
                    {
                        "ciphertext_blob": ciphertext_blob,
                        "encryption_context": dict(encryption_context),
                    }
                )
                # Always report a wrong key id.
                return AliyunDecryptResponse(
                    plaintext=base64.b64encode(b"anything").decode("ascii"),
                    key_id="some-other-key",
                    request_id="req-x",
                )

            def encrypt(self, key_id, plaintext_b64, encryption_context):
                return super().encrypt(key_id, plaintext_b64, encryption_context)

        gateway = MismatchedGateway()
        client = _build_client(
            gateway,
            kms_key_bindings={"cmk-a": "id-a"},
        )
        kek = KeyReference(provider="aliyun", key_id="cmk-a")
        wrapped = client.wrap_key(dek=b"dek", kek=kek)
        with pytest.raises(SecretCryptoException) as exc:
            client.unwrap_key(
                wrapped=wrapped,
                context=CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP),
            )
        assert "SEC-CRYPTO-002" in str(exc.value)

    def test_unwrap_empty_ciphertext_raises_crypto_002(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        from atlas_richie.secret.crypto import WrappedKey

        client = _build_client(
            fake_aliyun_gateway,
            kms_key_bindings={"cmk-a": "id-a"},
        )
        kek = KeyReference(provider="aliyun", key_id="cmk-a")
        wrapped = WrappedKey(
            kek_reference=kek,
            ciphertext=b"",
            algorithm="aliyun-kms-symmetric-default",
        )
        with pytest.raises(SecretCryptoException) as exc:
            client.unwrap_key(
                wrapped=wrapped,
                context=CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP),
            )
        assert "SEC-CRYPTO-002" in str(exc.value)


# ---------------------------------------------------------------------------
# `load` — flatten + merge + missing policy
# ---------------------------------------------------------------------------


def _binding(name: str, path: str, *, required: bool = True) -> SecretBinding:
    return SecretBinding(
        name=name,
        reference=_reference(path),
        required_when=RequiredWhen.STARTUP if required else RequiredWhen.LAZY,
    )


class TestLoad:
    def test_load_merges_flattens_multiple_secrets(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        fake_aliyun_gateway.put(
            "prod/db",
            secret_data='{"username": "app", "password": "s3cret"}',
            version_id="v1",
        )
        fake_aliyun_gateway.put(
            "prod/api",
            secret_data='{"token": "tok-1", "scopes": ["read", "write"]}',
            version_id="v1",
        )
        client = _build_client(
            fake_aliyun_gateway,
            secrets={
                "db": AliyunSecretMapping(secret_name="prod/db"),
                "api": AliyunSecretMapping(secret_name="prod/api"),
            },
        )
        request = _bootstrap_request(
            (
                _binding("db", "db"),
                _binding("api", "api"),
            )
        )
        result = client.load(request)
        assert isinstance(result, AliyunBootstrapLoadResult)
        # Each binding contributes its flattened JSON keys directly
        # (no binding-name prefix); conflict detection works at the
        # top level of the merged map.
        assert result.merged["username"] == "app"
        assert result.merged["password"] == "s3cret"
        assert result.merged["token"] == "tok-1"
        assert result.merged["scopes[0]"] == "read"
        assert result.merged["scopes[1]"] == "write"
        assert result.paths_loaded
        assert len(result.version_digest) == 64  # SHA-256 hex

    def test_load_conflict_raises_store_003(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        # Two secrets both expose a key `shared.thing` with
        # different values; the merge must reject.
        fake_aliyun_gateway.put(
            "prod/a",
            secret_data='{"shared": {"thing": "alpha"}}',
            version_id="v1",
        )
        fake_aliyun_gateway.put(
            "prod/b",
            secret_data='{"shared": {"thing": "beta"}}',
            version_id="v1",
        )
        client = _build_client(
            fake_aliyun_gateway,
            secrets={
                "a": AliyunSecretMapping(secret_name="prod/a"),
                "b": AliyunSecretMapping(secret_name="prod/b"),
            },
        )
        request = _bootstrap_request(
            (_binding("a", "a"), _binding("b", "b"))
        )
        with pytest.raises(SecretBootstrapException) as exc:
            client.load(request)
        assert "SEC-STORE-003" in str(exc.value)
        assert "shared.thing" in str(exc.value)

    def test_load_missing_with_local_policy_skips_silently(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        fake_aliyun_gateway.put(
            "prod/a",
            secret_data='{"k": "v"}',
            version_id="v1",
        )
        # `b` is not seeded → gateway returns `None`.
        client = _build_client(
            fake_aliyun_gateway,
            secrets={
                "a": AliyunSecretMapping(secret_name="prod/a"),
                "b": AliyunSecretMapping(secret_name="prod/missing"),
            },
        )
        request = _bootstrap_request(
            (_binding("a", "a"), _binding("b", "b"))
        )
        result = client.load(request, missing_policy=MissingPolicy.LOCAL)
        # `b` is silently skipped, only `a`'s keys appear in `merged`.
        assert result.merged == {"k": "v"}
        assert "prod/missing" not in result.paths_loaded
        # The result also records which binding names loaded
        # successfully — `a` loaded, `b` was skipped.
        assert result.binding_names == ("a",)

    def test_load_missing_with_fail_policy_raises(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        # `b` is not seeded → gateway returns `None`. With
        # MissingPolicy.FAIL, the call must raise SEC-STORE-001.
        client = _build_client(
            fake_aliyun_gateway,
            secrets={
                "a": AliyunSecretMapping(secret_name="prod/missing-a"),
                "b": AliyunSecretMapping(secret_name="prod/missing-b"),
            },
        )
        request = _bootstrap_request(
            (_binding("a", "a"), _binding("b", "b"))
        )
        with pytest.raises(SecretBootstrapException) as exc:
            client.load(request)
        assert "SEC-STORE-001" in str(exc.value)

    def test_load_records_last_request_id(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        fake_aliyun_gateway.put(
            "prod/db",
            secret_data='{"k": "v"}',
            version_id="v1",
            request_id="rid-7",
        )
        client = _build_client(
            fake_aliyun_gateway,
            secrets={"db": AliyunSecretMapping(secret_name="prod/db")},
        )
        request = _bootstrap_request((_binding("db", "db"),))
        result = client.load(request)
        assert result.last_request_id == "rid-7"

    def test_load_handles_non_dict_top_level(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        # A non-dict / non-list payload (e.g. a JSON-encoded string)
        # flattens to a single entry keyed by the empty string.
        # The important contract here is: a top-level string does
        # NOT raise; it contributes a single key/value pair.
        fake_aliyun_gateway.put(
            "prod/scalar",
            secret_data='"just-a-string"',
            version_id="v1",
        )
        client = _build_client(
            fake_aliyun_gateway,
            secrets={"scalar": AliyunSecretMapping(secret_name="prod/scalar")},
        )
        request = _bootstrap_request((_binding("scalar", "scalar"),))
        result = client.load(request)
        assert result.merged[""] == "just-a-string"


# ---------------------------------------------------------------------------
# `descriptor` + lifecycle
# ---------------------------------------------------------------------------


class TestDescriptorAndLifecycle:
    def test_descriptor_declares_aliyun_backend_and_capability(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        client = _build_client(fake_aliyun_gateway)
        d = client.descriptor
        assert d.backend is SecretBackend.ALIYUN
        assert d.name == "aliyun-test"
        assert d.capability.can_read is True
        assert d.capability.can_write is False
        assert d.capability.can_rotate is True
        assert d.capability.can_list is False
        assert d.capability.signs_values is False
        assert d.version == "0.2.0"

    def test_descriptor_capability_matches_resolved(self, fake_aliyun_gateway: FakeAliyunGateway) -> None:
        client = _build_client(fake_aliyun_gateway)
        # The capability published on the descriptor must equal the
        # static capability carried in the resolved configuration.
        assert client.descriptor.capability == client._resolved.capability  # noqa: SLF001

    def test_close_is_idempotent(self, fake_aliyun_gateway: FakeAliyunGateway) -> None:
        client = _build_client(fake_aliyun_gateway)
        client.close()
        client.close()  # second call is a no-op
        assert client.is_closed is True
        assert fake_aliyun_gateway.closed is True

    def test_operations_property_returns_self(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        client = _build_client(fake_aliyun_gateway)
        assert client.operations is client

    def test_writer_and_deletable_return_none(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        client = _build_client(fake_aliyun_gateway)
        assert client.writer is None
        assert client.deletable is None

    def test_signing_returns_none(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        # Alibaba symmetric KMS has no sign / verify; the session
        # exposes `signing=None` so `list_capability(session)` can
        # see the absence.
        client = _build_client(fake_aliyun_gateway)
        assert client.signing is None


# ---------------------------------------------------------------------------
# Configuration object surfaces (smoke)
# ---------------------------------------------------------------------------


class TestConfigurationAndProvider:
    def test_configuration_object(self, fake_aliyun_gateway: FakeAliyunGateway) -> None:
        client = _build_client(
            fake_aliyun_gateway,
            endpoint="https://kms.cn-hangzhou.aliyuncs.com",
            ca_file="/etc/ssl/ca.pem",
            secrets_manager_path_prefix="my-team",
        )
        cfg = client.configuration
        assert cfg.name == "aliyun-test"
        assert cfg.parameters["region"] == "cn-hangzhou"
        assert cfg.parameters["endpoint"].startswith("https://")
        assert cfg.parameters["ca_file"] == "/etc/ssl/ca.pem"
        assert cfg.parameters["secrets_manager_path_prefix"] == "my-team"
        assert cfg.namespace == "cn-hangzhou"
        assert cfg.retries == 3


# ---------------------------------------------------------------------------
# `bootstrap` — framework entry bridging to `load(...)`
# ---------------------------------------------------------------------------


class TestBootstrapFrameworkEntry:
    def test_bootstrap_returns_resolved_and_missing(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        # `a` is present, `b` is missing with `required_when=LAZY`
        # → must appear in `missing` without raising.
        fake_aliyun_gateway.put(
            "prod/a",
            secret_data='{"k": "v"}',
            version_id="v1",
        )
        client = _build_client(
            fake_aliyun_gateway,
            secrets={
                "a": AliyunSecretMapping(secret_name="prod/a"),
                "b": AliyunSecretMapping(secret_name="prod/missing"),
            },
        )
        request = _bootstrap_request(
            (
                _binding("a", "a", required=True),
                _binding("b", "b", required=False),
            )
        )
        result = client.bootstrap(request, DefaultBootstrapContext())
        assert "a" in result.resolved
        assert "b" in result.missing
        assert result.missing == ("b",)

    def test_bootstrap_startup_required_raises(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        client = _build_client(
            fake_aliyun_gateway,
            secrets={"x": AliyunSecretMapping(secret_name="prod/missing")},
        )
        request = _bootstrap_request((_binding("x", "x", required=True),))
        with pytest.raises(SecretException) as exc:
            client.bootstrap(request, DefaultBootstrapContext())
        assert "SEC-STORE-001" in str(exc.value)

    def test_bootstrap_resolves_secret_value(
        self, fake_aliyun_gateway: FakeAliyunGateway
    ) -> None:
        fake_aliyun_gateway.put(
            "prod/a",
            secret_data='{"k": "v"}',
            version_id="v1",
        )
        client = _build_client(
            fake_aliyun_gateway,
            secrets={"a": AliyunSecretMapping(secret_name="prod/a")},
        )
        request = _bootstrap_request((_binding("a", "a"),))
        result = client.bootstrap(request, DefaultBootstrapContext())
        value = result.resolved["a"]
        # The framework's `get(reference)` returns raw bytes (the
        # whole JSON document for a non-field-extracted read).
        assert value.plaintext == b'{"k": "v"}'
