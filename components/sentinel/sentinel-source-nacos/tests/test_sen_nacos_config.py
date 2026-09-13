"""M6.1.2 NacosRuleSourceConfig + 值对象契约测试。

中文
----
PLANNING M6.1.2 硬约束测试覆盖:

- 不可变 (frozen dataclass): 字段不可修改
- 必填字段: source_id / server_addresses / namespace / group /
  data_id_prefix 非空
- 超时与退避: > 0; ``reconnect_max >= reconnect_initial``
- 5 个 data_id 约定 (data_id_for): 5 类 rule type + 未知 rule type 抛错
- 脱敏 (M6.1.5 前置要求): ``__repr__`` 不暴露 password / PEM 内容
- default-deny 收窄: 5 类 (所有权 / 权限 / 故障策略 / 资源上限 /
  跨进程语义) optional 参数显式

不测试 (留给 M6.1.3-1.5):

- NacosRuleSource 实现 (M6.1.3-1.5)
- 真实 Nacos SDK 集成 (M6.1.6 + M6.1 真实验收)
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from atlas_richie.sentinel_source_nacos.config import (
    NacosAuth,
    NacosRuleSourceConfig,
    NacosSourceError,
    NacosSourceState,
    NacosTLS,
)


# ---------------------------------------------------------------------------
# NacosAuth tests

class TestNacosAuth:
    """NacosAuth 值对象: 不可变 + 必填 + 脱敏。"""

    def test_create_valid(self) -> None:
        auth = NacosAuth(username="ops", password="secret")
        assert auth.username == "ops"
        assert auth.password == "secret"

    def test_empty_username_rejected(self) -> None:
        with pytest.raises(ValueError, match="username must be a non-empty str"):
            NacosAuth(username="", password="secret")

    def test_empty_password_rejected(self) -> None:
        with pytest.raises(ValueError, match="password must be a non-empty str"):
            NacosAuth(username="ops", password="")

    def test_frozen(self) -> None:
        auth = NacosAuth(username="ops", password="secret")
        with pytest.raises(FrozenInstanceError):
            auth.username = "evil"  # type: ignore[misc]

    def test_repr_redacts_password(self) -> None:
        """M6.1.5 脱敏要求前置: password 不进 repr / str()。"""
        auth = NacosAuth(username="ops", password="super-secret-token")
        text = repr(auth)
        assert "super-secret-token" not in text
        assert "password=<redacted>" in text
        assert "ops" in text  # username 是公开信息

    def test_equality(self) -> None:
        """Frozen dataclass 等值性: 同值相等。"""
        a = NacosAuth(username="ops", password="x")
        b = NacosAuth(username="ops", password="x")
        c = NacosAuth(username="ops", password="y")
        assert a == b
        assert a != c
        assert hash(a) == hash(b)


# ---------------------------------------------------------------------------
# NacosTLS tests

class TestNacosTLS:
    """NacosTLS 值对象: 必填 ca + 可选 mTLS + 脱敏。"""

    def test_create_valid_tls(self) -> None:
        tls = NacosTLS(ca="-----BEGIN CERTIFICATE-----\n...")
        assert tls.ca.startswith("-----BEGIN")
        assert tls.cert is None
        assert tls.key is None
        assert tls.verify is True

    def test_create_valid_mtls(self) -> None:
        tls = NacosTLS(
            ca="CA-PEM",
            cert="CERT-PEM",
            key="KEY-PEM",
            verify=True,
        )
        assert tls.cert == "CERT-PEM"
        assert tls.key == "KEY-PEM"

    def test_mtls_partial_rejected(self) -> None:
        """mTLS: cert + key 必须同时给。"""
        with pytest.raises(ValueError, match="cert/key must both be set"):
            NacosTLS(ca="CA-PEM", cert="CERT-PEM")  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="cert/key must both be set"):
            NacosTLS(ca="CA-PEM", key="KEY-PEM")  # type: ignore[call-arg]

    def test_empty_ca_rejected(self) -> None:
        with pytest.raises(ValueError, match="ca must be a non-empty str"):
            NacosTLS(ca="")

    def test_frozen(self) -> None:
        tls = NacosTLS(ca="CA-PEM")
        with pytest.raises(FrozenInstanceError):
            tls.verify = False  # type: ignore[misc]

    def test_repr_redacts_pem(self) -> None:
        """M6.1.5 脱敏要求前置: ca / cert / key PEM 不进 repr。"""
        tls = NacosTLS(
            ca="CA-PEM-SHOULD-NOT-LEAK",
            cert="CERT-PEM-SHOULD-NOT-LEAK",
            key="KEY-PEM-SHOULD-NOT-LEAK",
        )
        text = repr(tls)
        assert "CA-PEM-SHOULD-NOT-LEAK" not in text
        assert "CERT-PEM-SHOULD-NOT-LEAK" not in text
        assert "KEY-PEM-SHOULD-NOT-LEAK" not in text
        assert "redacted" in text
        assert "verify=True" in text


# ---------------------------------------------------------------------------
# NacosSourceState / NacosSourceError tests

class TestEnums:
    """StrEnum: 5 状态 + 5 错误分类 (PLANNING M6.1.4 准备)。"""

    def test_state_values(self) -> None:
        assert NacosSourceState.CONNECTING == "connecting"
        assert NacosSourceState.READY == "ready"
        assert NacosSourceState.STALE == "stale"
        assert NacosSourceState.DISCONNECTED == "disconnected"
        assert NacosSourceState.CLOSED == "closed"

    def test_error_values(self) -> None:
        assert NacosSourceError.AUTH == "auth"
        assert NacosSourceError.NOT_FOUND == "not_found"
        assert NacosSourceError.EMPTY == "empty"
        assert NacosSourceError.DECODE == "decode"
        assert NacosSourceError.NETWORK == "network"

    def test_str_enum_string_compatible(self) -> None:
        """StrEnum 自动 str(): f-string / JSON 序列化都自然工作。"""
        assert f"state={NacosSourceState.READY}" == "state=ready"
        assert str(NacosSourceError.NETWORK) == "network"


# ---------------------------------------------------------------------------
# NacosRuleSourceConfig tests

class TestNacosRuleSourceConfig:
    """NacosRuleSourceConfig 顶层: 不可变 + 必填 + 5 类 default-deny。"""

    def test_minimal_valid(self) -> None:
        cfg = NacosRuleSourceConfig(
            source_id="nacos-prod",
            server_addresses=("nacos-1.example.com:8848",),
            namespace="sentinel-prod",
            group="DEFAULT_GROUP",
            data_id_prefix="gateway",
        )
        assert cfg.source_id == "nacos-prod"
        assert cfg.namespace == "sentinel-prod"
        assert cfg.group == "DEFAULT_GROUP"
        assert cfg.data_id_prefix == "gateway"
        assert cfg.auth is None
        assert cfg.tls is None
        # 默认 timing
        assert cfg.connect_timeout == timedelta(seconds=3)
        assert cfg.read_timeout == timedelta(seconds=10)
        assert cfg.reconnect_initial == timedelta(seconds=1)
        assert cfg.reconnect_max == timedelta(seconds=30)

    def test_frozen(self) -> None:
        cfg = NacosRuleSourceConfig(
            source_id="nacos-prod",
            server_addresses=("nacos:8848",),
            namespace="prod",
            group="DEFAULT",
            data_id_prefix="gw",
        )
        with pytest.raises(FrozenInstanceError):
            cfg.source_id = "evil"  # type: ignore[misc]

    @pytest.mark.parametrize("field_name,empty_value", [
        ("source_id", ""),
        ("namespace", ""),
        ("group", ""),
        ("data_id_prefix", ""),
    ])
    def test_required_string_fields_reject_empty(self, field_name: str, empty_value: str) -> None:
        """必填字符串字段: 拒绝空串 (PLANNING default-deny)。"""
        kwargs = {
            "source_id": "nacos-prod",
            "server_addresses": ("nacos:8848",),
            "namespace": "prod",
            "group": "DEFAULT",
            "data_id_prefix": "gw",
        }
        kwargs[field_name] = empty_value
        with pytest.raises(ValueError, match=f"{field_name} must be a non-empty str"):
            NacosRuleSourceConfig(**kwargs)

    def test_server_addresses_reject_empty_tuple(self) -> None:
        with pytest.raises(ValueError, match="server_addresses must be a non-empty tuple"):
            NacosRuleSourceConfig(
                source_id="nacos-prod",
                server_addresses=(),
                namespace="prod",
                group="DEFAULT",
                data_id_prefix="gw",
            )

    def test_server_addresses_reject_invalid_entry(self) -> None:
        with pytest.raises(ValueError, match="invalid address"):
            NacosRuleSourceConfig(
                source_id="nacos-prod",
                server_addresses=("nacos-1:8848", ""),
                namespace="prod",
                group="DEFAULT",
                data_id_prefix="gw",
            )

    def test_server_addresses_accept_multiple(self) -> None:
        """多节点 Nacos 集群: tuple 防止 list 误用。"""
        cfg = NacosRuleSourceConfig(
            source_id="nacos-prod",
            server_addresses=(
                "nacos-1.example.com:8848",
                "nacos-2.example.com:8848",
                "nacos-3.example.com:8848",
            ),
            namespace="prod",
            group="DEFAULT",
            data_id_prefix="gw",
        )
        assert len(cfg.server_addresses) == 3

    @pytest.mark.parametrize("field_name,bad_value", [
        ("connect_timeout", timedelta(seconds=0)),
        ("connect_timeout", timedelta(seconds=-1)),
        ("read_timeout", timedelta(0)),
        ("reconnect_initial", timedelta(0)),
        ("reconnect_max", timedelta(0)),
    ])
    def test_timing_reject_non_positive(self, field_name: str, bad_value: timedelta) -> None:
        """超时与退避必须 > 0 (PLANNING 故障策略 default-deny)。"""
        kwargs = {
            "source_id": "nacos-prod",
            "server_addresses": ("nacos:8848",),
            "namespace": "prod",
            "group": "DEFAULT",
            "data_id_prefix": "gw",
        }
        kwargs[field_name] = bad_value
        with pytest.raises(ValueError, match=f"{field_name} must be a positive timedelta"):
            NacosRuleSourceConfig(**kwargs)

    def test_reconnect_max_must_be_at_least_initial(self) -> None:
        """PLANNING 故障策略: 退避上限不能 < 起始值 (避免退化)。"""
        with pytest.raises(ValueError, match="reconnect_max must be >= reconnect_initial"):
            NacosRuleSourceConfig(
                source_id="nacos-prod",
                server_addresses=("nacos:8848",),
                namespace="prod",
                group="DEFAULT",
                data_id_prefix="gw",
                reconnect_initial=timedelta(seconds=10),
                reconnect_max=timedelta(seconds=5),
            )

    def test_reconnect_max_equal_initial_ok(self) -> None:
        """边界: reconnect_max == reconnect_initial (不退避) 允许。"""
        cfg = NacosRuleSourceConfig(
            source_id="nacos-prod",
            server_addresses=("nacos:8848",),
            namespace="prod",
            group="DEFAULT",
            data_id_prefix="gw",
            reconnect_initial=timedelta(seconds=5),
            reconnect_max=timedelta(seconds=5),
        )
        assert cfg.reconnect_max == cfg.reconnect_initial

    def test_data_id_for_5_rule_types(self) -> None:
        """PLANNING M6.1 1:1 Java 约定: 5 个 rule data-id 后缀。"""
        cfg = NacosRuleSourceConfig(
            source_id="nacos-prod",
            server_addresses=("nacos:8848",),
            namespace="prod",
            group="DEFAULT",
            data_id_prefix="gateway",
        )
        assert cfg.data_id_for("flow") == "gateway-flow-rules.json"
        assert cfg.data_id_for("degrade") == "gateway-degrade-rules.json"
        assert cfg.data_id_for("param_flow") == "gateway-param-flow-rules.json"
        assert cfg.data_id_for("system") == "gateway-system-rules.json"
        assert cfg.data_id_for("authority") == "gateway-authority-rules.json"

    def test_data_id_for_unknown_rule_type_rejected(self) -> None:
        """PLANNING 资源上限 default-deny: 5 类固定, 不可扩展。"""
        cfg = NacosRuleSourceConfig(
            source_id="nacos-prod",
            server_addresses=("nacos:8848",),
            namespace="prod",
            group="DEFAULT",
            data_id_prefix="gw",
        )
        with pytest.raises(ValueError, match="unknown rule_type"):
            cfg.data_id_for("unknown_rule")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="unknown rule_type"):
            cfg.data_id_for("")  # type: ignore[arg-type]

    def test_data_id_prefix_can_contain_dashes(self) -> None:
        """data_id_prefix 允许 `region-team-` 等含 dash 形式。"""
        cfg = NacosRuleSourceConfig(
            source_id="nacos-prod",
            server_addresses=("nacos:8848",),
            namespace="prod",
            group="DEFAULT",
            data_id_prefix="region-team-a",
        )
        assert cfg.data_id_for("flow") == "region-team-a-flow-rules.json"

    def test_repr_does_not_leak_password_or_pem(self) -> None:
        """M6.1.5 脱敏要求前置: cfg.__repr__ 通过 auth/tls repr 链自动脱敏。"""
        auth = NacosAuth(username="ops", password="TOP-SECRET-PASSWORD")
        tls = NacosTLS(ca="CA-PEM-TOP-SECRET")
        cfg = NacosRuleSourceConfig(
            source_id="nacos-prod",
            server_addresses=("nacos-1:8848",),
            namespace="prod",
            group="DEFAULT",
            data_id_prefix="gw",
            auth=auth,
            tls=tls,
        )
        text = repr(cfg)
        assert "TOP-SECRET-PASSWORD" not in text
        assert "CA-PEM-TOP-SECRET" not in text
        assert "redacted" in text
        # 公开信息保留
        assert "nacos-prod" in text
        assert "nacos-1:8848" in text
        assert "prod" in text

    def test_equality(self) -> None:
        """Frozen dataclass 等值性: 同值相等。"""
        kwargs = {
            "source_id": "nacos-prod",
            "server_addresses": ("nacos:8848",),
            "namespace": "prod",
            "group": "DEFAULT",
            "data_id_prefix": "gw",
        }
        a = NacosRuleSourceConfig(**kwargs)
        b = NacosRuleSourceConfig(**kwargs)
        assert a == b
        assert hash(a) == hash(b)
        # 不同 source_id
        c = NacosRuleSourceConfig(**{**kwargs, "source_id": "nacos-other"})
        assert a != c
