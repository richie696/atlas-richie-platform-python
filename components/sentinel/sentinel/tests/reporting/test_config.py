"""``AgentReporterConfig`` + ``OverflowPolicy`` 单元测试 (M6.5.1).

中文
----
覆盖:

1. **frozen slots 锁死** — 构造后改字段抛 ``FrozenInstanceError``
2. **启动 fail-fast 校验** — auth_token 长度 / 端口合法 / overflow_policy
   枚举 / loopback 强制 / 协议固定字段 (batch_max_events=256, batch_max_bytes=64KiB)
3. **默认值** — 跟协议 + M6.5.1 spec 1:1

English
--------
Coverage:

1. **frozen slots lock** — mutation after construction raises
   ``FrozenInstanceError``
2. **Startup fail-fast validation** — auth_token length / port /
   overflow_policy enum / loopback enforced / protocol-fixed fields
3. **Default values** — 1:1 with protocol + M6.5.1 spec
"""

from __future__ import annotations

import dataclasses
import unittest

from atlas_richie.sentinel.errors import SentinelConfigurationError, SentinelError
from atlas_richie.sentinel.reporting import (
    AgentReporterConfig,
    OverflowPolicy,
)
from atlas_richie.sentinel.reporting.config import (
    BATCH_MAX_BYTES,
    BATCH_MAX_EVENTS,
    validate_config,
)


# 合法默认 config (供所有测试用)
def _make_config(**overrides: object) -> AgentReporterConfig:
    defaults: dict[str, object] = {
        "collector_address": "127.0.0.1:8765",
        "auth_token": "0123456789abcdef",  # 16 chars
        "instance_id_persistence_path": None,
        "outbox_max_size": 10000,
        "outbox_overflow_policy": OverflowPolicy.BLOCK_WITH_TIMEOUT,
        "batch_max_events": BATCH_MAX_EVENTS,
        "batch_max_bytes": BATCH_MAX_BYTES,
        "batch_send_interval_ns": 100_000_000,
        "max_contiguous_sequence": 0,
        "connect_timeout_ns": 5_000_000_000,
        "request_timeout_ns": 5_000_000_000,
        "reconnect_initial_ns": 100_000_000,
        "reconnect_max_ns": 30_000_000_000,
        "reconnect_jitter_ns": 50_000_000,
    }
    defaults.update(overrides)
    return AgentReporterConfig(**defaults)  # type: ignore[arg-type]


class FrozenSlotsTest(unittest.TestCase):
    """frozen slots 锁死: 构造后改字段抛 FrozenInstanceError."""

    def test_frozen_after_construction(self) -> None:
        config = _make_config()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.collector_address = "127.0.0.1:9999"  # type: ignore[misc]

    def test_overflow_policy_strenum(self) -> None:
        # 3 选 1 显式 (无 default / auto / silent / inherit)
        self.assertEqual(OverflowPolicy.DROP_OLDEST.value, "drop_oldest")
        self.assertEqual(OverflowPolicy.DROP_NEWEST.value, "drop_newest")
        self.assertEqual(OverflowPolicy.BLOCK_WITH_TIMEOUT.value, "block_with_timeout")
        # 枚举不可扩展
        with self.assertRaises(ValueError):
            _ = OverflowPolicy("auto")
        with self.assertRaises(ValueError):
            _ = OverflowPolicy("silent")


