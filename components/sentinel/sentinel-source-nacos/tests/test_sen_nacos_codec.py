"""M6.1.3 Nacos codec 契约测试。

中文
----
PLANNING M6.1.3 + M6.1.4 硬约束测试覆盖:

- 5 类 rule data-id → 主包 rule dataclass 正确解码
- 5 个 data_id 缺一 → NOT_FOUND (warning, **不**抛)
- 5 个 data_id 内容空 → EMPTY (warning, **不**抛)
- 5 个 data_id 内容坏 JSON / 缺字段 / 类型错 → DECODE
  (:class:`NacosDecodeError`, **抛**)
- :class:`RuleSnapshot` 的 ``rule_version`` / ``source_id`` 透传
- 5 类所有 rule 字段透传 (字段映射正确)
- Java sentinel-datasource-nacos 整数 enum 值 (0/1/2) 兼容
- 公开 API 不引入 nacos SDK 类型
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from atlas_richie.sentinel.rules.authority import AuthorityRule, AuthorityStrategy
from atlas_richie.sentinel.rules.degrade import DegradeRule, DegradeStrategy
from atlas_richie.sentinel.rules.flow import (
    FlowBehavior,
    FlowControl,
    FlowGrade,
    FlowRule,
    FlowScope,
)
from atlas_richie.sentinel.rules.param_flow import (
    ParameterSource,
    ParamFlowRule,
)
from atlas_richie.sentinel.rules.selector import ResourceSelector, SelectorKind
from atlas_richie.sentinel.rules.snapshot import RuleSnapshot, RuleVersion
from atlas_richie.sentinel.rules.system import SystemRule, SystemStrategy

from atlas_richie.sentinel_source_nacos.codec import (
    NacosCodecError,
    NacosDecodeError,
    decode_rule_snapshot,
)
from atlas_richie.sentinel_source_nacos.config import (
    NacosRuleSourceConfig,
    NacosSourceError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> NacosRuleSourceConfig:
    return NacosRuleSourceConfig(
        source_id="nacos-prod",
        server_addresses=("nacos-1:8848",),
        namespace="prod",
        group="DEFAULT_GROUP",
        data_id_prefix="gateway",
    )


@pytest.fixture
def rule_version() -> RuleVersion:
    return RuleVersion(epoch=1, revision=0, checksum="a" * 64)


def _ids(config: NacosRuleSourceConfig) -> dict[str, str]:
    """Return all 5 data_id strings keyed by rule type."""
    return {
        rt: config.data_id_for(rt)
        for rt in ("flow", "degrade", "param_flow", "system", "authority")
    }


# ---------------------------------------------------------------------------
# 5 类正常 JSON 解析
# ---------------------------------------------------------------------------


class TestDecodeSuccess:
    """5 类 rule data-id 正常 JSON → 主包 rule dataclass。"""

    def test_flow_decode(self, config: NacosRuleSourceConfig, rule_version: RuleVersion) -> None:
        ids = _ids(config)
        # Java sentinel-datasource-nacos 整数 enum format
        flow_payload = [
            {
                "resource": "/api/orders",
                "grade": 1,           # QPS
                "count": 100,
                "controlBehavior": 0, # REJECT
                "priority": 10,
            },
        ]
        # 4 个 data_id 用 `[]` 触发 EMPTY 警告 (PLANNING: "[]" 视为 EMPTY)
        snap, warns = decode_rule_snapshot(
            {
                ids["flow"]: json.dumps(flow_payload),
                ids["degrade"]: "[]",
                ids["param_flow"]: "[]",
                ids["system"]: "[]",
                ids["authority"]: "[]",
            },
            rule_version,
            config=config,
        )
        # flow 解码成功; 其它 4 个 [] → 4 个 EMPTY
        assert NacosSourceError.EMPTY in warns
        assert warns.count(NacosSourceError.EMPTY) == 4
        assert isinstance(snap, RuleSnapshot)
        assert snap.version is rule_version
        assert snap.source_id == "nacos-prod"
        assert len(snap.rules) == 1
        rule = next(iter(snap.rules.values()))
        assert isinstance(rule, FlowRule)
        assert rule.threshold == 100.0
        assert rule.grade is FlowGrade.QPS
        assert rule.behavior is FlowBehavior.REJECT
        assert rule.control is FlowControl.REJECT
        assert rule.scope is FlowScope.DIRECT
        assert rule.selector.pattern == "/api/orders"
        assert rule.selector.kind is SelectorKind.EXACT

    def test_degrade_decode(self, config: NacosRuleSourceConfig, rule_version: RuleVersion) -> None:
        ids = _ids(config)
        degrade_payload = [
            {
                "resource": "/api/pay",
                "grade": 1,        # ERROR_RATIO
                "count": 10,       # Java: count; 错误率触发用 exceptionRatio 字段
                "timeWindow": 5000,
                "exceptionRatio": 0.5,
                "minRequestAmount": 5,
            },
        ]
        snap, warns = decode_rule_snapshot(
            {
                ids["flow"]: "[]",
                ids["degrade"]: json.dumps(degrade_payload),
                ids["param_flow"]: "[]",
                ids["system"]: "[]",
                ids["authority"]: "[]",
            },
            rule_version,
            config=config,
        )
        assert warns.count(NacosSourceError.EMPTY) == 4
        rule = next(iter(snap.rules.values()))
        assert isinstance(rule, DegradeRule)
        assert rule.strategy is DegradeStrategy.ERROR_RATIO
        assert rule.error_ratio_threshold == 0.5
        assert rule.recovery_timeout_ms == 5000
        assert rule.minimum_request_count == 5

    def test_param_flow_decode(self, config: NacosRuleSourceConfig, rule_version: RuleVersion) -> None:
        ids = _ids(config)
        pf_payload = [
            {
                "resource": "/api/orders/:id",
                "grade": 1,        # QPS in Java
                "paramIdx": 0,
                "count": 50,
                "paramKeyType": 0,  # POSITIONAL
            },
        ]
        snap, warns = decode_rule_snapshot(
            {
                ids["flow"]: "[]",
                ids["degrade"]: "[]",
                ids["param_flow"]: json.dumps(pf_payload),
                ids["system"]: "[]",
                ids["authority"]: "[]",
            },
            rule_version,
            config=config,
        )
        assert warns.count(NacosSourceError.EMPTY) == 4
        rule = next(iter(snap.rules.values()))
        assert isinstance(rule, ParamFlowRule)
        assert rule.source is ParameterSource.POSITIONAL
        assert rule.arg_index == 0
        assert rule.threshold == 50.0

    def test_system_decode(self, config: NacosRuleSourceConfig, rule_version: RuleVersion) -> None:
        ids = _ids(config)
        sys_payload = [
            {
                "strategy": 0,           # DIRECT
                "highestSystemLoad": 0.8,
                "qps": 200.0,
                "avgLoad": 5.0,
                "maxRt": 50.0,
                "maxThread": 1000,
                "priority": 1,
            },
        ]
        snap, warns = decode_rule_snapshot(
            {
                ids["flow"]: "[]",
                ids["degrade"]: "[]",
                ids["param_flow"]: "[]",
                ids["system"]: json.dumps(sys_payload),
                ids["authority"]: "[]",
            },
            rule_version,
            config=config,
        )
        assert warns.count(NacosSourceError.EMPTY) == 4
        rule = next(iter(snap.rules.values()))
        assert isinstance(rule, SystemRule)
        assert rule.strategy is SystemStrategy.DIRECT
        assert rule.max_cpu_usage == 0.8
        assert rule.max_in_flight_qps == 200.0
        assert rule.max_load == 5.0
        assert rule.max_event_loop_lag_ms == 50.0

    def test_authority_decode(self, config: NacosRuleSourceConfig, rule_version: RuleVersion) -> None:
        ids = _ids(config)
        auth_payload = [
            {
                "resource": "/api/admin",
                "limitApp": "default",
                "strategy": 0,  # ALLOW_LIST
                "origins": ["appA", "appB"],
                "defaultDeny": True,
            },
        ]
        snap, warns = decode_rule_snapshot(
            {
                ids["flow"]: "[]",
                ids["degrade"]: "[]",
                ids["param_flow"]: "[]",
                ids["system"]: "[]",
                ids["authority"]: json.dumps(auth_payload),
            },
            rule_version,
            config=config,
        )
        assert warns.count(NacosSourceError.EMPTY) == 4
        rule = next(iter(snap.rules.values()))
        assert isinstance(rule, AuthorityRule)
        assert rule.strategy is AuthorityStrategy.ALLOW_LIST
        assert rule.origins == ("appA", "appB")
        assert rule.default_deny_unresolved is True

    def test_rule_version_passthrough(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        snap, _ = decode_rule_snapshot({}, rule_version, config=config)
        assert snap.version is rule_version

    def test_source_id_passthrough(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        snap, _ = decode_rule_snapshot({}, rule_version, config=config)
        assert snap.source_id == "nacos-prod"

    def test_bytes_content_also_accepted(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        # bytes content
        snap, warns = decode_rule_snapshot(
            {
                ids["flow"]: b'[{"resource":"/x","grade":1,"count":1}]',
                ids["degrade"]: b"[]",
                ids["param_flow"]: b"[]",
                ids["system"]: b"[]",
                ids["authority"]: b"[]",
            },
            rule_version,
            config=config,
        )
        assert warns.count(NacosSourceError.EMPTY) == 4
        assert len(snap.rules) == 1


# ---------------------------------------------------------------------------
# 缺 1 个 data_id (5 个 case) — NOT_FOUND 警告, **不**抛
# ---------------------------------------------------------------------------


class TestNotFound:
    """缺 1 个 data_id → NOT_FOUND warning, 不抛错。"""

    @pytest.mark.parametrize("missing_rule_type", [
        "flow", "degrade", "param_flow", "system", "authority",
    ])
    def test_missing_data_id(
        self,
        config: NacosRuleSourceConfig,
        rule_version: RuleVersion,
        missing_rule_type: str,
    ) -> None:
        ids = _ids(config)
        # 4 个 data_id 给 `[]` → 4 个 EMPTY; 1 个缺失 → 1 个 NOT_FOUND
        data = {ids[rt]: "[]" for rt in ids if rt != missing_rule_type}
        snap, warns = decode_rule_snapshot(data, rule_version, config=config)
        assert NacosSourceError.NOT_FOUND in warns
        assert NacosSourceError.EMPTY in warns
        assert warns.count(NacosSourceError.NOT_FOUND) == 1
        assert warns.count(NacosSourceError.EMPTY) == 4
        assert len(snap.rules) == 0

    def test_all_missing_all_not_found(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        snap, warns = decode_rule_snapshot({}, rule_version, config=config)
        assert warns.count(NacosSourceError.NOT_FOUND) == 5
        assert warns.count(NacosSourceError.EMPTY) == 0
        assert len(snap.rules) == 0


# ---------------------------------------------------------------------------
# 空内容 (5 个 case) — EMPTY 警告, **不**抛
# ---------------------------------------------------------------------------


class TestEmpty:
    """5 个空内容形态 (b'' / '' / '[]' / 'null' / whitespace) → EMPTY 警告。

    注: 按 PLANNING M6.1.4 决策, ``"[]"`` 也是 EMPTY (与 Nacos 删除配置
    语义一致); 其它 4 个 data_id 也给 ``"[]"`` 也会触发 EMPTY。
    本测试只确认 1 个 EMPTY 来源 + 1 个 EMPTY 目标 = 5 个 EMPTY 总数。
    """

    @pytest.mark.parametrize("empty_payload", [
        b"",
        "",
        "[]",
        "null",
        "   \n  ",
    ])
    def test_empty_content(
        self,
        config: NacosRuleSourceConfig,
        rule_version: RuleVersion,
        empty_payload: Any,
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = empty_payload
        snap, warns = decode_rule_snapshot(data, rule_version, config=config)
        # 5 个 data_id 全部 EMPTY (4 个 "[]" + 1 个 flow 的 empty_payload)
        assert NacosSourceError.EMPTY in warns
        assert NacosSourceError.NOT_FOUND not in warns
        assert warns.count(NacosSourceError.EMPTY) == 5
        assert len(snap.rules) == 0


# ---------------------------------------------------------------------------
# DECODE 错误 (5+ case) — NacosDecodeError
# ---------------------------------------------------------------------------


class TestDecodeError:
    """JSON 解析失败 / 缺字段 / 类型错 → NacosDecodeError (DECODE 分类)。"""

    def test_bad_json_raises_decode_error(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = "{not valid json"
        with pytest.raises(NacosDecodeError) as exc_info:
            decode_rule_snapshot(data, rule_version, config=config)
        assert exc_info.value.nacos_error is NacosSourceError.DECODE
        assert exc_info.value.data_id == ids["flow"]

    def test_missing_required_field_raises(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        # flow 缺 'grade' 字段
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = '[{"resource":"/x","count":10}]'
        with pytest.raises(NacosDecodeError) as exc_info:
            decode_rule_snapshot(data, rule_version, config=config)
        assert "grade" in str(exc_info.value)

    def test_invalid_grade_int_raises(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        # grade=99 没有映射
        data[ids["flow"]] = '[{"resource":"/x","grade":99,"count":1}]'
        with pytest.raises(NacosDecodeError) as exc_info:
            decode_rule_snapshot(data, rule_version, config=config)
        assert "no integer" in str(exc_info.value) or "grade" in str(exc_info.value)

    def test_invalid_threshold_raises(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        # threshold <= 0 (FlowRule validation)
        data[ids["flow"]] = '[{"resource":"/x","grade":1,"count":0}]'
        with pytest.raises(NacosDecodeError):
            decode_rule_snapshot(data, rule_version, config=config)

    def test_non_array_payload_raises(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = '{"resource":"/x"}'  # object, not array
        with pytest.raises(NacosDecodeError):
            decode_rule_snapshot(data, rule_version, config=config)

    def test_non_object_item_raises(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = '["just a string"]'
        with pytest.raises(NacosDecodeError):
            decode_rule_snapshot(data, rule_version, config=config)

    def test_degrade_missing_timeWindow(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        # degrade 缺 timeWindow
        data[ids["degrade"]] = '[{"resource":"/x","grade":0,"count":1}]'
        with pytest.raises(NacosDecodeError) as exc_info:
            decode_rule_snapshot(data, rule_version, config=config)
        assert "timeWindow" in str(exc_info.value)

    def test_authority_missing_strategy(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        # authority 缺 strategy
        data[ids["authority"]] = '[{"resource":"/x","limitApp":"default"}]'
        with pytest.raises(NacosDecodeError):
            decode_rule_snapshot(data, rule_version, config=config)

    def test_decode_error_inherits_codec_error(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        """NacosDecodeError 必须继承 NacosCodecError。"""
        assert issubclass(NacosDecodeError, NacosCodecError)
        assert issubclass(NacosDecodeError, Exception)
        # nacos_error 字段映射到 DECODE
        assert NacosDecodeError.nacos_error is NacosSourceError.DECODE


# ---------------------------------------------------------------------------
# Resource selector 解析 (3 种 kind)
# ---------------------------------------------------------------------------


class TestResourceSelector:
    """ResourceSelector 3 种 kind 解析: EXACT / PREFIX / GLOB。"""

    def test_exact_resource(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = '[{"resource":"/api/orders","grade":1,"count":1}]'
        snap, _ = decode_rule_snapshot(data, rule_version, config=config)
        rule = next(iter(snap.rules.values()))
        assert rule.selector.kind is SelectorKind.EXACT
        assert rule.selector.pattern == "/api/orders"

    def test_prefix_resource(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = '[{"resource":"/api/...","grade":1,"count":1}]'
        snap, _ = decode_rule_snapshot(data, rule_version, config=config)
        rule = next(iter(snap.rules.values()))
        assert rule.selector.kind is SelectorKind.PREFIX
        assert rule.selector.pattern == "/api/..."

    def test_glob_resource(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = '[{"resource":"/api/*","grade":1,"count":1}]'
        snap, _ = decode_rule_snapshot(data, rule_version, config=config)
        rule = next(iter(snap.rules.values()))
        assert rule.selector.kind is SelectorKind.GLOB
        assert rule.selector.pattern == "/api/*"

    def test_empty_resource_raises(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = '[{"resource":"","grade":1,"count":1}]'
        with pytest.raises(NacosDecodeError):
            decode_rule_snapshot(data, rule_version, config=config)


# ---------------------------------------------------------------------------
# Java sentinel-datasource-nacos 整数 enum 兼容
# ---------------------------------------------------------------------------


class TestJavaIntegerEnumCompat:
    """Java sentinel-datasource-nacos 用整数表示 enum, Python 主包用字符串值。

    Codec 必须接受两种形态。"""

    def test_flow_grade_int_0_concurrency(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = '[{"resource":"/x","grade":0,"count":5}]'
        snap, _ = decode_rule_snapshot(data, rule_version, config=config)
        assert next(iter(snap.rules.values())).grade is FlowGrade.CONCURRENCY

    def test_flow_control_int_2_queue(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = '[{"resource":"/x","grade":1,"count":1,"controlBehavior":2}]'
        snap, _ = decode_rule_snapshot(data, rule_version, config=config)
        rule = next(iter(snap.rules.values()))
        assert rule.control is FlowControl.QUEUE

    def test_flow_scope_int_1_origin(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = (
            '[{"resource":"/x","grade":1,"count":1,'
            '"scope":1,"scopeReference":"appA"}]'
        )
        snap, _ = decode_rule_snapshot(data, rule_version, config=config)
        rule = next(iter(snap.rules.values()))
        assert rule.scope is FlowScope.ORIGIN
        assert rule.scope_reference == "appA"

    def test_degrade_strategy_int_0_slow_ratio(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        # SLOW_CALL_RATIO 需要 slow_call_threshold_ms (int, 从 count) + slow_call_ratio_threshold (float 0..1, 从 slowRatioThreshold)
        data[ids["degrade"]] = (
            '[{"resource":"/x","grade":0,"count":50,"timeWindow":1000,'
            '"slowRatioThreshold":0.5}]'
        )
        snap, _ = decode_rule_snapshot(data, rule_version, config=config)
        assert next(iter(snap.rules.values())).strategy is DegradeStrategy.SLOW_CALL_RATIO

    def test_param_flow_source_int_2_header(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["param_flow"]] = (
            '[{"resource":"/x","grade":1,"paramIdx":0,"count":5,'
            '"paramKeyType":2,"paramKey":"X-User"}]'
        )
        snap, _ = decode_rule_snapshot(data, rule_version, config=config)
        rule = next(iter(snap.rules.values()))
        assert rule.source is ParameterSource.HEADER
        assert rule.arg_key == "X-User"

    def test_authority_strategy_int_1_deny(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["authority"]] = (
            '[{"resource":"/x","limitApp":"default","strategy":1,"origins":["x"]}]'
        )
        snap, _ = decode_rule_snapshot(data, rule_version, config=config)
        assert next(iter(snap.rules.values())).strategy is AuthorityStrategy.DENY_LIST

    def test_string_enum_also_accepted(
        self, config: NacosRuleSourceConfig, rule_version: RuleVersion
    ) -> None:
        """Python 原生 str 形态 enum 也要能解析 (测试 + 自我描述配置)。"""
        ids = _ids(config)
        data = {ids[rt]: "[]" for rt in ids}
        data[ids["flow"]] = (
            '[{"resource":"/x","grade":"qps","count":1,'
            '"controlBehavior":"reject","scope":"direct"}]'
        )
        snap, _ = decode_rule_snapshot(data, rule_version, config=config)
        rule = next(iter(snap.rules.values()))
        assert rule.grade is FlowGrade.QPS
        assert rule.control is FlowControl.REJECT
        assert rule.scope is FlowScope.DIRECT


# ---------------------------------------------------------------------------
# 公开 API 边界 (C 层隔离 / 不泄漏 SDK)
# ---------------------------------------------------------------------------


class TestPublicApiBoundary:
    """公开 API 入参 / 返回值不引入 nacos SDK 类型。"""

    def test_decode_rule_snapshot_signature_no_sdk_types(self) -> None:
        """decode_rule_snapshot 入参 / 返回不含 nacos_sdk_python 类型。

        注: ``NacosRuleSourceConfig`` / ``NacosSourceError`` / ``NacosDecodeError``
        是本 wheel 自己的公开值对象, **不**算"泄漏 SDK"。
        泄漏的判定标准: 任何 ``module`` 来自 ``nacos`` 顶层或 ``nacos.*`` 子模块。
        """
        import inspect
        sig = inspect.signature(decode_rule_snapshot)
        for pname, p in sig.parameters.items():
            ann = p.annotation
            if ann is inspect.Parameter.empty:
                continue
            ann_mod = getattr(ann, "__module__", "")
            assert not ann_mod.startswith("nacos"), (
                f"param {pname!r} leaks nacos SDK type: {ann} (module={ann_mod})"
            )

    def test_codec_does_not_import_nacos_sdk(self) -> None:
        """codec 模块**不**能静态导入 nacos_sdk_python。"""
        import atlas_richie.sentinel_source_nacos.codec as mod
        # 检查 mod 自身的 globals 是否有 nacos.* 类型
        for name, val in vars(mod).items():
            if name.startswith("_"):
                continue
            ann_mod = getattr(type(val), "__module__", "")
            if ann_mod.startswith("nacos"):
                pytest.fail(
                    f"codec.{name} leaks nacos SDK type "
                    f"(module={ann_mod})"
                )
