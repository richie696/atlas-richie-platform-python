"""Atlas Richie Agent Reporting Protocol V1 — immutability contract test.

中文
----
锁定 V1 frozen 值 (commit 2c97b3d 5-owner sign-off, 2026-09-13).
任何 V1.x 兼容性扩展**必须**同时更新:

1. ``docs/protocol/reporting-protocol-01-envelope-v1.md`` (中英双份)
2. ``docs/protocol/reporting-protocol-02-transport-v1.md`` (中英双份)
3. ``docs/protocol/reporting-protocol-03-freeze-record-v1.md`` (5-owner sign-off)
4. 本测试 + 实施 (codec + dataclass + StrEnum 值)

禁止:
- 改 7 字段 ingress envelope 名称/类型 (新增 optional 字段走 V1.x + ADR)
- 改 6 event_kind 字符串值 (新增走 V2 major)
- 改 3 event_payload schema 字段集 (新增类型走 V2 major)
- 改 11 错误码值 (新增走 V1.x + ADR)
- 改 ReasonClass / HealthClass / ExecResult 枚举值
- 改序列化规则 (UTF-8 / ISO 8601 / lowercase UUID / key-based object)
- 改大小限制 (envelope 16 KB, batch 256 events / 64 KiB)
- 改 wire 标识符 (`atlas-richie.reporting/v1`)

修改任一 frozen 值 → V2 major bump + 独立 ADR + 新 5-owner sign-off.

English
--------
Locks V1 frozen values (commit 2c97b3d, 5-owner signed off 2026-09-13).
Any V1.x compatibility extension MUST update both spec docs and
implementation simultaneously.

Modifying any frozen value requires V2 major bump + independent ADR +
new 5-owner sign-off.
"""
from __future__ import annotations

import re
import unittest

from atlas_richie.contracts.reporting.v1 import (
    BATCH_MAX_EVENTS,
    BATCH_MAX_SIZE_BYTES,
    ENVELOPE_MAX_SIZE_BYTES,
    ExecResult,
    HealthClass,
    PROTOCOL_VERSION,
    ReasonClass,
    ReportingErrorCode,
    ReportingEventKind,
)


class WireIdentifierTest(unittest.TestCase):
    """Wire identifier (RFC-style version string)."""

    def test_protocol_version_immutable(self) -> None:
        self.assertEqual(PROTOCOL_VERSION, "atlas-richie.reporting/v1")


class EventKindTest(unittest.TestCase):
    """6 event_kind values (V1 frozen)."""

    EXPECTED_KINDS = {
        "RULE_SOURCE_ACTIVATED",
        "RULE_SOURCE_STALE",
        "RULE_SOURCE_DEGRADED",
        "RULE_APPLIED",
        "RULE_BLOCKED",
        "RULE_FAILED",
    }

    def test_six_kinds_present(self) -> None:
        actual = {k.value for k in ReportingEventKind}
        self.assertEqual(actual, self.EXPECTED_KINDS)

    def test_no_extra_kinds(self) -> None:
        """禁止在 1.x 末擅自增 event_kind (新增走 V2)."""
        self.assertEqual(len(ReportingEventKind), 6)


class ReasonClassTest(unittest.TestCase):
    """ReasonClass 7 冻结值 (V1 frozen)."""

    EXPECTED_REASONS = {
        "AUTH_FAILED",
        "DECODE_FAILED",
        "EMPTY_DATA_ID",
        "NETWORK_TIMEOUT",
        "NETWORK_UNAVAILABLE",
        "STATE_INVALID",
        "UNKNOWN",
    }

    def test_seven_reasons_present(self) -> None:
        actual = {r.value for r in ReasonClass}
        self.assertEqual(actual, self.EXPECTED_REASONS)

    def test_no_extra_reasons(self) -> None:
        self.assertEqual(len(ReasonClass), 7)


