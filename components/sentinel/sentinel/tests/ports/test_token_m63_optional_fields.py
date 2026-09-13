"""M6.3.2 1.0 兼容契约测试。

中文
----
验证 ``ports/token.py`` M6.3.2 兼容扩展**不**破坏 1.0 行为:

- ``Token`` 新增 2 个 optional field (``lease_id`` / ``owner_epoch``),
  默认 ``None``, 旧构造方式仍 work
- ``TokenResponse`` 新增 1 个 optional field (``retry_after_ns``), 默认 0
- ``ClusterFailurePolicy`` 新增 3 选 1 enum
- ``LocalTokenService`` 行为**完全不变**: 永远 ``LOCAL_GRANTED``,
  ``lease_id`` / ``owner_epoch`` 永远 ``None``, ``retry_after_ns`` 永远 0
- ``TokenResponse`` 不变量 (``DENIED`` vs 3 grants) 保持

English
--------
M6.3.2 backward-compat contract tests: verify the optional-field
extension on ``ports/token.py`` does **not** break 1.0 main wheel
behaviour.
"""

from __future__ import annotations

import time

import pytest

from atlas_richie.sentinel.ports.token import (
    ClusterFailurePolicy,
    LocalTokenService,
    Token,
    TokenDecision,
    TokenDenyReason,
    TokenResponse,
    TokenService,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 1. Token 旧构造方式仍 work (1.0 兼容)
# ---------------------------------------------------------------------------


class TestTokenBackwardCompat:
    """``Token`` 旧 4-field 构造方式 + 新 6-field 构造方式都 OK."""

    def test_old_construction_4_fields(self) -> None:
        """1.0 旧构造方式 (4 字段) 仍 work, 新字段默认 None。"""
        token = Token(
            resource="/api/v1/users",
            permits=1.0,
            issued_at_ns=time.time_ns(),
            ttl_ns=0,
        )
        assert token.resource == "/api/v1/users"
        assert token.permits == 1.0
        assert token.ttl_ns == 0
        # M6.3.2 新字段, 默认 None
        assert token.lease_id is None
        assert token.owner_epoch is None

    def test_new_construction_6_fields(self) -> None:
        """M6.3.2 新构造方式 (6 字段) 显式填 lease_id + owner_epoch。"""
        token = Token(
            resource="/api/v1/users",
            permits=1.0,
            issued_at_ns=time.time_ns(),
            ttl_ns=5_000_000_000,
            lease_id="550e8400-e29b-41d4-a716-446655440000",
            owner_epoch=3,
        )
        assert token.lease_id == "550e8400-e29b-41d4-a716-446655440000"
        assert token.owner_epoch == 3
        assert token.ttl_ns == 5_000_000_000

    def test_token_is_frozen_slots(self) -> None:
        """``Token`` 仍 frozen slots, 不能 mutation。"""
        token = Token(
            resource="/r", permits=1.0, issued_at_ns=1, ttl_ns=0,
            lease_id="abc", owner_epoch=1,
        )
        with pytest.raises((AttributeError, Exception)):
            token.lease_id = "new"  # type: ignore[misc]
        with pytest.raises((AttributeError, Exception)):
            token.owner_epoch = 99  # type: ignore[misc]

    def test_is_expired_unchanged(self) -> None:
        """``is_expired`` 行为不变。"""
        now = time.time_ns()
        # ttl=0 → 永远 False
        assert Token("/r", 1.0, now, 0).is_expired(now) is False
        # ttl=1s, 2s 后 → True
        token = Token("/r", 1.0, now - 2_000_000_000, 1_000_000_000)
        assert token.is_expired(now) is True
        # ttl=1s, 0.5s 后 → False
        token = Token("/r", 1.0, now - 500_000_000, 1_000_000_000)
        assert token.is_expired(now) is False


# ---------------------------------------------------------------------------
# 2. TokenResponse 旧构造 + 新 optional 字段
# ---------------------------------------------------------------------------


class TestTokenResponseBackwardCompat:
    """``TokenResponse`` 旧 4-field 构造 + 新 5-field 都 OK, 不变量保持。"""

    def test_old_construction_4_fields(self) -> None:
        """1.0 旧构造方式仍 work, retry_after_ns 默认 0。"""
        now = time.time_ns()
        token = Token("/r", 1.0, now, 0)
        response = TokenResponse(
            decision=TokenDecision.REMOTE_GRANTED,
            token=token,
        )
        assert response.decision is TokenDecision.REMOTE_GRANTED
        assert response.token is token
        assert response.deny_reason is None
        assert response.wait_ns == 0
        # M6.3.2 新字段, 默认 0
        assert response.retry_after_ns == 0

    def test_new_construction_5_fields(self) -> None:
        """M6.3.2 新 retry_after_ns 显式填。"""
        now = time.time_ns()
        token = Token("/r", 1.0, now, 0, lease_id="abc", owner_epoch=1)
        response = TokenResponse(
            decision=TokenDecision.REMOTE_GRANTED,
            token=token,
            retry_after_ns=2_000_000_000,
        )
        assert response.retry_after_ns == 2_000_000_000

    def test_denied_invariant_with_optional_field(self) -> None:
        """DENIED 仍有 deny_reason, 加上 retry_after_ns 不破坏不变量。"""
        response = TokenResponse(
            decision=TokenDecision.DENIED,
            deny_reason=TokenDenyReason.QUEUE_FULL,
            retry_after_ns=1_000_000_000,  # M6.3.2 字段
        )
        assert response.decision is TokenDecision.DENIED
        assert response.token is None
        assert response.deny_reason is TokenDenyReason.QUEUE_FULL
        assert response.retry_after_ns == 1_000_000_000

    def test_grant_invariant_with_optional_field(self) -> None:
        """3 grants (LOCAL/REMOTE/FAIL_OPEN) 仍有 token, retry_after_ns 可填。"""
        now = time.time_ns()
        for decision in (
            TokenDecision.LOCAL_GRANTED,
            TokenDecision.REMOTE_GRANTED,
            TokenDecision.FAIL_OPEN,
        ):
            token = Token("/r", 1.0, now, 0, lease_id="abc", owner_epoch=1)
            response = TokenResponse(
                decision=decision,
                token=token,
                retry_after_ns=500_000_000,
            )
            assert response.token is token
            assert response.deny_reason is None


# ---------------------------------------------------------------------------
# 3. ClusterFailurePolicy enum (M6.3.6)
# ---------------------------------------------------------------------------


class TestClusterFailurePolicyEnum:
    """``ClusterFailurePolicy`` 3 选 1 enum, 不允许默认静默放行。"""

    def test_three_values(self) -> None:
        """M6.3.6 枚举恰好 3 个值, 无第四个。"""
        assert len(ClusterFailurePolicy) == 3
        assert ClusterFailurePolicy.FAIL_CLOSED.value == "fail_closed"
        assert ClusterFailurePolicy.FAIL_OPEN.value == "fail_open"
        assert ClusterFailurePolicy.LOCAL_FALLBACK.value == "local_fallback"

    def test_explicit_selection_required(self) -> None:
        """文档化: 没有 "default" / "auto" / "silent" 等禁用值。

        PLANNING §M6.3 验收不变量: 禁止默认静默放行。
        """
        forbidden = {"default", "auto", "silent", "best_effort", "passthrough"}
        for member in ClusterFailurePolicy:
            assert member.value not in forbidden, (
                f"ClusterFailurePolicy.{member.name} is forbidden "
                f"(PLANNING §M6.3: no default silent pass)"
            )

    def test_no_default_factory(self) -> None:
        """枚举**不**提供隐式 default factory (PLANNING 显式选择 1 项)。"""
        # StrEnum 没有 __call__, 只能显式选 1 个值
        with pytest.raises(TypeError):
            ClusterFailurePolicy()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 4. LocalTokenService 行为完全不变 (1.0 兼容验证)
# ---------------------------------------------------------------------------


class TestLocalTokenServiceUnchanged:
    """``LocalTokenService`` 1.0 主包默认实现, 行为**完全不变**。"""

    def test_acquire_returns_local_granted(self) -> None:
        """永远 LOCAL_GRANTED (不依赖 M6.3.2 新字段)。"""
        service = LocalTokenService()
        response = service.acquire("/api/v1/users", 1.0)
        assert response.decision is TokenDecision.LOCAL_GRANTED
        assert response.token is not None
        assert response.deny_reason is None
        assert response.wait_ns == 0
        assert response.retry_after_ns == 0  # M6.3.2 默认

    def test_local_token_lease_id_is_none(self) -> None:
        """1.0 主包 LocalTokenService 永远不填 lease_id / owner_epoch。"""
        service = LocalTokenService()
        response = service.acquire("/r", 1.0)
        assert response.token is not None
        # M6.3.2 新字段: 永远 None
        assert response.token.lease_id is None
        assert response.token.owner_epoch is None

    def test_release_is_noop(self) -> None:
        """``release()`` no-op, 不依赖 M6.3.2 字段。"""
        service = LocalTokenService()
        token = Token("/r", 1.0, time.time_ns(), 0, lease_id="abc", owner_epoch=1)
        # 不抛错, 不改 state
        assert service.release(token) is None

    def test_acquire_with_zero_permits(self) -> None:
        """边界: permits=0.0 仍 grant。"""
        service = LocalTokenService()
        response = service.acquire("/r", 0.0)
        assert response.decision is TokenDecision.LOCAL_GRANTED
        assert response.token is not None
        assert response.token.permits == 0.0

    def test_isinstance_token_service_protocol(self) -> None:
        """``LocalTokenService`` 仍是 ``TokenService`` Protocol 实现。"""
        service = LocalTokenService()
        assert isinstance(service, TokenService)


# ---------------------------------------------------------------------------
# 5. TokenService Protocol 签名不变 (1.0 兼容)
# ---------------------------------------------------------------------------


class TestTokenServiceProtocolUnchanged:
    """``TokenService`` Protocol 签名不变 (acquire + release)。"""

    def test_protocol_methods(self) -> None:
        """``TokenService`` Protocol 仅 acquire / release, 无 M6.3.2 新增方法。"""
        # Protocol 用 runtime_checkable; 检查 method 存在
        service = LocalTokenService()
        assert hasattr(service, "acquire")
        assert hasattr(service, "release")
        # 不应有 M6.3.2 公开方法 (Server 端, 不在 Protocol 上)
        assert not hasattr(service, "renew")
        assert not hasattr(service, "cancel")
