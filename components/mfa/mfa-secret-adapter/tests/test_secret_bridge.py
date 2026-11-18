"""SecretRetriever 桥接：引用解析、错误映射，以及与 MFA 服务的完整闭环。"""

from __future__ import annotations

import pytest

from atlas_richie.mfa_secret_adapter import SecretStoreSecretRetriever
from atlas_richie.mfa_validation import (
    DefaultMfaValidationService,
    InMemoryMfaStateStore,
    MfaUserInfo,
    TotpValidationEngine,
    generate_secret_key,
)
from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend, SecretMetadata
from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret.value import SecretValue

pytestmark = pytest.mark.unit


class FakeOperations:
    """Faithful stand-in for a SecretOperations backend."""

    def __init__(self, secrets: dict[str, bytes] | None = None) -> None:
        self.secrets = secrets or {}
        self.requests: list[SecretReference] = []

    def get(self, reference: SecretReference) -> SecretValue:
        self.requests.append(reference)
        key = f"{reference.provider}:{reference.path}"
        if key not in self.secrets:
            raise SecretIntegrityException(f"secret not found: {key}")
        return SecretValue(
            plaintext=self.secrets[key],
            metadata=SecretMetadata(
                reference=reference, version=SecretVersion("1"),
                backend=SecretBackend.REDIS,
                created_at=None, expires_at=None, tags=frozenset(),
            ),
        )


class TestReferenceParsing:
    def test_provider_path_is_split_on_first_colon(self) -> None:
        store = FakeOperations({"vault-main:totp/users/u1": b"SECRET"})
        retriever = SecretStoreSecretRetriever(store)
        assert retriever.retrieve("vault-main:totp/users/u1") == "SECRET"
        assert store.requests[0].provider == "vault-main"
        assert store.requests[0].path == "totp/users/u1"

    def test_path_may_contain_colons(self) -> None:
        store = FakeOperations({"p:a:b": b"V"})
        assert SecretStoreSecretRetriever(store).retrieve("p:a:b") == "V"

    def test_default_provider_resolves_bare_paths(self) -> None:
        store = FakeOperations({"vault-main:plain/path": b"V"})
        retriever = SecretStoreSecretRetriever(store, default_provider="vault-main")
        assert retriever.retrieve("plain/path") == "V"
        assert store.requests[0].provider == "vault-main"

    def test_explicit_provider_wins_over_default(self) -> None:
        store = FakeOperations({"other:path": b"V"})
        retriever = SecretStoreSecretRetriever(store, default_provider="vault-main")
        assert retriever.retrieve("other:path") == "V"

    def test_no_provider_and_no_default_is_an_error(self) -> None:
        retriever = SecretStoreSecretRetriever(FakeOperations())
        with pytest.raises(ValueError, match="default_provider"):
            retriever.retrieve("just/a/path")

    @pytest.mark.parametrize("reference", ["", "   ", ":", "p:", ":path"])
    def test_malformed_references_rejected(self, reference) -> None:
        retriever = SecretStoreSecretRetriever(FakeOperations(), default_provider="p")
        with pytest.raises(ValueError):
            retriever.retrieve(reference)

    def test_blank_reference_rejected_without_default(self) -> None:
        with pytest.raises(ValueError, match="blank"):
            SecretStoreSecretRetriever(FakeOperations()).retrieve("")

    def test_blank_parts_still_rejected_even_with_default(self) -> None:
        retriever = SecretStoreSecretRetriever(FakeOperations(), default_provider="p")
        with pytest.raises(ValueError):
            retriever.retrieve(":")

    def test_whitespace_is_stripped(self) -> None:
        store = FakeOperations({"p:totp/u": b" JBSWY3DPEHPK3PXP \n"})
        assert SecretStoreSecretRetriever(store).retrieve("p: totp/u ") == "JBSWY3DPEHPK3PXP"


class TestErrorMapping:
    def test_missing_secret_returns_none(self) -> None:
        retriever = SecretStoreSecretRetriever(FakeOperations())
        assert retriever.retrieve("vault-main:absent") is None

    def test_integrity_error_from_backend_maps_to_none(self) -> None:
        class _Broken:
            def get(self, reference):
                raise SecretIntegrityException("gone")

        assert SecretStoreSecretRetriever(_Broken()).retrieve("p:x") is None

    @pytest.mark.parametrize(
        "error",
        [
            SecretException("backend down"),
            SecretCryptoException("decrypt failed"),
            SecretConfigurationException("bad config"),
        ],
    )
    def test_infrastructure_errors_propagate(self, error) -> None:
        """配置/解密故障必须上抛，不得伪装成「未配置 MFA」。"""

        class _Broken:
            def get(self, reference):
                raise error

        with pytest.raises(type(error)):
            SecretStoreSecretRetriever(_Broken()).retrieve("p:x")

    def test_empty_plaintext_maps_to_none(self) -> None:
        store = FakeOperations({"p:x": b"   "})
        assert SecretStoreSecretRetriever(store).retrieve("p:x") is None

    def test_none_operations_rejected(self) -> None:
        with pytest.raises(ValueError):
            SecretStoreSecretRetriever(None)