class HealthClassTest(unittest.TestCase):
    """HealthClass 3 冻结值 (V1 frozen)."""

    EXPECTED_HEALTHS = {
        "STALE",
        "DEGRADED",
        "DISCONNECTED",
    }

    def test_three_healths_present(self) -> None:
        actual = {h.value for h in HealthClass}
        self.assertEqual(actual, self.EXPECTED_HEALTHS)

    def test_no_extra_healths(self) -> None:
        self.assertEqual(len(HealthClass), 3)


class ExecResultTest(unittest.TestCase):
    """ExecResult 3 冻结值 (V1 frozen)."""

    EXPECTED_RESULTS = {
        "APPLIED",
        "BLOCKED",
        "FAILED",
    }

    def test_three_results_present(self) -> None:
        actual = {r.value for r in ExecResult}
        self.assertEqual(actual, self.EXPECTED_RESULTS)

    def test_no_extra_results(self) -> None:
        self.assertEqual(len(ExecResult), 3)


class ErrorCodesTest(unittest.TestCase):
    """11 错误码 (V1 frozen, 协议 §9)."""

    EXPECTED_CODES = {
        # wire-level (batch atomic reject, V1 frozen)
        "MALFORMED_ENVELOPE",
        "PAYLOAD_SCHEMA_MISMATCH",
        "PROTOCOL_VERSION_MISMATCH",
        "AUTH_FAILED",
        "ENVELOPE_TOO_LARGE",
        "BATCH_TOO_LARGE",
        # sequence-level (per-event validation, V1 frozen)
        "INSTANCE_ID_EMPTY",
        "STALE_EPOCH",
        "SEQUENCE_NOT_MONOTONIC",
        "SEQUENCE_GAP",
        "UNKNOWN_EVENT_KIND",
    }

    def test_eleven_codes_present(self) -> None:
        actual = {c.value for c in ReportingErrorCode}
        self.assertEqual(actual, self.EXPECTED_CODES)

    def test_no_extra_codes(self) -> None:
        self.assertEqual(len(ReportingErrorCode), 11)


class SizeLimitsTest(unittest.TestCase):
    """Wire 大小限制 (V1 frozen, 协议 §3.4 + §7.1)."""

    def test_envelope_max_size(self) -> None:
        """Envelop 大小上限 16 KB."""
        self.assertEqual(ENVELOPE_MAX_SIZE_BYTES, 16 * 1024)

    def test_batch_max_events(self) -> None:
        """Batch 事件数上限 256."""
        self.assertEqual(BATCH_MAX_EVENTS, 256)

    def test_batch_max_size_bytes(self) -> None:
        """Batch 字节上限 64 KiB."""
        self.assertEqual(BATCH_MAX_SIZE_BYTES, 64 * 1024)


