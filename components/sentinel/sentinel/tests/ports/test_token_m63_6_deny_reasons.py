"""M6.3.6 1.0 兼容契约测试: TokenDenyReason 加 2 个新值.

中文
----
验证 ``ports/token.py`` M6.3.6 兼容扩展**不**破坏 1.0 行为:

- ``TokenDenyReason`` 加 2 个新值 (``RESOURCE_NOT_CONFIGURED`` /
  ``SERVER_OVERLOADED``), 默认 ``None`` (不可能默认, enum 值)
- 旧 5 个值不变: ``QUEUE_FULL`` / ``REMOTE_UNAVAILABLE`` / ``RATE_LIMITED`` /
  ``SHUTTING_DOWN`` / ``UNKNOWN``
- ``TokenResponse`` 不变量 (``DENIED`` vs 3 grants) 保持
- ``LocalTokenService`` 行为**完全不变**: 永远 ``LOCAL_GRANTED``,
  ``deny_reason=None``

English
--------
M6.3.6 backward-compat contract tests: verify the deny-reason extension
on ``ports/token.py`` does **not** break 1.0 main wheel behaviour.
"""

from __future__ import annotations

import time

import pytest

from atlas_richie.sentinel.ports.token import (
    LocalTokenService,
    Token,
    TokenDecision,
    TokenDenyReason,
    TokenResponse,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 1. 旧 5 个值不变 + 新 2 个值存在 (1.0 兼容)
# ---------------------------------------------------------------------------


class TestTokenDenyReasonBackwardCompat:
    """``TokenDenyReason`` 旧 5 值不变 + 新 2 值存在."""

    def test_old_5_values_still_exist(self) -> None:
        # 旧 5 值必须保持 (1.0 兼容)
        for value in (
            "queue_full",
            "remote_unavailable",
            "rate_limited",
            "shutting_down",
            "unknown",
        ):
            assert TokenDenyReason(value) is not None, (
                f"old TokenDenyReason {value!r} must still exist (1.0 compat)"
            )

    def test_new_2_values_exist(self) -> None:
        # 新 2 值必须存在
        for value in ("resource_not_configured", "server_overloaded"):
            assert TokenDenyReason(value) is not None, (
                f"new TokenDenyReason {value!r} must exist (M6.3.6)"
            )

    def test_total_count_is_7(self) -> None:
        # 5 旧 + 2 新 = 7
        assert len(TokenDenyReason) == 7, (
            f"TokenDenyReason must have exactly 7 values, got {len(TokenDenyReason)}"
        )

    def test_new_value_string_values(self) -> None:
        # enum value 字符串稳定 (1.0 wire-stable)
        assert TokenDenyReason.RESOURCE_NOT_CONFIGURED.value == "resource_not_configured"
        assert TokenDenyReason.SERVER_OVERLOADED.value == "server_overloaded"

    def test_authority_denied_not_in_token_deny_reason(self) -> None:
        # 1.0 不变: AUTHORITY_DENIED 仍不属于 TokenService
        with pytest.raises(ValueError):
            TokenDenyReason("authority_denied")


# ---------------------------------------------------------------------------
# 2. TokenResponse 不变量 (DENIED + 2 新 deny_reason 仍合法)
# ---------------------------------------------------------------------------


class TestTokenResponseInvariantWithNewReasons:
    """``TokenResponse`` 不变量保持, 新 deny_reason 走 DENIED 路径."""

    def test_denied_with_resource_not_configured(self) -> None:
        # 启动 fail-fast: resource 未配, Client 标 DENIED + RESOURCE_NOT_CONFIGURED
        resp = TokenResponse(
            decision=TokenDecision.DENIED,
            token=None,
            deny_reason=TokenDenyReason.RESOURCE_NOT_CONFIGURED,
            wait_ns=0,
        )
        assert resp.decision is TokenDecision.DENIED
        assert resp.deny_reason is TokenDenyReason.RESOURCE_NOT_CONFIGURED
        assert resp.token is None
        assert resp.wait_ns == 0

    def test_denied_with_server_overloaded(self) -> None:
        # Server 资源满: DENIED + SERVER_OVERLOADED
        resp = TokenResponse(
            decision=TokenDecision.DENIED,
            token=None,
            deny_reason=TokenDenyReason.SERVER_OVERLOADED,
            wait_ns=0,
            retry_after_ns=100_000_000,  # 100ms, 跟 M6.3.4 协议 retry_after_ns 配套
        )
        assert resp.decision is TokenDecision.DENIED
        assert resp.deny_reason is TokenDenyReason.SERVER_OVERLOADED
        assert resp.retry_after_ns == 100_000_000

    def test_denied_requires_deny_reason_still_holds(self) -> None:
        # 不变量: DENIED 必有 deny_reason (1.0 行为不变)
        with pytest.raises(ValueError, match="DENIED requires deny_reason"):
            TokenResponse(
                decision=TokenDecision.DENIED,
                token=None,
                deny_reason=None,  # 缺
            )

    def test_grant_requires_no_deny_reason_still_holds(self) -> None:
        # 不变量: 3 grants 必有 deny_reason=None (1.0 行为不变)
        token = Token(
            resource="/api/v1/users",
            permits=1.0,
            issued_at_ns=time.time_ns(),
            ttl_ns=0,
        )
        for decision in (
            TokenDecision.LOCAL_GRANTED,
            TokenDecision.REMOTE_GRANTED,
            TokenDecision.FAIL_OPEN,
        ):
            with pytest.raises(ValueError, match="requires deny_reason is None"):
                TokenResponse(
                    decision=decision,
                    token=token,
                    deny_reason=TokenDenyReason.SERVER_OVERLOADED,  # 错
                )


# ---------------------------------------------------------------------------
# 3. LocalTokenService 行为完全不变 (1.0 兼容)
# ---------------------------------------------------------------------------


class TestLocalTokenServiceUnchanged:
    """``LocalTokenService`` 永远 ``LOCAL_GRANTED`` + 新 deny_reason 永不触发."""

    def test_local_always_local_granted(self) -> None:
        svc = LocalTokenService()
        resp = svc.acquire(resource="/api/v1/users", permits=1.0)
        assert resp.decision is TokenDecision.LOCAL_GRANTED
        assert resp.deny_reason is None
        assert resp.wait_ns == 0
        assert resp.retry_after_ns == 0

    def test_local_never_uses_new_deny_reasons(self) -> None:
        # 单进程永不触发 RESOURCE_NOT_CONFIGURED / SERVER_OVERLOADED
        svc = LocalTokenService()
        for _ in range(5):
            resp = svc.acquire(resource="/api/v1/users", permits=1.0)
            assert resp.deny_reason not in (
                TokenDenyReason.RESOURCE_NOT_CONFIGURED,
                TokenDenyReason.SERVER_OVERLOADED,
            )

    def test_local_release_is_noop(self) -> None:
        svc = LocalTokenService()
        token = svc.acquire(resource="x", permits=1.0).token
        assert svc.release(token) is None  # 1.0 行为不变
