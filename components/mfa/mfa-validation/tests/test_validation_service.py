"""MFA validation service orchestration tests.

Error codes and their evaluation order are ported from the Java
`MfaValidationServiceImpl`; these tests pin each branch.
"""

from __future__ import annotations

import pytest

from atlas_richie.mfa_validation import (
    ENABLED,
    DefaultMfaValidationService,
    InMemoryMfaStateStore,
    InMemoryReplayGuard,
    InMemoryTrustedDeviceStore,
    MfaSecurityProperties,
    MfaUserInfo,
    MfaValidationProperties,
    MfaValidationResult,
    TotpValidationEngine,
)

pytestmark = pytest.mark.unit

SECRET = "JBSWY3DPEHPK3PXP"
NOW = 1_700_000_000


class _Secrets:
    def __init__(self, secret: str | None = SECRET) -> None:
        self.secret = secret
        self.asked: list[str] = []

    def retrieve(self, reference: str) -> str | None:
        self.asked.append(reference)
        return self.secret


@pytest.fixture
def clock():
    return [float(NOW)]


@pytest.fixture
def store(clock):
    return InMemoryMfaStateStore(clock=lambda: clock[0])


@pytest.fixture
def secrets():
    return _Secrets()


@pytest.fixture
def properties():
    return MfaValidationProperties(
        window_size=1,
        security=MfaSecurityProperties(max_attempts=3, lock_duration_seconds=900),
    )


@pytest.fixture
def service(store, secrets, properties, clock):
    return DefaultMfaValidationService(
        store, secrets, properties=properties,
        replay_guard=InMemoryReplayGuard(), clock=lambda: clock[0],
    )


def _bind(store, **overrides) -> MfaUserInfo:
    fields = {"status": ENABLED, "secret_reference": "mfa:u1"}
    fields.update(overrides)
    info = MfaUserInfo(**fields)
    store.put_user_info("u1", None, info)
    return info