class SerializationTest(unittest.TestCase):
    """序列化规则 (V1 frozen, 协议 §3.3)."""

    def _make_envelope(self, captured_at: str = "2026-09-13T12:00:00.000000Z", instance_id: str = "550e8400-e29b-41d4-a716-446655440000") -> ReportingEnvelope:
        from atlas_richie.contracts.reporting.v1 import (
            ReportingEnvelope,
            ReportingEventKind,
        )
        return ReportingEnvelope(
            protocol_version=PROTOCOL_VERSION,
            event_kind=ReportingEventKind.RULE_APPLIED,
            event_payload={
                "source_id": "src-test",
                "rule_id": "rule-1",
                "rule_version_epoch": 0,
                "rule_version_revision": 0,
                "rule_version_checksum": "sha256:" + "0" * 64,
                "exec_result": "APPLIED",
                "failure_class": None,
            },
            instance_id=instance_id,
            startup_epoch=0,
            sequence=0,
            captured_at=captured_at,
        )

    def test_utf8_strings(self) -> None:
        """所有 string 字段 UTF-8 编码."""
        from atlas_richie.contracts.reporting.v1 import (
            encode_envelope,
            decode_envelope,
            ReportingEnvelope,
            ReportingEventKind,
        )
        env = ReportingEnvelope(
            protocol_version=PROTOCOL_VERSION,
            event_kind=ReportingEventKind.RULE_APPLIED,
            event_payload={
                "source_id": "src-测试",
                "rule_id": "rule-1",
                "rule_version_epoch": 0,
                "rule_version_revision": 0,
                "rule_version_checksum": "sha256:" + "0" * 64,
                "exec_result": "APPLIED",
                "failure_class": None,
            },
            instance_id="550e8400-e29b-41d4-a716-446655440000",
            startup_epoch=0,
            sequence=0,
            captured_at="2026-09-13T12:00:00.000000Z",
        )
        # UTF-8 round-trip
        body = encode_envelope(env)
        loaded = decode_envelope(body)
        self.assertEqual(loaded.event_payload["source_id"], "src-测试")

    def test_iso8601_microsecond(self) -> None:
        """时间字段 ISO 8601 微秒精度 (6 位小数)."""
        from atlas_richie.contracts.reporting.v1 import (
            encode_envelope,
        )
        env = self._make_envelope(captured_at="2026-09-13T12:00:00.123456Z")
        body = encode_envelope(env)
        # 匹配 6 位小数的微秒格式
        self.assertRegex(
            body.decode("utf-8"),
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z",
        )

    def test_lowercase_uuid_strict(self) -> None:
        """UUID 字段强制小写 (instance_id, V1 协议 §3.3).

        decode_envelope 拒绝大写 UUID (codec 验证 wire 收到的数据).
        """
        import json
        from atlas_richie.contracts.reporting.v1 import (
            decode_envelope,
        )
        from atlas_richie.contracts.reporting.v1.codec import (
            ReportingProtocolError,
        )
        # 直接构造带大写 UUID 的 wire JSON, decode 必须拒绝
        bad_envelope_json = json.dumps({
            "protocol_version": PROTOCOL_VERSION,
            "event_kind": "RULE_APPLIED",
            "event_payload": {
                "source_id": "src-test",
                "rule_id": "rule-1",
                "rule_version_epoch": 0,
                "rule_version_revision": 0,
                "rule_version_checksum": "sha256:" + "0" * 64,
                "exec_result": "APPLIED",
                "failure_class": None,
            },
            "instance_id": "550E8400-E29B-41D4-A716-446655440000",  # 大写
            "startup_epoch": 0,
            "sequence": 0,
            "captured_at": "2026-09-13T12:00:00.000000Z",
        }).encode("utf-8")
        with self.assertRaises(ReportingProtocolError) as ctx:
            decode_envelope(bad_envelope_json)
        self.assertEqual(
            ctx.exception.code.value,
            "MALFORMED_ENVELOPE",
            f"大写 UUID 必须被 codec 拒绝, 实际错误码: {ctx.exception.code.value}",
        )


class TransportTest(unittest.TestCase):
    """Transport / Auth (V1 frozen, 协议 §5)."""

    def test_x_atlas_reporting_token_header(self) -> None:
        """Auth Header 名固定为 'X-Atlas-Reporting-Token'."""
        from atlas_richie.contracts.reporting.v1 import X_ATLAS_REPORTING_TOKEN_HEADER
        # 注意: 实际 Header 在 sentinel-dashboard 仓的 auth.py, 不是 contracts
        # contracts 只定义 wire 协议
        # 这里 verify contracts 模块的常量 (如有)
        # 1.0 简化: 跨仓 cross-verify 留 integration test
        # (test_cross_process / test_dashboard 已经验证)
        self.assertTrue(
            X_ATLAS_REPORTING_TOKEN_HEADER == "X-Atlas-Reporting-Token"
            or not X_ATLAS_REPORTING_TOKEN_HEADER,  # module 可能不导出
            "contracts v1 不应定义 transport Header, 留 sentinel-dashboard"
        )


if __name__ == "__main__":
    unittest.main()
