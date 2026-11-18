"""MFA validation orchestration and result contract.

Ported from `MfaValidationService` / `MfaValidationServiceImpl` /
`MfaValidationResult` (Java). The Java impl reads `GlobalCache`, retrieves secrets
through a KMS key-management provider and publishes Spring audit events. None of
those are dependencies here: user state, secret retrieval, trusted devices and
audit are injected SPIs, with per-process reference implementations so the service
is usable out of the box.

Error codes and their evaluation order match the Java implementation.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .engine import TotpProperties, TotpValidationEngine
from .replay import InMemoryReplayGuard, ReplayGuard

_log = logging.getLogger(__name__)

ENABLED = "ENABLED"


@dataclass
class MfaUserInfo:
    """Per-user MFA state, as loaded from the caller's store."""

    status: str | None = None
    secret_reference: str | None = None
    algorithm: str | None = None
    period: int | None = None
    digits: int | None = None
    locked_until_millis: int | None = None


@dataclass
class MfaValidationResult:
    success: bool = False
    mfa_required: bool = False
    mfa_bound: bool = False
    trusted_device: bool = False
    trusted_device_expired: bool = False
    account_locked: bool = False
    locked_until: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    failure_count: int | None = None
    max_attempts: int | None = None
    trusted_device_supported: bool = False
    trusted_device_count: int | None = None
    max_trusted_devices: int | None = None
    default_trust_days: int | None = None

    @classmethod
    def success_without_mfa(cls) -> MfaValidationResult:
        return cls(success=True, mfa_required=False)

    @classmethod
    def success_with_trusted_device(cls) -> MfaValidationResult:
        return cls(success=True, mfa_required=False, trusted_device=True)

    @classmethod
    def success_with_mfa(cls) -> MfaValidationResult:
        return cls(success=True, mfa_required=True, mfa_bound=True)

    @classmethod
    def failure(cls, error_code: str, error_message: str) -> MfaValidationResult:
        return cls(success=False, error_code=error_code, error_message=error_message)

    @classmethod
    def mfa_required_result(
        cls,
        trusted_device_supported: bool,
        trusted_device_count: int | None,
        max_trusted_devices: int | None,
        default_trust_days: int | None,
    ) -> MfaValidationResult:
        return cls(
            success=False,
            mfa_required=True,
            mfa_bound=True,
            trusted_device_supported=trusted_device_supported,
            trusted_device_count=trusted_device_count,
            max_trusted_devices=max_trusted_devices,
            default_trust_days=default_trust_days,
        )


class MfaStateStore(Protocol):
    """User MFA state, failure counting and the lock marker.

    Java keeps these in GlobalCache under separate keys; notably the lock is a
    standalone `mfa:lock:{tenant}:{user}` key with a TTL, not a mutation of the
    user record — the management module reconciles it into the database.
    """

    def get_user_info(self, user_id: str, tenant_id: str | int | None) -> MfaUserInfo | None: ...

    def increment_failure(self, user_id: str, tenant_id: str | int | None, ttl_seconds: float) -> int: ...

    def reset_failure(self, user_id: str, tenant_id: str | int | None) -> None: ...

    def mark_locked(self, user_id: str, tenant_id: str | int | None, duration_seconds: float) -> None: ...

    def lock_until_millis(self, user_id: str, tenant_id: str | int | None) -> int | None: ...


class SecretRetriever(Protocol):
    """Resolves a secret reference to the plaintext Base32 TOTP secret.

    Wire this to one of the platform's secret providers; this package deliberately
    does not depend on any KMS or storage implementation.
    """

    def retrieve(self, secret_reference: str) -> str | None: ...


class TrustedDeviceStore(Protocol):
    def device_expiry_millis(self, user_id: str, tenant_id: str | int | None, device_id: str) -> int | None:
        """None when the device is unknown; otherwise its trust expiry."""
        ...

    def device_count(self, user_id: str, tenant_id: str | int | None) -> int: ...


