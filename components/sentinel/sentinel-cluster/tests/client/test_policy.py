"""Client ClusterFailurePolicy 决策单测 (M6.3.4 + M6.3.6) — 8 个测试.

中文
----
- ``test_fail_closed_returns_denied_with_remote_unavailable`` (3 选 1 / FAIL_CLOSED)
- ``test_fail_open_grants_stub_with_lease_id_none`` (3 选 1 / FAIL_OPEN)
- ``test_local_fallback_delegates_to_local_token_service`` (3 选 1 / LOCAL_FALLBACK)
- ``test_fail_closed_does_not_require_local_fallback``
- ``test_fail_open_stub_token_has_lease_id_none``
- ``test_local_fallback_without_instance_falls_back_to_fail_closed``
- ``test_unsupported_policy_raises_value_error``
- ``test_decision_kind_labels_match_policy``

English
--------
- 8 unit tests covering ClusterFailurePolicy 3-way decision semantics.
"""

from __future__ import annotations

import pytest

from atlas_richie.sentinel.ports.token import (
    ClusterFailurePolicy,
    LocalTokenService,
    Token,
    TokenDecision,
    TokenDenyReason,
)

from atlas_richie.sentinel_cluster.client.policy import (
    PolicyDecision,
    decide_failure,
)

pytestmark = pytest.mark.unit


class TestFailClosed:
    """FAIL_CLOSED: 强保证, 真 deny, 业务受影响."""

    def test_fail_closed_returns_denied_with_remote_unavailable(self) -> None:
        # FAIL_CLOSED + Server 不可达 → DENIED + REMOTE_UNAVAILABLE
        decision = decide_failure(
            resource="/r1",
            permits=1.0,
            policy=ClusterFailurePolicy.FAIL_CLOSED,
            reason="server_unreachable",
        )
        assert isinstance(decision, PolicyDecision)
        assert decision.response.decision is TokenDecision.DENIED
        assert decision.response.deny_reason is TokenDenyReason.REMOTE_UNAVAILABLE
        assert decision.response.token is None
        assert decision.fail_open is False
        assert decision.local_fallback is False
        assert decision.decision_kind == "FAIL_CLOSED"

    def test_fail_closed_does_not_require_local_fallback(self) -> None:
        # FAIL_CLOSED 不需要 local_fallback 参数
        decision = decide_failure(
            resource="/r1",
            permits=2.5,
            policy=ClusterFailurePolicy.FAIL_CLOSED,
            reason="timeout",
        )
        assert decision.response.decision is TokenDecision.DENIED


class TestFailOpen:
    """FAIL_OPEN: 不承诺不超发, 每次放行 stub token + 指标."""

    def test_fail_open_grants_stub_with_lease_id_none(self) -> None:
        # FAIL_OPEN → FAIL_OPEN 决策 + stub token (lease_id=None)
        decision = decide_failure(
            resource="/r1",
            permits=1.0,
            policy=ClusterFailurePolicy.FAIL_OPEN,
            reason="server_unreachable",
        )
        assert decision.response.decision is TokenDecision.FAIL_OPEN
        assert decision.response.token is not None
        assert decision.response.deny_reason is None
        assert decision.fail_open is True
        assert decision.local_fallback is False
        assert decision.decision_kind == "FAIL_OPEN"

    def test_fail_open_stub_token_has_lease_id_none(self) -> None:
        # stub token 必须 lease_id=None 标记 (跟真 lease 区分)
        decision = decide_failure(
            resource="/r1",
            permits=3.0,
            policy=ClusterFailurePolicy.FAIL_OPEN,
            reason="connection_refused",
        )
        token = decision.response.token
        assert token is not None
        assert token.lease_id is None
        assert token.owner_epoch is None
        assert token.resource == "/r1"
        assert token.permits == 3.0
        assert token.ttl_ns == 0  # 永久 (本地 stub)


class TestLocalFallback:
    """LOCAL_FALLBACK: 显式本地策略, fallback 到 LocalTokenService."""

    def test_local_fallback_delegates_to_local_token_service(self) -> None:
        # LOCAL_FALLBACK + 传 local_fallback → 调 LocalTokenService.acquire
        local = LocalTokenService()
        decision = decide_failure(
            resource="/r1",
            permits=1.0,
            policy=ClusterFailurePolicy.LOCAL_FALLBACK,
            reason="server_unreachable",
            local_fallback=local,
        )
        # LocalTokenService 永远 LOCAL_GRANTED
        assert decision.response.decision is TokenDecision.LOCAL_GRANTED
        assert decision.response.token is not None
        assert decision.response.deny_reason is None
        assert decision.fail_open is False
        assert decision.local_fallback is True
        assert decision.decision_kind == "LOCAL_FALLBACK"

    def test_local_fallback_without_instance_falls_back_to_fail_closed(self) -> None:
        # 1.0 接受限制: 没传 local_fallback → 降级 FAIL_CLOSED 行为
        # (避免 silently fallback, 强制用户显式提供 fallback 实例)
        decision = decide_failure(
            resource="/r1",
            permits=1.0,
            policy=ClusterFailurePolicy.LOCAL_FALLBACK,
            reason="server_unreachable",
            local_fallback=None,
        )
        assert decision.response.decision is TokenDecision.DENIED
        assert decision.response.deny_reason is TokenDenyReason.REMOTE_UNAVAILABLE
        assert decision.local_fallback is True  # 仍标 LOCAL_FALLBACK 标签
        assert decision.decision_kind == "LOCAL_FALLBACK_MISSING"


class TestPolicyValidation:
    """policy 校验 + 决策标签."""

    def test_unsupported_policy_raises_value_error(self) -> None:
        # 不在 3 选 1 enum → 抛 ValueError (default-deny)
        # 用绕过 enum 的方式构造 (直接 str 没法, 用 object 替代)
        with pytest.raises(ValueError, match="unsupported ClusterFailurePolicy"):
            decide_failure(
                resource="/r1",
                permits=1.0,
                policy="auto",  # type: ignore[arg-type]  # 故意错类型
                reason="test",
            )

    def test_decision_kind_labels_match_policy(self) -> None:
        # 3 个 policy 各对应不同 decision_kind (用于指标 / 日志)
        fail_closed = decide_failure(
            resource="/r1",
            permits=1.0,
            policy=ClusterFailurePolicy.FAIL_CLOSED,
            reason="test",
        )
        fail_open = decide_failure(
            resource="/r1",
            permits=1.0,
            policy=ClusterFailurePolicy.FAIL_OPEN,
            reason="test",
        )
        local = decide_failure(
            resource="/r1",
            permits=1.0,
            policy=ClusterFailurePolicy.LOCAL_FALLBACK,
            reason="test",
            local_fallback=LocalTokenService(),
        )
        assert fail_closed.decision_kind == "FAIL_CLOSED"
        assert fail_open.decision_kind == "FAIL_OPEN"
        assert local.decision_kind == "LOCAL_FALLBACK"
