"""Redis 性能守卫的复杂度分级表 + String 载荷形状规则测试。

覆盖三块：

1. **分级表**（`RedisComplexityTier` / `RedisCommandMeta` /
   `RedisOperationCatalog`）——26 条预设的取值、探测建议与工厂方法。
2. **String 载荷形状规则**（`RedisStringPayloadInspector`）——集合 / Map
   整包、超大文本、疑似整包 JSON 的判定。
3. **策略判定**（`RedisPerfGuard.check_operation_tier` /
   `check_string_write_payload`）——白名单、非 O(1) 告警、禁用档拦截、
   BIGKEY 探测提示。

外加**接线验证**：用 MagicMock 后端 + 记录型 guard，确认每个 manager 方法
声明的是**哪一条** catalog 预设——分级表只有被真正引用才算落地。

English
--------
Unit tests for the complexity-tier catalogue and the String payload shape
rules, plus wiring checks that every manager method declares the expected
catalogue preset.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest
import structlog.testing

from atlas_richie.cache_redis import ConfigurationError
from atlas_richie.cache_redis.managers.redis_bitmap_manager import RedisBitmapManager
from atlas_richie.cache_redis.managers.redis_collection_manager import (
    RedisCollectionManager,
)
from atlas_richie.cache_redis.managers.redis_field_manager import RedisFieldManager
from atlas_richie.cache_redis.managers.redis_geo_manager import RedisGeoManager
from atlas_richie.cache_redis.managers.redis_hyper_log_manager import (
    RedisHyperLogManager,
)
from atlas_richie.cache_redis.managers.redis_key_manager import RedisKeyManager
from atlas_richie.cache_redis.managers.redis_limiter_manager import (
    RedisLimiterManager,
)
from atlas_richie.cache_redis.managers.redis_ranking_manager import (
    RedisRankingManager,
)
from atlas_richie.cache_redis.managers.redis_script_manager import RedisScriptManager
from atlas_richie.cache_redis.managers.redis_string_manager import RedisStringManager
from atlas_richie.cache_redis.perf import (
    BLOCKED_TIERS,
    RedisCommandMeta,
    RedisComplexityTier,
    RedisOperationCatalog,
    RedisPerfGuard,
    RedisStringPayloadInspector,
    StringPayloadSeverity,
)
from atlas_richie.cache_redis.redis_cache_properties import RedisPerfSettings

pytestmark = pytest.mark.unit


# ── Helpers ──────────────────────────────────────────────────────


def _perf(**overrides: Any) -> RedisPerfSettings:
    """构造一份 perf 配置（默认关闭，由各用例按需打开）。"""
    return RedisPerfSettings(**overrides)


class _SpyGuard:
    """记录型 guard：只记调用，不做判定。"""

    def __init__(self) -> None:
        self.tiers: list[tuple[str, Any]] = []
        self.shapes: list[tuple[str, str, Any]] = []
        self.batches: list[tuple[str, int]] = []

    def check_operation_tier(self, op_name: str, meta: Any) -> None:
        self.tiers.append((op_name, meta))

    def check_string_write_payload(
        self, op_name: str, key: str, value: Any
    ) -> None:
        self.shapes.append((op_name, key, value))

    def check_batch_size(self, op_name: str, items: int) -> None:
        self.batches.append((op_name, items))

    def check_key_name_hint(self, key: str) -> None:
        return None

    def check_string_payload(self, op_name: str, value: Any) -> None:
        return None

    @contextmanager
    def time_op(self, op_name: str) -> Iterator[None]:
        yield


def _backend() -> MagicMock:
    """一个够用的假后端——被测的判定都发生在访问 Redis 之前。"""
    backend = MagicMock()
    backend.namespace = "test"
    backend.make_key.side_effect = lambda key: f"test:{key}"
    client = MagicMock()
    client.scan_iter.return_value = []
    client.smembers.return_value = []
    client.hgetall.return_value = {}
    client.hkeys.return_value = []
    client.mget.return_value = []
    backend.raw_client.return_value = client
    return backend


# ── Complexity tier ──────────────────────────────────────────────


class TestRedisComplexityTier:
    def test_values_match_java(self) -> None:
        assert [t.value for t in RedisComplexityTier] == [
            "O1",
            "LOG_N",
            "LINEAR_N",
            "WORSE",
            "SCRIPT_OR_UNKNOWN",
        ]

    def test_blocked_tiers_are_linear_and_worse(self) -> None:
        """Java `shouldBlock`: LINEAR_N / WORSE 拦截，LOG_N 不拦。"""
        assert BLOCKED_TIERS == {
            RedisComplexityTier.LINEAR_N,
            RedisComplexityTier.WORSE,
        }


# ── Command meta ─────────────────────────────────────────────────


class TestRedisCommandMeta:
    def test_o1_has_no_probe_hints(self) -> None:
        meta = RedisCommandMeta.o1("GET/SET 单 key")
        assert meta.tier is RedisComplexityTier.O1
        assert meta.probe_hints() == []

    def test_log_n_carries_the_zcard_probe(self) -> None:
        """与 Java `logN` 一致：LOG_N 预设带 ZCARD 探测建议。"""
        meta = RedisCommandMeta.log_n("ZSet 排名")
        assert meta.tier is RedisComplexityTier.LOG_N
        assert meta.probe_hints() == ["ZCARD"]

    def test_linear_carries_the_requested_probes(self) -> None:
        meta = RedisCommandMeta.linear(
            "HGETALL", hlen=True, scard=True
        )
        assert meta.tier is RedisComplexityTier.LINEAR_N
        assert meta.probe_hints() == ["HLEN", "SCARD"]

    def test_script_and_worse_tiers(self) -> None:
        assert (
            RedisCommandMeta.script("EVAL").tier
            is RedisComplexityTier.SCRIPT_OR_UNKNOWN
        )
        assert RedisCommandMeta.worse("O(n^2)").tier is RedisComplexityTier.WORSE

    def test_meta_is_immutable(self) -> None:
        meta = RedisCommandMeta.o1("x")
        with pytest.raises(Exception):
            meta.tier = RedisComplexityTier.WORSE  # type: ignore[misc]


# ── Operation catalog ───────────────────────────────────────────


class TestRedisOperationCatalog:
    def test_catalog_has_26_presets(self) -> None:
        presets = [
            name
            for name in dir(RedisOperationCatalog)
            if name.isupper() and name != "BLOCKED_TIERS"
        ]
        assert len(presets) == 26

    @pytest.mark.parametrize(
        ("name", "tier"),
        [
            ("STRING_SINGLE", RedisComplexityTier.O1),
            ("STRING_MULTI_GET", RedisComplexityTier.LINEAR_N),
            ("HASH_FIELD", RedisComplexityTier.O1),
            ("HASH_FULL", RedisComplexityTier.LINEAR_N),
            ("HASH_KEYS", RedisComplexityTier.LINEAR_N),
            ("HASH_MULTI_FIELD", RedisComplexityTier.LINEAR_N),
            ("LIST_RANGE", RedisComplexityTier.LINEAR_N),
            ("KEYS_PATTERN", RedisComplexityTier.LINEAR_N),
            ("ZSET_ORDERED", RedisComplexityTier.LOG_N),
            ("ZSET_MULTI_KEY", RedisComplexityTier.LINEAR_N),
            ("ZSET_BATCH", RedisComplexityTier.LINEAR_N),
            ("SET_MEMBERS", RedisComplexityTier.LINEAR_N),
            ("SET_COMBINE", RedisComplexityTier.LINEAR_N),
            ("GEO_RADIUS", RedisComplexityTier.LINEAR_N),
            ("GEO_ADD", RedisComplexityTier.O1),
            ("GEO_DIST", RedisComplexityTier.O1),
            ("LUA_EVAL", RedisComplexityTier.SCRIPT_OR_UNKNOWN),
            ("LOCK_TRY", RedisComplexityTier.O1),
            ("STREAM_XADD", RedisComplexityTier.SCRIPT_OR_UNKNOWN),
            ("STREAM_ACK", RedisComplexityTier.O1),
            ("PUBLISH", RedisComplexityTier.O1),
            ("BIT_OP", RedisComplexityTier.O1),
            ("HLL_PFADD", RedisComplexityTier.LINEAR_N),
            ("HLL_PF_COUNT", RedisComplexityTier.O1),
            ("EVENT_SUBSCRIBE", RedisComplexityTier.O1),
            ("LIMITER_LUA", RedisComplexityTier.SCRIPT_OR_UNKNOWN),
        ],
    )
    def test_preset_tiers(self, name: str, tier: RedisComplexityTier) -> None:
        assert getattr(RedisOperationCatalog, name).tier is tier

    @pytest.mark.parametrize(
        ("name", "hints"),
        [
            ("HASH_FULL", ["HLEN"]),
            ("HASH_KEYS", ["HLEN"]),
            ("LIST_RANGE", ["LLEN"]),
            ("SET_MEMBERS", ["SCARD"]),
            ("SET_COMBINE", ["SCARD"]),
            ("ZSET_MULTI_KEY", ["ZCARD"]),
            ("ZSET_BATCH", ["ZCARD"]),
            ("ZSET_ORDERED", ["ZCARD"]),
            ("STRING_MULTI_GET", []),
            ("KEYS_PATTERN", []),
        ],
    )
    def test_preset_probe_hints(self, name: str, hints: list[str]) -> None:
        assert getattr(RedisOperationCatalog, name).probe_hints() == hints

    def test_every_preset_has_a_description(self) -> None:
        for name in dir(RedisOperationCatalog):
            if not name.isupper():
                continue
            preset = getattr(RedisOperationCatalog, name)
            if isinstance(preset, RedisCommandMeta):
                assert preset.description, f"{name} 缺少说明"


# ── String payload inspector ─────────────────────────────────────


@dataclass
class _Complex:
    """既不是标量也不是集合——触发"疑似复杂对象整包"告警。"""

    value: int


class TestRedisStringPayloadInspector:
    def test_none_is_ok(self) -> None:
        result = RedisStringPayloadInspector.inspect(None, _perf())
        assert result.severity is StringPayloadSeverity.OK
        assert result.is_ok is True

    @pytest.mark.parametrize("value", [1, 1.5, True, "plain", uuid.uuid4()])
    def test_scalars_are_ok(self, value: Any) -> None:
        result = RedisStringPayloadInspector.inspect(value, _perf())
        assert result.severity is StringPayloadSeverity.OK

    @pytest.mark.parametrize(
        "value", [[1, 2], {"a": 1}, (1, 2), {1, 2}, frozenset({1})]
    )
    def test_collections_are_errors(self, value: Any) -> None:
        """集合 / Map 整包塞 String 是明确滥用。"""
        result = RedisStringPayloadInspector.inspect(value, _perf())
        assert result.severity is StringPayloadSeverity.ERROR
        assert "集合" in result.detail

    def test_dict_is_an_error(self) -> None:
        result = RedisStringPayloadInspector.inspect({"a": 1}, _perf())
        assert result.severity is StringPayloadSeverity.ERROR

    def test_complex_object_is_a_warning(self) -> None:
        result = RedisStringPayloadInspector.inspect(_Complex(1), _perf())
        assert result.severity is StringPayloadSeverity.WARN

    def test_str_char_thresholds(self) -> None:
        perf = _perf(string_payload_max_chars_warn=10, string_payload_max_chars_error=20)
        assert (
            RedisStringPayloadInspector.inspect("x" * 9, perf).severity
            is StringPayloadSeverity.OK
        )
        assert (
            RedisStringPayloadInspector.inspect("x" * 10, perf).severity
            is StringPayloadSeverity.WARN
        )
        assert (
            RedisStringPayloadInspector.inspect("x" * 20, perf).severity
            is StringPayloadSeverity.ERROR
        )

    def test_bytes_byte_thresholds(self) -> None:
        perf = _perf(
            string_payload_max_bytes_warn=10, string_payload_max_bytes_error=20
        )
        assert (
            RedisStringPayloadInspector.inspect(b"x" * 9, perf).severity
            is StringPayloadSeverity.OK
        )
        assert (
            RedisStringPayloadInspector.inspect(b"x" * 10, perf).severity
            is StringPayloadSeverity.WARN
        )
        assert (
            RedisStringPayloadInspector.inspect(b"x" * 20, perf).severity
            is StringPayloadSeverity.ERROR
        )

    def test_json_like_string_is_a_warning(self) -> None:
        perf = _perf(json_like_min_chars_for_warn=10)
        blob = '{"a": ' + "0" * 20 + "}"
        result = RedisStringPayloadInspector.inspect(blob, perf)
        assert result.severity is StringPayloadSeverity.WARN
        assert "JSON" in result.detail

    def test_json_like_array_is_a_warning(self) -> None:
        perf = _perf(json_like_min_chars_for_warn=10)
        blob = "[" + "0" * 20 + "]"
        assert (
            RedisStringPayloadInspector.inspect(blob, perf).severity
            is StringPayloadSeverity.WARN
        )

    def test_short_json_like_string_is_ok(self) -> None:
        perf = _perf(json_like_min_chars_for_warn=100)
        assert (
            RedisStringPayloadInspector.inspect('{"a":1}', perf).severity
            is StringPayloadSeverity.OK
        )

    def test_json_heuristic_can_be_disabled(self) -> None:
        perf = _perf(json_like_min_chars_for_warn=10, warn_json_like_string_blob=False)
        blob = '{"a": ' + "0" * 20 + "}"
        assert (
            RedisStringPayloadInspector.inspect(blob, perf).severity
            is StringPayloadSeverity.OK
        )


# ── Guard: complexity tier policy ────────────────────────────────


class TestGuardTierPolicy:
    def test_disabled_is_a_noop(self) -> None:
        guard = RedisPerfGuard(_perf(enabled=False, block_forbidden_tiers=True))
        with structlog.testing.capture_logs() as logs:
            guard.check_operation_tier(
                "op", RedisOperationCatalog.HASH_FULL
            )
        assert logs == []

    def test_linear_tier_is_blocked_when_configured(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_forbidden_tiers=True)
        )
        with pytest.raises(ConfigurationError):
            guard.check_operation_tier("op", RedisOperationCatalog.HASH_FULL)

    def test_worse_tier_is_blocked_when_configured(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_forbidden_tiers=True)
        )
        with pytest.raises(ConfigurationError):
            guard.check_operation_tier(
                "op", RedisCommandMeta.worse("O(n^2)")
            )

    def test_log_n_is_not_blocked(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_forbidden_tiers=True)
        )
        guard.check_operation_tier("op", RedisOperationCatalog.ZSET_ORDERED)

    def test_o1_is_not_blocked(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_forbidden_tiers=True)
        )
        guard.check_operation_tier("op", RedisOperationCatalog.BIT_OP)

    def test_script_tier_is_not_blocked(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_forbidden_tiers=True)
        )
        guard.check_operation_tier("op", RedisOperationCatalog.LUA_EVAL)

    def test_whitelist_violation_blocks_when_forbidden_tiers_block(self) -> None:
        guard = RedisPerfGuard(
            _perf(
                enabled=True,
                block_forbidden_tiers=True,
                toc_allowed_complexities=["O1"],
            )
        )
        with pytest.raises(ConfigurationError):
            guard.check_operation_tier("op", RedisOperationCatalog.HASH_FULL)

    def test_whitelist_violation_only_logs_without_blocking(self) -> None:
        guard = RedisPerfGuard(
            _perf(
                enabled=True,
                block_forbidden_tiers=False,
                toc_allowed_complexities=["O1"],
            )
        )
        with structlog.testing.capture_logs() as logs:
            guard.check_operation_tier("op", RedisOperationCatalog.HASH_FULL)
        assert any(e["event"] == "perf.tier_not_allowed" for e in logs)

    def test_whitelist_is_case_insensitive_and_trimmed(self) -> None:
        guard = RedisPerfGuard(
            _perf(
                enabled=True,
                block_forbidden_tiers=True,
                toc_allowed_complexities=[" o1 "],
            )
        )
        guard.check_operation_tier("op", RedisOperationCatalog.BIT_OP)

    def test_empty_whitelist_allows_everything(self) -> None:
        """白名单为空 = 不做白名单判定（与 Java 的 null/empty 语义一致）。

        注意这与"禁用档拦截"是**两件事**：`block_forbidden_tiers` 拦的是
        LINEAR_N / WORSE 本身，与白名单无关。
        """
        guard = RedisPerfGuard(
            _perf(
                enabled=True,
                block_forbidden_tiers=True,
                toc_allowed_complexities=[],
            )
        )
        with structlog.testing.capture_logs() as logs:
            guard.check_operation_tier("op", RedisOperationCatalog.BIT_OP)
        assert not any(e["event"] == "perf.tier_not_allowed" for e in logs)

    def test_non_o1_is_warned(self) -> None:
        guard = RedisPerfGuard(_perf(enabled=True, warn_non_o1=True))
        with structlog.testing.capture_logs() as logs:
            guard.check_operation_tier("op", RedisOperationCatalog.HASH_FULL)
        assert any(e["event"] == "perf.non_o1_op" for e in logs)

    def test_o1_is_not_warned(self) -> None:
        guard = RedisPerfGuard(_perf(enabled=True, warn_non_o1=True))
        with structlog.testing.capture_logs() as logs:
            guard.check_operation_tier("op", RedisOperationCatalog.BIT_OP)
        assert not any(e["event"] == "perf.non_o1_op" for e in logs)

    def test_big_key_probe_hints_are_logged_for_non_o1(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, log_big_key_probe_hints=True)
        )
        with structlog.testing.capture_logs() as logs:
            guard.check_operation_tier("op", RedisOperationCatalog.HASH_FULL)
        hints = [e for e in logs if e["event"] == "perf.big_key_probe_hints"]
        assert hints and hints[0]["suggest"] == ["HLEN"]

    def test_big_key_probe_hints_are_skipped_for_o1(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, log_big_key_probe_hints=True)
        )
        with structlog.testing.capture_logs() as logs:
            guard.check_operation_tier("op", RedisOperationCatalog.BIT_OP)
        assert not any(
            e["event"] == "perf.big_key_probe_hints" for e in logs
        )

    def test_probe_hints_can_be_switched_off(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, log_big_key_probe_hints=False)
        )
        with structlog.testing.capture_logs() as logs:
            guard.check_operation_tier("op", RedisOperationCatalog.HASH_FULL)
        assert not any(
            e["event"] == "perf.big_key_probe_hints" for e in logs
        )

    def test_bare_tier_is_accepted(self) -> None:
        guard = RedisPerfGuard(_perf(enabled=True, warn_non_o1=True))
        with structlog.testing.capture_logs() as logs:
            guard.check_operation_tier("op", RedisComplexityTier.LINEAR_N)
        assert any(e["event"] == "perf.non_o1_op" for e in logs)


class TestLegacyComplexityEntry:
    def test_legacy_strings_map_to_tiers(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_forbidden_tiers=True)
        )
        with pytest.raises(ConfigurationError):
            guard.check_complexity("op", "O_N")

    def test_legacy_o1_passes(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_forbidden_tiers=True)
        )
        guard.check_complexity("op", "O1")

    def test_unknown_legacy_string_is_treated_as_script(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_forbidden_tiers=True)
        )
        guard.check_complexity("op", "who-knows")


# ── Guard: String payload shape ──────────────────────────────────


class TestGuardStringPayload:
    def test_disabled_is_a_noop(self) -> None:
        guard = RedisPerfGuard(_perf(enabled=False))
        guard.check_string_write_payload("op", "k", [1, 2, 3])

    def test_anti_pattern_switch_off_is_a_noop(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, warn_string_payload_anti_patterns=False)
        )
        guard.check_string_write_payload("op", "k", [1, 2, 3])

    def test_collection_blocks_when_configured(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_string_payload_violations=True)
        )
        with pytest.raises(ConfigurationError):
            guard.check_string_write_payload("op", "k", [1, 2, 3])

    def test_collection_only_logs_without_blocking(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_string_payload_violations=False)
        )
        with structlog.testing.capture_logs() as logs:
            guard.check_string_write_payload("op", "k", {"a": 1})
        events = [
            e for e in logs if e["event"] == "perf.string_payload_anti_pattern"
        ]
        assert events and events[0]["log_level"] == "error"

    def test_complex_object_warns_without_blocking(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_string_payload_violations=True)
        )
        with structlog.testing.capture_logs() as logs:
            guard.check_string_write_payload("op", "k", _Complex(1))
        events = [
            e for e in logs if e["event"] == "perf.string_payload_anti_pattern"
        ]
        assert events and events[0]["log_level"] == "warning"

    def test_scalar_produces_no_event(self) -> None:
        guard = RedisPerfGuard(_perf(enabled=True))
        with structlog.testing.capture_logs() as logs:
            guard.check_string_write_payload("op", "k", "plain")
        assert not any(
            e["event"] == "perf.string_payload_anti_pattern" for e in logs
        )

    def test_long_key_is_truncated_in_the_log(self) -> None:
        guard = RedisPerfGuard(_perf(enabled=True))
        long_key = "k" * 500
        with structlog.testing.capture_logs() as logs:
            guard.check_string_write_payload("op", long_key, [1])
        events = [
            e for e in logs if e["event"] == "perf.string_payload_anti_pattern"
        ]
        assert events and len(events[0]["key"]) < len(long_key)
        assert events[0]["key"].endswith("(500 chars)")


# ── Manager wiring ───────────────────────────────────────────────


class TestManagerWiring:
    """每个 manager 方法必须声明**哪一条** catalog 预设。"""

    def test_string_manager_tier_and_shape(self) -> None:
        spy = _SpyGuard()
        manager = RedisStringManager(_backend(), None, spy)  # type: ignore[arg-type]

        manager.get_map(["a"], str)
        manager.get_list(["a"], str)

        assert spy.tiers == [
            ("get_map", RedisOperationCatalog.STRING_MULTI_GET),
            ("get_list", RedisOperationCatalog.STRING_MULTI_GET),
        ]

    def test_string_manager_shape_check_uses_the_raw_value(self) -> None:
        """形状检查必须拿**序列化之前**的值——否则集合已经被压成 JSON。"""
        spy = _SpyGuard()
        manager = RedisStringManager(_backend(), None, spy)  # type: ignore[arg-type]
        payload = {"a": 1}

        manager.add_value("k", payload, 1000)

        assert spy.shapes == [("add_value", "k", payload)]
        assert spy.shapes[0][2] is payload

    def test_string_manager_shape_checks_on_all_four_write_paths(self) -> None:
        spy = _SpyGuard()
        manager = RedisStringManager(_backend(), None, spy)  # type: ignore[arg-type]

        manager.add_value("a", 1, 1000)
        manager.add_value_simple("b", 1)
        manager.add_value_if_absent("c", 1, 1000)
        manager.add_value_if_absent_simple("d", 1)

        assert [op for op, _, _ in spy.shapes] == [
            "add_value",
            "add_value_simple",
            "add_value_if_absent",
            "add_value_if_absent_simple",
        ]

    def test_collection_manager_set_tiers(self) -> None:
        spy = _SpyGuard()
        manager = RedisCollectionManager(_backend(), None, spy)  # type: ignore[arg-type]

        manager.get_from_set("k", str)
        manager.difference_from_set(["a"], str)
        manager.difference_and_store_from_set(["a"], "b")
        manager.batch_add_to_set({"k": {1}})

        assert spy.tiers == [
            ("get_from_set", RedisOperationCatalog.SET_MEMBERS),
            ("difference_from_set", RedisOperationCatalog.SET_COMBINE),
            (
                "difference_and_store_from_set",
                RedisOperationCatalog.SET_COMBINE,
            ),
            ("batch_add_to_set", RedisOperationCatalog.SET_COMBINE),
        ]

    def test_field_manager_hash_tiers(self) -> None:
        spy = _SpyGuard()
        manager = RedisFieldManager(_backend(), None, spy)  # type: ignore[arg-type]

        manager.get_all("k", str)
        manager.get_fields("k")

        assert spy.tiers == [
            ("get_all", RedisOperationCatalog.HASH_FULL),
            ("get_fields", RedisOperationCatalog.HASH_KEYS),
        ]

    def test_key_manager_keys_pattern_tier(self) -> None:
        spy = _SpyGuard()
        manager = RedisKeyManager(_backend(), None, spy)  # type: ignore[arg-type]

        manager.get_all_keys("user:*")

        assert spy.tiers == [
            ("get_all_keys", RedisOperationCatalog.KEYS_PATTERN),
        ]

    def test_ranking_manager_zset_tiers(self) -> None:
        spy = _SpyGuard()
        manager = RedisRankingManager(_backend(), None, spy)  # type: ignore[arg-type]

        manager.batch_add_to_zset({"k": {1}})
        manager.intersect_from_zset("k", ["o"], str)
        manager.union_from_zset("k", ["o"], str)
        manager.difference_from_zset("k", ["o"], str)
        manager.intersect_and_store_from_zset("k", ["o"], "d")
        manager.union_and_store_from_zset("k", ["o"], "d")
        manager.difference_and_store_from_zset("k", ["o"], "d")

        assert spy.tiers == [
            ("batch_add_to_zset", RedisOperationCatalog.ZSET_BATCH),
            ("intersect_from_zset", RedisOperationCatalog.ZSET_MULTI_KEY),
            ("union_from_zset", RedisOperationCatalog.ZSET_MULTI_KEY),
            ("difference_from_zset", RedisOperationCatalog.ZSET_MULTI_KEY),
            (
                "intersect_and_store_from_zset",
                RedisOperationCatalog.ZSET_MULTI_KEY,
            ),
            (
                "union_and_store_from_zset",
                RedisOperationCatalog.ZSET_MULTI_KEY,
            ),
            (
                "difference_and_store_from_zset",
                RedisOperationCatalog.ZSET_MULTI_KEY,
            ),
        ]

    def test_geo_manager_tiers(self) -> None:
        spy = _SpyGuard()
        manager = RedisGeoManager(_backend(), None, spy)  # type: ignore[arg-type]

        manager.add_geo("k", 1.0, 2.0, "m")
        manager.geo_dist("k", "a", "b")
        manager.geo_radius("k", 1.0, 2.0, 3.0)

        assert spy.tiers == [
            ("add_geo", RedisOperationCatalog.GEO_ADD),
            ("geo_dist", RedisOperationCatalog.GEO_DIST),
            ("geo_radius", RedisOperationCatalog.GEO_RADIUS),
        ]

    def test_bitmap_manager_tier(self) -> None:
        spy = _SpyGuard()
        manager = RedisBitmapManager(_backend(), None, spy)  # type: ignore[arg-type]

        manager.set_bit("k", 1, True)
        manager.get_bit("k", 1)

        assert spy.tiers == [
            ("set_bit", RedisOperationCatalog.BIT_OP),
            ("get_bit", RedisOperationCatalog.BIT_OP),
        ]

    def test_hyper_log_manager_tiers(self) -> None:
        spy = _SpyGuard()
        manager = RedisHyperLogManager(_backend(), None, spy)  # type: ignore[arg-type]

        manager.pf_add("k", "a")
        manager.pf_count("k")

        assert spy.tiers == [
            ("pf_add", RedisOperationCatalog.HLL_PFADD),
            ("pf_count", RedisOperationCatalog.HLL_PF_COUNT),
        ]

    def test_script_manager_tier(self) -> None:
        spy = _SpyGuard()
        manager = RedisScriptManager(_backend(), None, spy)  # type: ignore[arg-type]

        manager.eval("return 1", [], [], int)

        assert spy.tiers == [("eval", RedisOperationCatalog.LUA_EVAL)]

    def test_limiter_manager_tier(self) -> None:
        spy = _SpyGuard()
        manager = RedisLimiterManager(_backend(), None, spy)  # type: ignore[arg-type]

        manager.try_acquire("k", 1, 1)

        assert spy.tiers == [
            ("try_acquire", RedisOperationCatalog.LIMITER_LUA),
        ]


class TestBlockedTierReachesTheManager:
    """真实 guard 装进 manager：禁用档必须在访问 Redis 之前就被拦下。"""

    def test_linear_tier_blocks_before_touching_redis(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_forbidden_tiers=True)
        )
        backend = _backend()
        manager = RedisFieldManager(backend, None, guard)  # type: ignore[arg-type]

        with pytest.raises(ConfigurationError):
            manager.get_all("k", str)

        backend.raw_client.assert_not_called()

    def test_collection_write_is_blocked_by_the_shape_rule(self) -> None:
        guard = RedisPerfGuard(
            _perf(enabled=True, block_string_payload_violations=True)
        )
        backend = _backend()
        manager = RedisStringManager(backend, None, guard)  # type: ignore[arg-type]

        with pytest.raises(ConfigurationError):
            manager.add_value("k", [1, 2, 3], 1000)

        backend.raw_client.assert_not_called()