@dataclass
class TrustedDeviceProperties:
    enabled: bool = False
    max_devices: int = 10
    default_trust_days: int = 30


@dataclass
class MfaSecurityProperties:
    max_attempts: int = 5
    lock_duration_seconds: float = 900.0
    failure_count_ttl_seconds: float = 3600.0
    trusted_device: TrustedDeviceProperties = field(default_factory=TrustedDeviceProperties)


@dataclass
class MfaValidationProperties:
    totp: TotpProperties = field(default_factory=TotpProperties)
    window_size: int = 1
    security: MfaSecurityProperties = field(default_factory=MfaSecurityProperties)


class InMemoryMfaStateStore:
    """Thread-safe per-process reference store. Not durable, not shared."""

    def __init__(self, *, clock=time.time) -> None:
        self._clock = clock
        self._users: dict[tuple[str, str], MfaUserInfo] = {}
        self._failures: dict[tuple[str, str], tuple[int, float]] = {}
        self._locks: dict[tuple[str, str], float] = {}
        self._guard = threading.Lock()

    @staticmethod
    def _key(user_id: str, tenant_id: str | int | None) -> tuple[str, str]:
        return (str(tenant_id) if tenant_id is not None else "-", user_id)

    def put_user_info(self, user_id: str, tenant_id: str | int | None, info: MfaUserInfo) -> None:
        with self._guard:
            self._users[self._key(user_id, tenant_id)] = info

    def get_user_info(self, user_id: str, tenant_id: str | int | None) -> MfaUserInfo | None:
        with self._guard:
            return self._users.get(self._key(user_id, tenant_id))

    def increment_failure(self, user_id: str, tenant_id: str | int | None, ttl_seconds: float) -> int:
        key = self._key(user_id, tenant_id)
        now = self._clock()
        with self._guard:
            count, expires_at = self._failures.get(key, (0, 0.0))
            if expires_at <= now:
                count = 0
            count += 1
            self._failures[key] = (count, now + ttl_seconds)
            return count

    def reset_failure(self, user_id: str, tenant_id: str | int | None) -> None:
        with self._guard:
            self._failures.pop(self._key(user_id, tenant_id), None)

    def mark_locked(self, user_id: str, tenant_id: str | int | None, duration_seconds: float) -> None:
        with self._guard:
            self._locks[self._key(user_id, tenant_id)] = self._clock() + duration_seconds

    def lock_until_millis(self, user_id: str, tenant_id: str | int | None) -> int | None:
        with self._guard:
            expires_at = self._locks.get(self._key(user_id, tenant_id))
        if expires_at is None or expires_at <= self._clock():
            return None
        return int(expires_at * 1000)


class InMemoryTrustedDeviceStore:
    def __init__(self, *, clock=time.time) -> None:
        self._clock = clock
        self._devices: dict[tuple[str, str, str], float] = {}
        self._guard = threading.Lock()

    def trust(self, user_id: str, tenant_id: str | int | None, device_id: str, expiry_millis: int) -> None:
        with self._guard:
            self._devices[(str(tenant_id) if tenant_id is not None else "-", user_id, device_id)] = expiry_millis / 1000

    def device_expiry_millis(self, user_id: str, tenant_id: str | int | None, device_id: str) -> int | None:
        key = (str(tenant_id) if tenant_id is not None else "-", user_id, device_id)
        with self._guard:
            expiry = self._devices.get(key)
        return None if expiry is None else int(expiry * 1000)

    def device_count(self, user_id: str, tenant_id: str | int | None) -> int:
        prefix = (str(tenant_id) if tenant_id is not None else "-", user_id)
        now = self._clock()
        with self._guard:
            return sum(1 for key, expiry in self._devices.items() if key[:2] == prefix and expiry > now)