def _code(engine=None, now=NOW, period=30, digits=6) -> str:
    engine = engine or TotpValidationEngine()
    return engine.generate_code(SECRET, now // period, digits, "SHA1")


class TestCheckMfaStatus:
    def test_blank_user_id(self, service) -> None:
        result = service.check_mfa_status("  ")
        assert result.error_code == "INVALID_USER_ID"

    def test_unbound_user_needs_no_mfa(self, service) -> None:
        result = service.check_mfa_status("u1")
        assert result.success is True
        assert result.mfa_required is False

    def test_disabled_mfa_needs_no_mfa(self, service, store) -> None:
        _bind(store, status="DISABLED")
        assert service.check_mfa_status("u1").mfa_required is False

    def test_enabled_mfa_requires_verification(self, service, store) -> None:
        _bind(store)
        result = service.check_mfa_status("u1")
        assert result.mfa_required is True
        assert result.mfa_bound is True
        assert result.success is False

    def test_trusted_device_metadata_defaults(self, service, store) -> None:
        _bind(store)
        result = service.check_mfa_status("u1")
        assert result.max_trusted_devices == 10
        assert result.default_trust_days == 30
        assert result.trusted_device_supported is False

    def test_locked_account(self, service, store, clock) -> None:
        _bind(store, locked_until_millis=int((NOW + 60) * 1000))
        result = service.check_mfa_status("u1")
        assert result.account_locked is True
        assert result.error_code == "ACCOUNT_LOCKED"
        assert result.mfa_required is True

    def test_expired_lock_is_ignored(self, service, store) -> None:
        _bind(store, locked_until_millis=int((NOW - 60) * 1000))
        assert service.check_mfa_status("u1").account_locked is False


class TestVerifyMfaCode:
    def test_blank_params(self, service) -> None:
        assert service.verify_mfa_code("", None, "123456").error_code == "INVALID_PARAMS"
        assert service.verify_mfa_code("u1", None, "").error_code == "INVALID_PARAMS"

    def test_unbound_user(self, service) -> None:
        assert service.verify_mfa_code("u1", None, "123456").error_code == "MFA_NOT_BOUND"

    def test_not_enabled(self, service, store) -> None:
        _bind(store, status="DISABLED")
        assert service.verify_mfa_code("u1", None, "123456").error_code == "MFA_NOT_ENABLED"

    def test_locked_account_blocks_before_replay_check(self, service, store) -> None:
        _bind(store, locked_until_millis=int((NOW + 60) * 1000))
        result = service.verify_mfa_code("u1", None, "123456")
        assert result.error_code == "ACCOUNT_LOCKED"
        assert result.account_locked is True
        assert result.locked_until == int((NOW + 60) * 1000)

    def test_valid_code_succeeds(self, service, store, secrets) -> None:
        _bind(store)
        result = service.verify_mfa_code("u1", None, _code())
        assert result.success is True
        assert result.mfa_bound is True
        assert secrets.asked == ["mfa:u1"]

    def test_wrong_code_increments_failure_count(self, service, store) -> None:
        _bind(store)
        result = service.verify_mfa_code("u1", None, "000000")
        assert result.success is False
        assert result.error_code == "MFA_CODE_INVALID"
        assert result.failure_count == 1
        assert result.max_attempts == 3
        assert result.account_locked is False

    def test_lockout_at_max_attempts(self, service, store) -> None:
        _bind(store)
        for expected in (1, 2):
            assert service.verify_mfa_code("u1", None, "000000").failure_count == expected
        third = service.verify_mfa_code("u1", None, "000000")
        assert third.account_locked is True
        assert third.error_message == "验证码错误，账户已锁定"
        # The lock marker takes effect immediately on the next attempt.
        assert service.verify_mfa_code("u1", None, "000000").error_code == "ACCOUNT_LOCKED"

    def test_success_resets_failure_count(self, service, store, clock) -> None:
        _bind(store)
        service.verify_mfa_code("u1", None, "000000")
        assert service.verify_mfa_code("u1", None, _code()).success is True
        # Move to the next time step: the successful code is now replay-protected.
        clock[0] = float(NOW + 30)
        assert service.verify_mfa_code("u1", None, "000000").failure_count == 1

    def test_replay_is_rejected(self, service, store) -> None:
        _bind(store)
        code = _code()
        assert service.verify_mfa_code("u1", None, code).success is True
        replay = service.verify_mfa_code("u1", None, code)
        assert replay.error_code == "MFA_CODE_USED"

    def test_user_info_period_and_digits_are_used(self, store, secrets, clock) -> None:
        info = MfaUserInfo(status=ENABLED, secret_reference="mfa:u1", period=60, digits=8, algorithm="SHA256")
        store.put_user_info("u1", None, info)
        service = DefaultMfaValidationService(
            store, secrets, replay_guard=InMemoryReplayGuard(), clock=lambda: clock[0]
        )
        code = TotpValidationEngine().generate_code(SECRET, NOW // 60, 8, "SHA256")
        assert service.verify_mfa_code("u1", None, code).success is True
        # The same code must not validate under the default 30s/6-digit parameters.
        other = MfaUserInfo(status=ENABLED, secret_reference="mfa:u2")
        store.put_user_info("u2", None, other)
        assert service.verify_mfa_code("u2", None, code).success is False

    def test_secret_retrieval_failure_is_a_result_not_a_raise(self, store, properties, clock) -> None:
        _bind(store)

        class _Broken:
            def retrieve(self, reference):
                raise ConnectionError("kms down")

        service = DefaultMfaValidationService(
            store, _Broken(), properties=properties, clock=lambda: clock[0]
        )
        result = service.verify_mfa_code("u1", None, "123456")
        assert result.error_code == "MFA_VERIFY_ERROR"

    def test_missing_secret_fails_closed(self, store, properties, clock) -> None:
        _bind(store)
        service = DefaultMfaValidationService(
            store, _Secrets(None), properties=properties, clock=lambda: clock[0]
        )
        assert service.verify_mfa_code("u1", None, _code()).error_code == "MFA_CODE_INVALID"

    def test_default_secret_reference_when_absent(self, store, secrets, properties, clock) -> None:
        store.put_user_info("u1", 7, MfaUserInfo(status=ENABLED))
        service = DefaultMfaValidationService(
            store, secrets, properties=properties, clock=lambda: clock[0]
        )
        service.verify_mfa_code("u1", 7, "000000")
        assert secrets.asked == ["mfa:7:u1"]

    def test_audit_sink_receives_outcomes(self, store, secrets, properties, clock) -> None:
        events: list[dict] = []
        _bind(store)
        service = DefaultMfaValidationService(
            store, secrets, properties=properties,
            replay_guard=InMemoryReplayGuard(), audit=events.append, clock=lambda: clock[0],
        )
        service.verify_mfa_code("u1", None, "000000")
        service.verify_mfa_code("u1", None, _code())
        assert [e["outcome"] for e in events] == ["FAILED", "SUCCESS"]
        assert events[0]["error_code"] == "MFA_CODE_INVALID"

    def test_failing_audit_sink_does_not_break_validation(self, store, secrets, properties, clock) -> None:
        def bad_audit(event):
            raise RuntimeError("audit down")

        _bind(store)
        service = DefaultMfaValidationService(
            store, secrets, properties=properties,
            replay_guard=InMemoryReplayGuard(), audit=bad_audit, clock=lambda: clock[0],
        )
        assert service.verify_mfa_code("u1", None, _code()).success is True


class TestTrustedDevice:
    def test_blank_params(self, service) -> None:
        assert service.check_trusted_device("", None, "d1").error_code == "INVALID_PARAMS"
        assert service.check_trusted_device("u1", None, "").error_code == "INVALID_PARAMS"

    def test_no_store_means_mfa_required(self, service) -> None:
        result = service.check_trusted_device("u1", None, "d1")
        assert result.trusted_device is False
        assert result.mfa_required is True

    def test_unknown_device(self, store, secrets, properties, clock) -> None:
        service = DefaultMfaValidationService(
            store, secrets, properties=properties,
            trusted_devices=InMemoryTrustedDeviceStore(clock=lambda: clock[0]),
            clock=lambda: clock[0],
        )
        result = service.check_trusted_device("u1", None, "d1")
        assert result.trusted_device is False
        assert result.mfa_required is True

    def test_trusted_unexpired_device_skips_mfa(self, store, secrets, properties, clock) -> None:
        devices = InMemoryTrustedDeviceStore(clock=lambda: clock[0])
        devices.trust("u1", None, "d1", int((NOW + 3600) * 1000))
        service = DefaultMfaValidationService(
            store, secrets, properties=properties, trusted_devices=devices, clock=lambda: clock[0]
        )
        result = service.check_trusted_device("u1", None, "d1")
        assert result.success is True
        assert result.trusted_device is True
        assert result.trusted_device_expired is False
        assert result.mfa_required is False

    def test_expired_device_requires_mfa(self, store, secrets, properties, clock) -> None:
        devices = InMemoryTrustedDeviceStore(clock=lambda: clock[0])
        devices.trust("u1", None, "d1", int((NOW - 1) * 1000))
        service = DefaultMfaValidationService(
            store, secrets, properties=properties, trusted_devices=devices, clock=lambda: clock[0]
        )
        result = service.check_trusted_device("u1", None, "d1")
        assert result.trusted_device is True
        assert result.trusted_device_expired is True
        assert result.mfa_required is True

    def test_device_count_feeds_status_metadata(self, store, secrets, properties, clock) -> None:
        devices = InMemoryTrustedDeviceStore(clock=lambda: clock[0])
        devices.trust("u1", None, "d1", int((NOW + 3600) * 1000))
        devices.trust("u1", None, "d2", int((NOW - 1) * 1000))
        _bind(store)
        service = DefaultMfaValidationService(
            store, secrets, properties=properties, trusted_devices=devices, clock=lambda: clock[0]
        )
        assert service.check_mfa_status("u1").trusted_device_count == 1, "expired devices are not counted"


class TestResultFactories:
    def test_factory_shapes(self) -> None:
        assert MfaValidationResult.success_without_mfa().mfa_required is False
        assert MfaValidationResult.success_with_trusted_device().trusted_device is True
        with_mfa = MfaValidationResult.success_with_mfa()
        assert with_mfa.success is True and with_mfa.mfa_bound is True
        failure = MfaValidationResult.failure("X", "y")
        assert failure.success is False and failure.error_code == "X"
