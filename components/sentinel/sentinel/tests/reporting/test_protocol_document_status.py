"""Guard the separation between the frozen envelope and draft transport docs."""

from pathlib import Path


SENTINEL_ROOT = Path(__file__).resolve().parents[3]
PROTOCOLS_ROOT = SENTINEL_ROOT / "docs" / "protocol"


def test_reporting_freeze_records_only_freeze_the_envelope_schema() -> None:
    english = (PROTOCOLS_ROOT / "reporting-protocol-03-freeze-record-v1.md").read_text(
        encoding="utf-8"
    )
    chinese = (PROTOCOLS_ROOT / "上报协议-03-freeze-v1.md").read_text(encoding="utf-8")
    english_transport = (
        PROTOCOLS_ROOT / "reporting-protocol-02-transport-v1.md"
    ).read_text(encoding="utf-8")
    chinese_transport = (
        PROTOCOLS_ROOT / "上报协议-02-transport-v1.md"
    ).read_text(encoding="utf-8")
    planning = (SENTINEL_ROOT / "docs" / "process" / "PLANNING.md").read_text(
        encoding="utf-8"
    )

    assert "1.0 Envelope Schema (Frozen)" in english
    assert "transport remains a draft" in english
    assert "Envelope schema 已冻结" in chinese
    assert "transport 仍为草案" in chinese
    assert "Status**: Pending transport freeze and owner sign-off" in english_transport
    assert "Status**: 待 transport 冻结与 owner 签字" in chinese_transport
    assert "不是当前可证事实" in planning

    m651 = " ".join(
        planning.split("- [x] M6.5.1", maxsplit=1)[1]
        .split("- [x] M6.5.2", maxsplit=1)[0]
        .split()
    )
    assert "仅冻结 V1 event envelope schema" in m651
    assert "transport 仍待 owner 签字" in m651
    assert "冻结 V1 schema、 transport 基线" not in m651


def test_design_does_not_describe_unfrozen_transport_or_metrics_as_v1_contract() -> None:
    design = (SENTINEL_ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")

    assert "当前唯一冻结的跨语言事实是 V1 **事件 envelope**" in design
    assert "transport、认证、batch/ack" in design
    assert "transport owner 签字" in design
    assert "不包含通用指标或原始 RT 序列" in design
    assert "每个批次至少包含 protocol version" not in design
    assert "它不满足" in design
    assert "V1 envelope 冻结不授权跨主机生产上报" in design
    assert "远程生产 Reporter/Collector 链路必须保持禁用" in design


def test_python_reporting_models_distinguish_frozen_envelope_from_draft_transport() -> None:
    source_root = (
        SENTINEL_ROOT.parents[1]
        / "foundation"
        / "contracts"
        / "src"
        / "atlas_richie"
        / "contracts"
        / "reporting"
        / "v1"
    )
    event_kind = (source_root / "event_kind.py").read_text(encoding="utf-8")
    envelope = (source_root / "envelope.py").read_text(encoding="utf-8")
    payloads = (source_root / "payloads.py").read_text(encoding="utf-8")
    batch = (source_root / "batch.py").read_text(encoding="utf-8")
    error_codes = (source_root / "error_codes.py").read_text(encoding="utf-8")

    assert "已由 5-owner sign-off 冻结" in event_kind
    assert "frozen ingress envelope" in envelope
    assert "V1 per-kind payload schemas 已冻结" in payloads
    assert "pending transport draft" in batch
    assert "belongs to the pending transport draft" in error_codes
    assert "DRAFT, 待 5-owner sign-off" not in event_kind + envelope + payloads