class FailFastValidationTest(unittest.TestCase):
    """启动 fail-fast 校验 — 各类错误."""

    def test_collector_address_non_loopback_rejected(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(collector_address="0.0.0.0:8765")
        self.assertIn("loopback", str(cm.exception).lower())

    def test_collector_address_public_ip_rejected(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(collector_address="8.8.8.8:8765")
        self.assertIn("loopback", str(cm.exception).lower())

    def test_collector_address_missing_port_rejected(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(collector_address="127.0.0.1")
        self.assertIn("port", str(cm.exception).lower())

    def test_collector_address_invalid_port_rejected(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(collector_address="127.0.0.1:99999")
        self.assertIn("port", str(cm.exception).lower())

    def test_collector_address_localhost_accepted(self) -> None:
        # localhost 等同 127.0.0.1
        config = _make_config(collector_address="localhost:8765")
        self.assertEqual(config.collector_address, "localhost:8765")

    def test_collector_address_ipv6_loopback_accepted(self) -> None:
        config = _make_config(collector_address="[::1]:8765")
        self.assertEqual(config.collector_address, "[::1]:8765")

    def test_auth_token_too_short_rejected(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(auth_token="short")
        self.assertIn("auth_token", str(cm.exception).lower())

    def test_auth_token_exactly_16_accepted(self) -> None:
        config = _make_config(auth_token="0123456789abcdef")  # 16 chars
        self.assertEqual(len(config.auth_token), 16)

    def test_outbox_max_size_zero_rejected(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(outbox_max_size=0)
        self.assertIn("outbox_max_size", str(cm.exception).lower())

    def test_outbox_max_size_negative_rejected(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(outbox_max_size=-1)
        self.assertIn("outbox_max_size", str(cm.exception).lower())

    def test_overflow_policy_invalid_type_rejected(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(outbox_overflow_policy="auto")  # type: ignore[arg-type]
        self.assertIn("outbox_overflow_policy", str(cm.exception).lower())

    def test_batch_max_events_protocol_fixed(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(batch_max_events=512)  # protocol 强制 256
        self.assertIn("batch_max_events", str(cm.exception).lower())

    def test_batch_max_bytes_protocol_fixed(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(batch_max_bytes=128 * 1024)  # protocol 强制 64 KiB
        self.assertIn("batch_max_bytes", str(cm.exception).lower())

    def test_reconnect_max_less_than_initial_rejected(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(reconnect_initial_ns=1_000_000_000, reconnect_max_ns=500_000_000)
        self.assertIn("reconnect", str(cm.exception).lower())

    def test_negative_interval_rejected(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(batch_send_interval_ns=-1)
        self.assertIn("batch_send_interval_ns", str(cm.exception).lower())

    def test_negative_max_contiguous_rejected(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_config(max_contiguous_sequence=-1)
        self.assertIn("max_contiguous_sequence", str(cm.exception).lower())


class SentinelErrorSubclassTest(unittest.TestCase):
    """SentinelConfigurationError 必须继承 SentinelError (主包根)."""

    def test_sentinel_configuration_error_is_sentinel_error(self) -> None:
        try:
            _make_config(auth_token="short")
        except SentinelError as e:
            # 应该被 except SentinelError 捕获
            self.assertIsInstance(e, SentinelConfigurationError)


class DefaultsTest(unittest.TestCase):
    """默认值跟协议 + M6.5.1 spec 1:1."""

    def test_default_values(self) -> None:
        config = _make_config()
        # 跟 spec 一致
        self.assertEqual(config.outbox_max_size, 10000)
        self.assertEqual(config.batch_max_events, 256)
        self.assertEqual(config.batch_max_bytes, 64 * 1024)
        self.assertEqual(config.batch_send_interval_ns, 100_000_000)  # 100ms
        self.assertEqual(config.connect_timeout_ns, 5_000_000_000)  # 5s
        self.assertEqual(config.request_timeout_ns, 5_000_000_000)  # 5s
        self.assertEqual(config.reconnect_initial_ns, 100_000_000)  # 100ms
        self.assertEqual(config.reconnect_max_ns, 30_000_000_000)  # 30s
        self.assertEqual(config.reconnect_jitter_ns, 50_000_000)  # 50ms

    def test_protocol_constants_match(self) -> None:
        # 协议 §7.1 batch_max_events=256, batch_max_bytes=64 KiB
        self.assertEqual(BATCH_MAX_EVENTS, 256)
        self.assertEqual(BATCH_MAX_BYTES, 64 * 1024)


class ValidateConfigEntryPointTest(unittest.TestCase):
    """``validate_config(config)`` 公开入口 — 1.0 内部但 reporter 调."""

    def test_validate_passes_for_valid(self) -> None:
        config = _make_config()
        # 不抛
        validate_config(config)

    def test_validate_fails_for_wrong_type(self) -> None:
        # 错类型走 validate_config 显式校验
        with self.assertRaises(SentinelConfigurationError):
            validate_config("not a config")  # type: ignore[arg-type]