class TestMfaServiceLoop:
    """桥接 + MFA 服务：密钥存进 store，经引用读回并完成验证。"""

    def _service(self, store, clock=lambda: 1_700_000_000):
        state = InMemoryMfaStateStore(clock=clock)
        state.put_user_info(
            "u-1", 7,
            MfaUserInfo(
                status="ENABLED",
                secret_reference="vault-main:totp/tenants/7/users/u-1",
                algorithm="SHA1", period=30, digits=6,
            ),
        )
        retriever = SecretStoreSecretRetriever(store, default_provider="vault-main")
        return DefaultMfaValidationService(state, retriever, clock=clock)

    def test_valid_code_verifies_end_to_end(self) -> None:
        secret = generate_secret_key()
        store = FakeOperations({"vault-main:totp/tenants/7/users/u-1": secret.encode()})
        service = self._service(store)
        code = TotpValidationEngine().generate_code(secret, 1_700_000_000 // 30)
        result = service.verify_mfa_code("u-1", 7, code)
        assert result.success is True, result.error_code

    def test_wrong_code_fails(self) -> None:
        secret = generate_secret_key()
        store = FakeOperations({"vault-main:totp/tenants/7/users/u-1": secret.encode()})
        service = self._service(store)
        result = service.verify_mfa_code("u-1", 7, "000000")
        assert result.success is False

    def test_missing_secret_fails_closed_not_as_error(self) -> None:
        service = self._service(FakeOperations())
        result = service.verify_mfa_code("u-1", 7, "123456")
        assert result.success is False

    def test_bare_reference_uses_default_provider(self) -> None:
        secret = generate_secret_key()
        store = FakeOperations({"vault-main:totp/u": secret.encode()})
        state = InMemoryMfaStateStore(clock=lambda: 1_700_000_000)
        state.put_user_info(
            "u", None, MfaUserInfo(status="ENABLED", secret_reference="totp/u")
        )
        retriever = SecretStoreSecretRetriever(store, default_provider="vault-main")
        service = DefaultMfaValidationService(state, retriever, clock=lambda: 1_700_000_000)
        code = TotpValidationEngine().generate_code(secret, 1_700_000_000 // 30)
        assert service.verify_mfa_code("u", None, code).success is True

    def test_crypto_error_is_distinct_from_not_configured(self) -> None:
        """桥接上抛基础设施错误，服务把它映射为 MFA_VERIFY_ERROR 而不是
        「未配置」——两种故障不得混淆。"""
        class _CryptoBroken:
            def get(self, reference):
                raise SecretCryptoException("key unavailable")

        state = InMemoryMfaStateStore()
        state.put_user_info(
            "u-1", 7, MfaUserInfo(status="ENABLED", secret_reference="p:x")
        )
        retriever = SecretStoreSecretRetriever(_CryptoBroken())
        service = DefaultMfaValidationService(state, retriever, clock=lambda: 1_700_000_000)
        result = service.verify_mfa_code("u-1", 7, "123456")
        assert result.success is False
        assert result.error_code == "MFA_VERIFY_ERROR"

    def test_missing_secret_is_not_a_verify_error(self) -> None:
        """缺失（IntegrityException→None）走普通失败路径，不是基础设施错误。"""
        state = InMemoryMfaStateStore()
        state.put_user_info(
            "u-1", 7, MfaUserInfo(status="ENABLED", secret_reference="p:absent")
        )
        retriever = SecretStoreSecretRetriever(FakeOperations())
        service = DefaultMfaValidationService(state, retriever, clock=lambda: 1_700_000_000)
        result = service.verify_mfa_code("u-1", 7, "123456")
        assert result.success is False
        assert result.error_code != "MFA_VERIFY_ERROR"


class TestSatisfiesProtocol:
    def test_exposes_the_retriever_surface(self) -> None:
        """mfa-validation 的 Protocol 未标记 runtime_checkable，无法 isinstance；
        结构兼容性由本文件的 MFA 服务闭环测试证明。"""
        retriever = SecretStoreSecretRetriever(FakeOperations())
        assert callable(retriever.retrieve)
        assert retriever.retrieve("p:x") is None  # 缺失 → None 契约