class DefaultMfaValidationService:
    """Orchestrates status checks, TOTP verification, replay defence and lockout."""

    def __init__(
        self,
        state_store: MfaStateStore,
        secret_retriever: SecretRetriever,
        *,
        properties: MfaValidationProperties | None = None,
        engine: TotpValidationEngine | None = None,
        replay_guard: ReplayGuard | None = None,
        trusted_devices: TrustedDeviceStore | None = None,
        audit: Callable[[dict[str, Any]], None] | None = None,
        clock=time.time,
    ) -> None:
        self._state = state_store
        self._secrets = secret_retriever
        self._properties = properties if properties is not None else MfaValidationProperties()
        self._engine = engine if engine is not None else TotpValidationEngine(self._properties.totp)
        self._replay = replay_guard if replay_guard is not None else InMemoryReplayGuard()
        self._devices = trusted_devices
        self._audit = audit
        self._clock = clock

    def _emit(self, user_id: str, tenant_id: str | int | None, outcome: str,
              error_code: str | None = None, error_message: str | None = None) -> None:
        if self._audit is None:
            return
        try:
            self._audit({
                "user_id": user_id, "tenant_id": tenant_id, "operation": "VERIFY",
                "method": "TOTP", "outcome": outcome,
                "error_code": error_code, "error_message": error_message,
            })
        except Exception:  # noqa: BLE001 — auditing must not break validation
            _log.exception("mfa audit sink failed")

    def check_mfa_status(
        self, user_id: str, tenant_id: str | int | None = None, device_id: str | None = None
    ) -> MfaValidationResult:
        if not user_id or not user_id.strip():
            return MfaValidationResult.failure("INVALID_USER_ID", "用户ID不能为空")
        info = self._state.get_user_info(user_id, tenant_id)
        if info is None:
            return MfaValidationResult.success_without_mfa()
        locked_until = self._locked_until(info, user_id, tenant_id)
        if locked_until is not None:
            return MfaValidationResult(
                success=False, mfa_required=True, mfa_bound=True, account_locked=True,
                locked_until=locked_until, error_code="ACCOUNT_LOCKED",
                error_message="账户已锁定，请稍后再试",
            )
        if info.status != ENABLED:
            return MfaValidationResult.success_without_mfa()
        trusted = self._properties.security.trusted_device
        count = self._devices.device_count(user_id, tenant_id) if self._devices is not None else None
        return MfaValidationResult.mfa_required_result(
            trusted.enabled, count, trusted.max_devices, trusted.default_trust_days
        )

    def verify_mfa_code(
        self, user_id: str, tenant_id: str | int | None, mfa_code: str
    ) -> MfaValidationResult:
        if not user_id or not user_id.strip() or not mfa_code or not mfa_code.strip():
            return MfaValidationResult.failure("INVALID_PARAMS", "用户ID和验证码不能为空")
        info = self._state.get_user_info(user_id, tenant_id)
        if info is None:
            self._emit(user_id, tenant_id, "FAILED", "MFA_NOT_BOUND", "用户未绑定 MFA 设备")
            return MfaValidationResult.failure("MFA_NOT_BOUND", "用户未绑定 MFA 设备")
        if info.status != ENABLED:
            self._emit(user_id, tenant_id, "FAILED", "MFA_NOT_ENABLED", "MFA 未启用")
            return MfaValidationResult.failure("MFA_NOT_ENABLED", "MFA 未启用")
        locked_until = self._locked_until(info, user_id, tenant_id)
        if locked_until is not None:
            self._emit(user_id, tenant_id, "BLOCKED", "ACCOUNT_LOCKED", "账户已锁定，请稍后再试")
            return MfaValidationResult(
                success=False, account_locked=True, locked_until=locked_until,
                error_code="ACCOUNT_LOCKED", error_message="账户已锁定，请稍后再试",
            )

        period = info.period if info.period is not None else self._properties.totp.time_window
        time_step = int(self._clock()) // period
        if self._replay.is_code_used(user_id, tenant_id, time_step):
            _log.warning("MFA replay detected; userId=%s", user_id)
            self._emit(user_id, tenant_id, "FAILED", "MFA_CODE_USED", "验证码已被使用（重放攻击）")
            return MfaValidationResult.failure("MFA_CODE_USED", "验证码已被使用")

        try:
            reference = info.secret_reference or self._default_reference(user_id, tenant_id)
            secret = self._secrets.retrieve(reference)
            valid = self._engine.verify_code(
                secret,
                mfa_code,
                window=self._properties.window_size,
                algorithm=info.algorithm,
                period=period,
                digits=info.digits if info.digits is not None else self._properties.totp.code_length,
                now=int(self._clock()),
            )
            if not valid:
                return self._on_invalid_code(user_id, tenant_id)
            self._replay.mark_code_as_used(user_id, tenant_id, time_step)
            self._state.reset_failure(user_id, tenant_id)
            self._emit(user_id, tenant_id, "SUCCESS")
            return MfaValidationResult.success_with_mfa()
        except Exception as error:  # noqa: BLE001 — Java returns a failure result
            _log.error("MFA verification error; userId=%s exceptionType=%s", user_id, type(error).__name__)
            self._emit(user_id, tenant_id, "FAILED", "MFA_VERIFY_ERROR", str(error))
            return MfaValidationResult.failure("MFA_VERIFY_ERROR", f"MFA验证异常: {error}")

    def check_trusted_device(
        self, user_id: str, tenant_id: str | int | None, device_id: str
    ) -> MfaValidationResult:
        if not user_id or not user_id.strip() or not device_id or not device_id.strip():
            return MfaValidationResult.failure("INVALID_PARAMS", "用户ID和设备ID不能为空")
        if self._devices is None:
            return MfaValidationResult(success=False, mfa_required=True, trusted_device=False)
        expiry = self._devices.device_expiry_millis(user_id, tenant_id, device_id)
        if expiry is None:
            return MfaValidationResult(success=False, mfa_required=True, trusted_device=False)
        if expiry <= int(self._clock() * 1000):
            return MfaValidationResult(
                success=False, mfa_required=True, trusted_device=True, trusted_device_expired=True
            )
        return MfaValidationResult.success_with_trusted_device()

    def _on_invalid_code(self, user_id: str, tenant_id: str | int | None) -> MfaValidationResult:
        security = self._properties.security
        count = self._state.increment_failure(user_id, tenant_id, security.failure_count_ttl_seconds)
        if count >= security.max_attempts:
            self._state.mark_locked(user_id, tenant_id, security.lock_duration_seconds)
            _log.warning("MFA account locked after max failures; userId=%s", user_id)
            self._emit(user_id, tenant_id, "BLOCKED", "ACCOUNT_LOCKED", "账户已锁定")
            return MfaValidationResult(
                success=False, error_code="MFA_CODE_INVALID",
                error_message="验证码错误，账户已锁定",
                failure_count=count, max_attempts=security.max_attempts, account_locked=True,
            )
        self._emit(user_id, tenant_id, "FAILED", "MFA_CODE_INVALID", "验证码错误")
        return MfaValidationResult(
            success=False, error_code="MFA_CODE_INVALID", error_message="验证码错误",
            failure_count=count, max_attempts=security.max_attempts,
        )

    def _locked_until(self, info: MfaUserInfo, user_id: str, tenant_id: str | int | None) -> int | None:
        now_millis = int(self._clock() * 1000)
        if info.locked_until_millis is not None and info.locked_until_millis > now_millis:
            return info.locked_until_millis
        return self._state.lock_until_millis(user_id, tenant_id)

    @staticmethod
    def _default_reference(user_id: str, tenant_id: str | int | None) -> str:
        prefix = f"{tenant_id}:" if tenant_id is not None else ""
        return f"mfa:{prefix}{user_id}"


__all__ = [
    "ENABLED",
    "DefaultMfaValidationService",
    "InMemoryMfaStateStore",
    "InMemoryTrustedDeviceStore",
    "MfaSecurityProperties",
    "MfaStateStore",
    "MfaUserInfo",
    "MfaValidationProperties",
    "MfaValidationResult",
    "SecretRetriever",
    "TrustedDeviceProperties",
    "TrustedDeviceStore",
]
