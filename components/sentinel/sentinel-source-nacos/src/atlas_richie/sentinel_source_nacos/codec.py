"""Nacos data-id → :class:`RuleSnapshot` 解码 (M6.1.3)。

中文
----
**职责**: 把 Nacos 配置中心返回的 5 个 data-id 原始 JSON (每个对应一种
rule) 解码成主包 :class:`RuleSnapshot` 格式。

**不**做的事:

- **不** import ``nacos-sdk-python`` (本模块纯数据转换, 不触 SDK)
- **不**触网络 / SDK 调用 / 异步 I/O
- **不**做 schema 转换 (主包 ``RuleIndex`` 是 schema registry, 这里是
  raw JSON → 主包 dataclass 的字面映射)
- **不**改主包任何 rule dataclass 字段

**5 个 data_id 命名**: 通过
:meth:`NacosRuleSourceConfig.data_id_for` 拿到 (PLANNING 1:1 Java
约定: ``flow`` / ``degrade`` / ``param_flow`` / ``system`` / ``authority``)。

**输入格式** (与 Java sentinel-datasource-nacos 一致, JSON 数组)::

    [
      {"resource": "/foo", "grade": 1, "count": 100, ...},
      ...
    ]

**错误处理** (M6.1.4):

- 缺 1 个 data_id (key 不存在) → 视为 last-known-good 保留, 记
  :class:`NacosSourceError.NOT_FOUND`, **不**抛
- 内容为空 (``b""`` / ``""`` / ``"[]"`` / ``"null"``) → 视为"配置删除",
  记 :class:`NacosSourceError.EMPTY`, **不**抛
- JSON 解析失败 / 字段缺失 / 类型错 → 抛 :class:`NacosDecodeError`
  (继承自 :class:`NacosCodecError` 公共异常), 包含 :class:`NacosSourceError`
  语义 (DECODE)

English
--------
Nacos data-id → :class:`RuleSnapshot` decoding (M6.1.3).

**Does not**: import ``nacos-sdk-python``; do any I/O; do schema
conversion; modify main-package rule dataclass fields.

**5 data-id names**: derived via
:meth:`NacosRuleSourceConfig.data_id_for`.

**Input format** (1:1 Java sentinel-datasource-nacos, JSON array)::

    [
      {"resource": "/foo", "grade": 1, "count": 100, ...},
      ...
    ]

**Error handling** (M6.1.4):

- Missing data_id (key absent) → last-known-good, marked
  :class:`NacosSourceError.NOT_FOUND`, no raise
- Empty content (``b""`` / ``""`` / ``"[]"`` / ``"null"``) →
  "configuration deleted", marked :class:`NacosSourceError.EMPTY`, no raise
- JSON parse / field / type errors → :class:`NacosDecodeError`
  (public, captures :class:`NacosSourceError` semantic ``DECODE``)
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from atlas_richie.sentinel.rules.authority import AuthorityRule, AuthorityStrategy
from atlas_richie.sentinel.errors import SentinelConfigurationError
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

from .config import NacosRuleSourceConfig, NacosSourceError


# ---------------------------------------------------------------------------
# 公开异常 (M6.1.4)
# ---------------------------------------------------------------------------


class NacosCodecError(Exception):
    """Codec 公共异常根类 (M6.1.4)。

    中文
    ----
    公开异常树根; 子类:

    - :class:`NacosDecodeError` — JSON 解析 / 字段缺失 / 类型错

    公开理由: extension 测试可以 ``pytest.raises`` 验证字段缺失 /
    类型错映射到 DECODE 分类。

    English
    --------
    Public exception root. Subclass :class:`NacosDecodeError` covers
    JSON / field / type errors. Public so extension tests can
    ``pytest.raises`` and assert error class → NacosSourceError
    mapping.
    """

    nacos_error: NacosSourceError

    def __init__(self, message: str, *, data_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.data_id = data_id


class NacosDecodeError(NacosCodecError):
    """JSON 解析 / 字段缺失 / 类型错 (M6.1.4 → DECODE)。"""

    nacos_error = NacosSourceError.DECODE


# ---------------------------------------------------------------------------
# 5 个 rule_type 字符串常量 (与 config._RULE_TYPE_DATA_ID_SUFFIX key 一致)
# ---------------------------------------------------------------------------

_RULE_TYPE_FLOW = "flow"
_RULE_TYPE_DEGRADE = "degrade"
_RULE_TYPE_PARAM_FLOW = "param_flow"
_RULE_TYPE_SYSTEM = "system"
_RULE_TYPE_AUTHORITY = "authority"

# Per-rule-type required JSON field names. 缺一不可 (PLANNING 资源上限
# default-deny); 5 类固定, 不通过"自动发现"扩展。
_REQUIRED_RULE_FIELDS: dict[str, tuple[str, ...]] = {
    _RULE_TYPE_FLOW: (
        "resource", "grade", "count",
    ),
    _RULE_TYPE_DEGRADE: (
        "resource", "grade", "count", "timeWindow",
    ),
    _RULE_TYPE_PARAM_FLOW: (
        "resource", "grade", "paramIdx", "count",
    ),
    _RULE_TYPE_SYSTEM: (),  # 校验时按 strategy 单独算
    _RULE_TYPE_AUTHORITY: (
        "resource", "limitApp", "strategy",
    ),
}


# ---------------------------------------------------------------------------
# Resource selector 解析 (3 种 kind)
# ---------------------------------------------------------------------------


def _parse_resource(raw: Any) -> ResourceSelector:
    """把 Nacos ``resource`` 字符串解析为 :class:`ResourceSelector`。

    中文
    ----
    Nacos raw rule 的 ``resource`` 字段是单字符串; 按以下规则映射:

    - 以 ``"..."`` 结尾 (且长度 > 3) → :class:`SelectorKind.PREFIX`
    - 含 ``*`` 或 ``?`` → :class:`SelectorKind.GLOB`
    - 其它 → :class:`SelectorKind.EXACT`

    字符串为空 / 非字符串 → 抛 :class:`NacosDecodeError`。
    """
    if not isinstance(raw, str) or not raw:
        raise NacosDecodeError(
            f"resource must be a non-empty str (got {raw!r})",
        )
    if raw.endswith("...") and len(raw) > 3:
        return ResourceSelector(kind=SelectorKind.PREFIX, pattern=raw)
    if "*" in raw or "?" in raw:
        return ResourceSelector(kind=SelectorKind.GLOB, pattern=raw)
    return ResourceSelector(kind=SelectorKind.EXACT, pattern=raw)


# ---------------------------------------------------------------------------
# 5 个 decoder
# ---------------------------------------------------------------------------


def _coerce_list(data_id: str, payload: Any) -> list[dict[str, Any]]:
    """把 Nacos raw content 解析成 ``list[dict]``; 非数组 → 抛错。"""
    if not isinstance(payload, list):
        raise NacosDecodeError(
            f"Nacos data_id {data_id!r}: expected JSON array, "
            f"got {type(payload).__name__}",
            data_id=data_id,
        )
    out: list[dict[str, Any]] = []
    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            raise NacosDecodeError(
                f"Nacos data_id {data_id!r}[{i}]: expected JSON object, "
                f"got {type(item).__name__}",
                data_id=data_id,
            )
        out.append(item)
    return out


# Java sentinel-datasource-nacos 用整数表示 enum 值; Python 主包 StrEnum
# 用字符串值。Codec 接受**两种**形态 (优先级: 字符串 > 整数)。
#
# Java → Python 整数映射 (sentinel-datasource-nacos v1.8.x):
#   FlowGrade: 0 = CONCURRENCY (Java: "ThreadCount"), 1 = QPS
#   FlowControl / FlowBehavior: 0 = REJECT, 1 = WARM_UP, 2 = QUEUE
#   FlowScope: 0 = DIRECT, 1 = ORIGIN, 2 = ASSOCIATED_RESOURCE, 3 = CALL_PATH
#   DegradeStrategy: 0 = SLOW_CALL_RATIO, 1 = ERROR_RATIO,
#                    2 = ERROR_COUNT, 3 = SLOW_CALL_COUNT
#   AuthorityStrategy: 0 = ALLOW_LIST (Java: "WHITE"), 1 = DENY_LIST (Java: "BLACK")


def _coerce_enum(value: Any, enum_cls: type, int_map: dict[int, str], data_id: str, field: str) -> Any:
    """把 Nacos 字段值 (str 或 int) 转成 enum 实例; 不匹配 → 抛 NacosDecodeError。"""
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError:
            # 尝试按字符串小写匹配
            try:
                return enum_cls(value.lower())
            except ValueError:
                raise NacosDecodeError(
                    f"{data_id}: {field}={value!r} is not a valid "
                    f"{enum_cls.__name__}",
                    data_id=data_id,
                )
    if isinstance(value, int):
        mapped = int_map.get(value)
        if mapped is None:
            raise NacosDecodeError(
                f"{data_id}: {field}={value!r} has no integer → "
                f"{enum_cls.__name__} mapping",
                data_id=data_id,
            )
        return enum_cls(mapped)
    raise NacosDecodeError(
        f"{data_id}: {field} must be str or int (got {type(value).__name__})",
        data_id=data_id,
    )


_FLOW_GRADE_INT = {0: "concurrency", 1: "qps"}
_FLOW_BEHAVIOR_INT = {0: "reject", 1: "warm_up", 2: "reject"}  # behavior 与 control 同源
_FLOW_CONTROL_INT = {0: "reject", 1: "warm_up", 2: "queue"}
_FLOW_SCOPE_INT = {
    0: "direct", 1: "origin", 2: "associated_resource", 3: "call_path",
}
_DEGRADE_STRATEGY_INT = {
    0: "slow_call_ratio", 1: "error_ratio", 2: "error_count", 3: "slow_call_count",
}
_AUTHORITY_STRATEGY_INT = {0: "allow_list", 1: "deny_list"}
_SYSTEM_STRATEGY_INT = {0: "direct", 1: "adaptive_capacity"}
_PARAM_FLOW_SOURCE_INT = {
    0: "positional", 1: "keyword", 2: "header", 3: "query", 4: "cookie", 5: "custom",
}


def _decode_flow(data_id: str, items: list[dict[str, Any]]) -> dict[str, FlowRule]:
    """``-flow-rules.json`` → :class:`FlowRule` 字典。"""
    out: dict[str, FlowRule] = {}
    for i, item in enumerate(items):
        for required in _REQUIRED_RULE_FIELDS[_RULE_TYPE_FLOW]:
            if required not in item:
                raise NacosDecodeError(
                    f"Nacos data_id {data_id!r}[{i}]: missing required "
                    f"field {required!r}",
                    data_id=data_id,
                )
        try:
            grade = _coerce_enum(
                item["grade"], FlowGrade, _FLOW_GRADE_INT, data_id, "grade",
            )
            behavior = _coerce_enum(
                item.get("controlBehavior", "reject"),
                FlowBehavior, _FLOW_BEHAVIOR_INT,
                data_id, "controlBehavior",
            )
            control = _coerce_enum(
                item.get("controlBehavior", "reject"),
                FlowControl, _FLOW_CONTROL_INT,
                data_id, "controlBehavior",
            )
            scope = _coerce_enum(
                item.get("scope", 0),
                FlowScope, _FLOW_SCOPE_INT, data_id, "scope",
            )
            scope_ref = item.get("scopeReference")
            rule = FlowRule(
                rule_id=str(item.get("id", f"{data_id}#{i}")),
                selector=_parse_resource(item["resource"]),
                priority=int(item.get("priority", 0)),
                grade=grade,
                threshold=float(item["count"]),
                behavior=behavior,
                control=control,
                scope=scope,
                scope_reference=str(scope_ref) if scope_ref is not None else None,
                max_queueing_time_ms=int(item.get("maxQueueingTimeMs", 0)),
                warm_up_period_sec=float(item.get("warmUpPeriodSec", 0.0)),
            )
        except (ValueError, KeyError, TypeError, SentinelConfigurationError) as e:
            raise NacosDecodeError(
                f"Nacos data_id {data_id!r}[{i}]: invalid FlowRule: {e}",
                data_id=data_id,
            ) from e
        out[rule.rule_id] = rule
    return out


def _decode_degrade(data_id: str, items: list[dict[str, Any]]) -> dict[str, DegradeRule]:
    """``-degrade-rules.json`` → :class:`DegradeRule` 字典。

    中文
    ----
    Java sentinel-datasource-nacos 的 ``count`` 字段在不同 strategy 下语义
    不同; Python 主包 DegradeRule 把这两个语义拆成两个字段:

    - ERROR_COUNT / ERROR_RATIO: ``count`` → ``error_count_threshold``
    - SLOW_CALL_RATIO / SLOW_CALL_COUNT: ``count`` → ``slow_call_threshold_ms``
    """
    out: dict[str, DegradeRule] = {}
    for i, item in enumerate(items):
        for required in _REQUIRED_RULE_FIELDS[_RULE_TYPE_DEGRADE]:
            if required not in item:
                raise NacosDecodeError(
                    f"Nacos data_id {data_id!r}[{i}]: missing required "
                    f"field {required!r}",
                    data_id=data_id,
                )
        try:
            strategy = _coerce_enum(
                item["grade"], DegradeStrategy, _DEGRADE_STRATEGY_INT,
                data_id, "grade",
            )
            # count 字段按 strategy 分流
            count_value = int(item["count"])
            if strategy in (DegradeStrategy.SLOW_CALL_RATIO, DegradeStrategy.SLOW_CALL_COUNT):
                slow_call_threshold_ms = count_value
                error_count_threshold = int(item.get("errorCountThreshold", count_value))
            else:
                # ERROR_RATIO / ERROR_COUNT
                slow_call_threshold_ms = int(item.get("slowCallThresholdMs", 0))
                error_count_threshold = count_value
            rule = DegradeRule(
                rule_id=str(item.get("id", f"{data_id}#{i}")),
                selector=_parse_resource(item["resource"]),
                priority=int(item.get("priority", 0)),
                strategy=strategy,
                slow_call_threshold_ms=slow_call_threshold_ms,
                slow_call_ratio_threshold=float(
                    item.get("slowRatioThreshold", 0.0)
                ),
                error_count_threshold=error_count_threshold,
                error_ratio_threshold=float(item.get("exceptionRatio", 0.0)),
                minimum_request_count=int(item.get("minRequestAmount", 5)),
                stat_window_ms=int(item.get("statIntervalMs", 1000)),
                recovery_timeout_ms=int(item["timeWindow"]),
                half_open_probe_count=int(item.get("recoveryTimeout", 1)),
            )
        except (ValueError, KeyError, TypeError, SentinelConfigurationError) as e:
            raise NacosDecodeError(
                f"Nacos data_id {data_id!r}[{i}]: invalid DegradeRule: {e}",
                data_id=data_id,
            ) from e
        out[rule.rule_id] = rule
    return out


def _decode_param_flow(
    data_id: str, items: list[dict[str, Any]]
) -> dict[str, ParamFlowRule]:
    """``-param-flow-rules.json`` → :class:`ParamFlowRule` 字典。"""
    out: dict[str, ParamFlowRule] = {}
    for i, item in enumerate(items):
        for required in _REQUIRED_RULE_FIELDS[_RULE_TYPE_PARAM_FLOW]:
            if required not in item:
                raise NacosDecodeError(
                    f"Nacos data_id {data_id!r}[{i}]: missing required "
                    f"field {required!r}",
                    data_id=data_id,
                )
        try:
            source = _coerce_enum(
                item.get("paramKeyType", 0),
                ParameterSource, _PARAM_FLOW_SOURCE_INT,
                data_id, "paramKeyType",
            )
            rule = ParamFlowRule(
                rule_id=str(item.get("id", f"{data_id}#{i}")),
                selector=_parse_resource(item["resource"]),
                priority=int(item.get("priority", 0)),
                source=source,
                arg_index=int(item["paramIdx"]),
                arg_key=str(item.get("paramKey", "")),
                extractor_id=str(item.get("extractorId", "")),
                threshold=float(item["count"]),
                stat_window_ms=int(item.get("controlIntervalMs", 1000)),
                max_distinct_values=int(item.get("maxQueueingTimeMs", 100)),
                idle_ttl_ms=int(item.get("idleTtlMs", 0)),
                overflow_error=bool(item.get("overflow", True)),
            )
        except (ValueError, KeyError, TypeError, SentinelConfigurationError) as e:
            raise NacosDecodeError(
                f"Nacos data_id {data_id!r}[{i}]: invalid ParamFlowRule: {e}",
                data_id=data_id,
            ) from e
        out[rule.rule_id] = rule
    return out


def _decode_system(
    data_id: str, items: list[dict[str, Any]]
) -> dict[str, SystemRule]:
    """``-system-rules.json`` → :class:`SystemRule` 字典。"""
    out: dict[str, SystemRule] = {}
    for i, item in enumerate(items):
        try:
            strategy = _coerce_enum(
                item.get("strategy", 0),
                SystemStrategy, _SYSTEM_STRATEGY_INT,
                data_id, "strategy",
            )
            rule = SystemRule(
                rule_id=str(item.get("id", f"{data_id}#{i}")),
                priority=int(item.get("priority", 0)),
                strategy=strategy,
                max_cpu_usage=(
                    float(item["highestSystemLoad"])
                    if "highestSystemLoad" in item
                    else None
                ),
                max_load=(
                    float(item["avgLoad"])
                    if "avgLoad" in item
                    else None
                ),
                max_event_loop_lag_ms=(
                    float(item["maxRt"])
                    if "maxRt" in item
                    else None
                ),
                max_in_flight_qps=(
                    float(item["qps"])
                    if "qps" in item
                    else None
                ),
                min_stable_rt_ms=float(item.get("minRt", 1.0)),
                max_concurrent_adaptive=int(item.get("maxThread", 1000)),
            )
        except (ValueError, KeyError, TypeError, SentinelConfigurationError) as e:
            raise NacosDecodeError(
                f"Nacos data_id {data_id!r}[{i}]: invalid SystemRule: {e}",
                data_id=data_id,
            ) from e
        out[rule.rule_id] = rule
    return out


def _decode_authority(
    data_id: str, items: list[dict[str, Any]]
) -> dict[str, AuthorityRule]:
    """``-authority-rules.json`` → :class:`AuthorityRule` 字典。"""
    out: dict[str, AuthorityRule] = {}
    for i, item in enumerate(items):
        for required in _REQUIRED_RULE_FIELDS[_RULE_TYPE_AUTHORITY]:
            if required not in item:
                raise NacosDecodeError(
                    f"Nacos data_id {data_id!r}[{i}]: missing required "
                    f"field {required!r}",
                    data_id=data_id,
                )
        try:
            strategy = _coerce_enum(
                item["strategy"], AuthorityStrategy, _AUTHORITY_STRATEGY_INT,
                data_id, "strategy",
            )
            origins_raw = item.get("origins", ())
            if isinstance(origins_raw, (list, tuple, set)):
                origins = tuple(str(o) for o in origins_raw)
            elif isinstance(origins_raw, str):
                # 允许逗号分隔字符串
                origins = tuple(o.strip() for o in origins_raw.split(",") if o.strip())
            else:
                raise NacosDecodeError(
                    f"origins must be list/tuple/set/str, got "
                    f"{type(origins_raw).__name__}",
                )
            rule = AuthorityRule(
                rule_id=str(item.get("id", f"{data_id}#{i}")),
                selector=_parse_resource(item["resource"]),
                priority=int(item.get("priority", 0)),
                strategy=strategy,
                origins=origins,
                default_deny_unresolved=bool(item.get("defaultDeny", True)),
            )
        except (ValueError, KeyError, TypeError, SentinelConfigurationError) as e:
            raise NacosDecodeError(
                f"Nacos data_id {data_id!r}[{i}]: invalid AuthorityRule: {e}",
                data_id=data_id,
            ) from e
        out[rule.rule_id] = rule
    return out


# Dispatch table: rule_type → decoder
_DECODERS: dict[str, Any] = {
    _RULE_TYPE_FLOW: _decode_flow,
    _RULE_TYPE_DEGRADE: _decode_degrade,
    _RULE_TYPE_PARAM_FLOW: _decode_param_flow,
    _RULE_TYPE_SYSTEM: _decode_system,
    _RULE_TYPE_AUTHORITY: _decode_authority,
}


# ---------------------------------------------------------------------------
# Content 预处理: 脱壳 / JSON 解析
# ---------------------------------------------------------------------------


def _coerce_bytes_or_str(content: bytes | str) -> str:
    """统一 bytes / str 入参。"""
    if isinstance(content, bytes):
        return content.decode("utf-8")
    if isinstance(content, str):
        return content
    raise NacosDecodeError(
        f"content must be bytes or str (got {type(content).__name__})",
    )


class _EmptyContent(Exception):
    """内部 sentinel: 触发 EMPTY 分类。"""

    def __init__(self, *, data_id: str) -> None:
        super().__init__(data_id)
        self.data_id = data_id


def _parse_content(
    config: NacosRuleSourceConfig, rule_type: str, content: bytes | str
) -> list[dict[str, Any]]:
    """把 Nacos raw content 解析成 ``list[dict]``; 非 JSON 数组 → 抛错。"""
    data_id = config.data_id_for(rule_type)
    text = _coerce_bytes_or_str(content)
    if not text.strip():
        # Empty / whitespace only → EMPTY sentinel value; 抛回给 caller
        raise _EmptyContent(data_id=data_id)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        raise NacosDecodeError(
            f"Nacos data_id {data_id!r}: invalid JSON: {e}",
            data_id=data_id,
        ) from e
    if payload is None:
        # Java sentinel-datasource-nacos 把 "" / "[]" / "null" 都视为空
        raise _EmptyContent(data_id=data_id)
    if isinstance(payload, list) and len(payload) == 0:
        raise _EmptyContent(data_id=data_id)
    return _coerce_list(data_id, payload)


# ---------------------------------------------------------------------------
# 公开 API (M6.1.3)
# ---------------------------------------------------------------------------


def decode_rule_snapshot(
    data_ids: Mapping[str, bytes | str],
    rule_version: RuleVersion,
    *,
    config: NacosRuleSourceConfig,
) -> tuple[RuleSnapshot, list[NacosSourceError]]:
    """把 Nacos 5 个 data-id 原始内容解码成 :class:`RuleSnapshot`。

    中文
    ----
    **签名**: ``decode_rule_snapshot(data_ids, rule_version, *, config)``
    → ``(snapshot, warnings)``

    - ``data_ids`` — 5 个 data_id (经
      :meth:`NacosRuleSourceConfig.data_id_for` 生成的完整字符串) →
      原始 content (``bytes`` / ``str``) 的映射
    - ``rule_version`` — 新的 :class:`RuleVersion` (epoch / revision /
      checksum)
    - ``config`` — 必填 keyword-only, 用于生成 5 个 data_id 字符串 + 脱敏
      上下文

    返回:

    - ``snapshot`` — 解码成功的 :class:`RuleSnapshot` (含全部 5 类 rule,
      每类缺失 / 空 → 空 list, **不**抛错)
    - ``warnings`` — :class:`NacosSourceError` 列表; 缺 1 个 data_id →
      ``[NOT_FOUND]``, 空内容 → ``[EMPTY]``; JSON 解析失败 / 字段错 →
      **抛** :class:`NacosDecodeError` (5 类中唯一抛错的)

    校验顺序: NOT_FOUND (缺 key) → EMPTY (空 content) → DECODE (其它)

    English
    --------
    Decode 5 Nacos data-id raw contents into a :class:`RuleSnapshot`.

    Returns ``(snapshot, warnings)``. Missing / empty data_id maps to
    :class:`NacosSourceError.NOT_FOUND` / ``EMPTY`` recorded in
    warnings, not raised. JSON / field / type errors raise
    :class:`NacosDecodeError`.
    """
    warnings: list[NacosSourceError] = []
    rules: dict[str, Any] = {}

    for rule_type, decoder in _DECODERS.items():
        data_id = config.data_id_for(rule_type)
        if data_id not in data_ids:
            # NOT_FOUND: 缺 1 个 data_id; last-known-good 保留 (不抛)
            warnings.append(NacosSourceError.NOT_FOUND)
            continue
        content = data_ids[data_id]
        try:
            items = _parse_content(config, rule_type, content)
        except _EmptyContent:
            # EMPTY: 配置存在但为空 (配置删除); last-known-good 保留
            warnings.append(NacosSourceError.EMPTY)
            continue
        rules.update(decoder(data_id, items))

    snapshot = RuleSnapshot(
        version=rule_version,
        rules=rules,
        applied_at_ns=0,  # 0 = 尚未 apply; 由 Repository 设置
        source_id=config.source_id,
    )
    return snapshot, warnings


__all__ = [
    "NacosCodecError",
    "NacosDecodeError",
    "decode_rule_snapshot",
]
