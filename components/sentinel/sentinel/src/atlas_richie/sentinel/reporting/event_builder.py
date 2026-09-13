"""Atlas Richie Sentinel — Agent Reporting V1 event builder (M6.5.3 + M6.5.4).

中文
----
``event_builder`` 内部 (Mavis 治理: 私有) — 把主包内部 fact 翻译成
V1 7 字段 envelope + per-kind payload.

3 套映射:

- **Rule source activation** (M6.1 frozen) →
  :class:`ReportingEventKind.RULE_SOURCE_ACTIVATED`
- **Source health 变化** (从 ``RuleSourceSupervisor`` polling) →
  :class:`ReportingEventKind.RULE_SOURCE_STALE` /
  :class:`ReportingEventKind.RULE_SOURCE_DEGRADED`
- **Slot chain 执行结果** (M2 outcomes) →
  :class:`ReportingEventKind.RULE_APPLIED` / ``_BLOCKED`` / ``_FAILED``

所有 per-kind payload 字段 (3 rule_version_* 成组可选 / failure_class
仅 FAILED 必填) 严格走 ``foundation/contracts/reporting/v1/codec.py``
的 ``validate_payload`` 校验, **不**重复实现 wire schema.

Wire 字段值 (FROZEN 2026-09-13, 5-owner 签收完成, 不变):

- ``event_kind``: 大写 (跟 V1 6 个 ReportingEventKind value 一致)
- ``health_class``: 大写 STALE / DEGRADED / DISCONNECTED
- ``exec_result``: 大写 APPLIED / BLOCKED / FAILED
- ``reason_class``: 大写 (ReasonClass 7 冻结值)

English
--------
``event_builder`` is internal (Mavis governance: private) — it
translates the main package's internal facts into the V1 7-field
envelope + per-kind payload.

Three mappings:

- **Rule source activation** (M6.1 frozen) →
  :class:`ReportingEventKind.RULE_SOURCE_ACTIVATED`
- **Source health change** (from ``RuleSourceSupervisor`` polling) →
  :class:`ReportingEventKind.RULE_SOURCE_STALE` /
  :class:`ReportingEventKind.RULE_SOURCE_DEGRADED`
- **Slot chain execution result** (M2 outcomes) →
  :class:`ReportingEventKind.RULE_APPLIED`` / ``_BLOCKED`` / ``_FAILED``

All per-kind payload fields (3 ``rule_version_*`` group optional /
``failure_class`` FAILED-only) are strictly validated via
``foundation/contracts/reporting/v1/codec.py``'s ``validate_payload``;
**no** duplicate wire-schema implementation.

Wire field values (FROZEN 2026-09-13, 5-owner signed off, immutable):

- ``event_kind``: uppercase (matches V1 6 ReportingEventKind values)
- ``health_class``: uppercase STALE / DEGRADED / DISCONNECTED
- ``exec_result``: uppercase APPLIED / BLOCKED / FAILED
- ``reason_class``: uppercase (ReasonClass 7 frozen values)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    ExecResult,
    HealthClass,
    ReasonClass,
    ReportingEnvelope,
    ReportingEventKind,
    validate_payload,
)

from ._identity import ReporterIdentity


# 协议冻结 7 值; 3 值; 3 值 (跟 codec 严格一致).
_VALID_HEALTH_CLASSES: Final[frozenset[str]] = frozenset(c.value for c in HealthClass)
_VALID_EXEC_RESULTS: Final[frozenset[str]] = frozenset(c.value for c in ExecResult)
_VALID_REASON_CLASSES: Final[frozenset[str]] = frozenset(c.value for c in ReasonClass)


# ---------------------------------------------------------------------------
# Internal fact DTOs (Mavis 治理: 私有, 不导出 __all__)
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class RuleSourceActivationFact:
    """``RuleSourceActivation`` fact (M6.1.0b frozen) 内部表示.

    中文
    ----
    字段: source_id + version (epoch/revision/checksum). 不含时间戳
    (M6.5.7 envelope 提供 captured_at).

    注意: activation payload 只含 ``source_id`` + version triplet
    (4 字段, 协议 §5.1); 不含 previous_source_id / reason / priority.
    这跟 M6.1 ``RuleSourceActivation`` fact 内部表示不同 — fact 是
    "激活事件触发器" (含切换原因), wire payload 是 "切换后的稳定状态"
    (只含 source 标识 + version).

    English
    --------
    Fields: source_id + version (epoch/revision/checksum). No timestamp
    (M6.5.7 envelope provides captured_at).

    Note: activation payload only has ``source_id`` + version triplet
    (4 fields, protocol §5.1); no previous_source_id / reason /
    priority. This differs from the internal M6.1 ``RuleSourceActivation``
    fact — the fact is the "trigger for activation event" (includes
    switch reason), while the wire payload is the "stable state after
    switch" (only source identity + version).
    """

    source_id: str
    epoch: int
    revision: int
    checksum: str  # "sha256:..." 64 hex


@dataclass(slots=True, frozen=True)
class SourceHealthFact:
    """Rule source health 变化 fact (内部).

    中文
    ----
    ``health_class`` ∈ HealthClass (STALE / DEGRADED / DISCONNECTED,
    协议 §5.2 大写). ``epoch`` / ``revision`` / ``checksum`` 3 字段
    成组可选 — 首次加载失败 / 无 last-known-good 场景全部省略.

    ``reason_class`` ∈ ReasonClass 7 冻结值 (协议 §5.4 必填).

    English
    --------
    ``health_class`` ∈ HealthClass (STALE / DEGRADED / DISCONNECTED,
    protocol §5.2 uppercase). ``epoch`` / ``revision`` / ``checksum``
    3-tuple group-optional — all three are omitted in the first-load-
    failure / no-last-known-good scenario.

    ``reason_class`` ∈ ReasonClass 7 frozen values (protocol §5.4 required).
    """

    source_id: str
    health_class: str  # HealthClass enum value (UPPERCASE)
    reason_class: str  # ReasonClass enum value (UPPERCASE)
    epoch: int | None
    revision: int | None
    checksum: str | None  # "sha256:..." 64 hex 或 None
    reason_message: str  # ≤ 64 chars (协议 REASON_MESSAGE_MAX_LEN)


@dataclass(slots=True, frozen=True)
class SlotExecFact:
    """Slot chain 单次执行 fact (M2 outcomes 内部表示).

    中文
    ----
    ``exec_result`` ∈ ExecResult (APPLIED / BLOCKED / FAILED, 协议
    §5.3 大写). 协议 §5.3 强制: failure_class 仅 FAILED 必填
    (ReasonClass 7 值), 其它结果必须 None.

    业务执行事件 payload (协议 §5.3) 7 字段: source_id, rule_id,
    rule_version_*, exec_result, failure_class.

    English
    --------
    ``exec_result`` ∈ ExecResult (APPLIED / BLOCKED / FAILED,
    protocol §5.3 uppercase). Protocol §5.3 mandates: failure_class
    is required for FAILED only (one of 7 ReasonClass values), must
    be None otherwise.

    Business exec event payload (protocol §5.3) 7 fields: source_id,
    rule_id, rule_version_*, exec_result, failure_class.
    """

    source_id: str
    rule_id: str
    exec_result: str  # ExecResult enum value (UPPERCASE)
    failure_class: str | None  # ReasonClass enum value (UPPERCASE) 或 None
    epoch: int
    revision: int
    checksum: str  # "sha256:..." 64 hex


# ---------------------------------------------------------------------------
# Event builder 内部接口 (Reporter 内 Outbox 调用)
# ---------------------------------------------------------------------------


def _now_iso_utc_micro() -> str:
    """ISO 8601 UTC microsecond, 跟 codec 严格 regex 一致 (无 +00:00)."""
    return (
        datetime.now(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.%f")
    ) + "Z"


def _check_health_class(value: str) -> None:
    if value not in _VALID_HEALTH_CLASSES:
        raise ValueError(
            f"health_class must be one of {sorted(_VALID_HEALTH_CLASSES)}, "
            f"got {value!r}"
        )


def _check_exec_result(value: str) -> None:
    if value not in _VALID_EXEC_RESULTS:
        raise ValueError(
            f"exec_result must be one of {sorted(_VALID_EXEC_RESULTS)}, "
            f"got {value!r}"
        )


def _check_reason_class(value: str | None, exec_result: str) -> None:
    if exec_result == ExecResult.FAILED.value:
        if value is None:
            raise ValueError(
                "exec_result=FAILED requires failure_class not None (协议 §5.3)"
            )
        if value not in _VALID_REASON_CLASSES:
            raise ValueError(
                f"failure_class must be ReasonClass ({sorted(_VALID_REASON_CLASSES)}) "
                f"when exec_result=FAILED, got {value!r}"
            )
    else:  # APPLIED / BLOCKED
        if value is not None:
            raise ValueError(
                f"exec_result={exec_result} requires failure_class=None "
                f"(协议 §5.3), got {value!r}"
            )


def _build_envelope(
    *,
    event_kind: ReportingEventKind,
    event_payload: dict[str, Any],
    identity: ReporterIdentity,
    sequence: int,
) -> ReportingEnvelope:
    """构造 7 字段 envelope, 调 ``validate_payload`` 锁 schema.

    Raises:
        ReportingProtocolError: 字段不合法 (由 ``validate_payload`` 抛)
    """
    # 先在构造前校验 payload schema (frozen dataclass __init__ 不会再校验)
    validate_payload(event_kind.value, event_payload)
    return ReportingEnvelope(
        protocol_version=PROTOCOL_VERSION,
        event_kind=event_kind.value,
        event_payload=event_payload,
        instance_id=identity.instance_id,
        startup_epoch=identity.startup_epoch,
        sequence=sequence,
        captured_at=_now_iso_utc_micro(),
    )


def build_rule_source_activated(
    *,
    identity: ReporterIdentity,
    sequence: int,
    fact: RuleSourceActivationFact,
) -> ReportingEnvelope:
    """``RuleSourceActivation`` fact → ``RULE_SOURCE_ACTIVATED`` envelope.

    中文
    ----
    payload 字段 (协议 §5.1, 严格 4 字段):
    - ``source_id``
    - ``rule_version_epoch`` / ``rule_version_revision`` /
      ``rule_version_checksum`` (3 字段必填, 不成组可选)

    English
    --------
    Payload fields (protocol §5.1, strict 4 fields):
    - ``source_id``
    - ``rule_version_epoch`` / ``rule_version_revision`` /
      ``rule_version_checksum`` (3 fields required, NOT group-optional)
    """
    payload: dict[str, Any] = {
        "source_id": fact.source_id,
        "rule_version_epoch": fact.epoch,
        "rule_version_revision": fact.revision,
        "rule_version_checksum": fact.checksum,
    }
    return _build_envelope(
        event_kind=ReportingEventKind.RULE_SOURCE_ACTIVATED,
        event_payload=payload,
        identity=identity,
        sequence=sequence,
    )


def build_source_stale(
    *,
    identity: ReporterIdentity,
    sequence: int,
    fact: SourceHealthFact,
) -> ReportingEnvelope:
    """``Source health STALE`` → ``RULE_SOURCE_STALE`` envelope."""
    _check_health_class(fact.health_class)
    payload: dict[str, Any] = {
        "source_id": fact.source_id,
        "health_class": fact.health_class,
        "reason_class": fact.reason_class,
    }
    if fact.epoch is not None and fact.revision is not None and fact.checksum is not None:
        payload["rule_version_epoch"] = fact.epoch
        payload["rule_version_revision"] = fact.revision
        payload["rule_version_checksum"] = fact.checksum
    if fact.reason_message:
        payload["reason_message"] = fact.reason_message
    return _build_envelope(
        event_kind=ReportingEventKind.RULE_SOURCE_STALE,
        event_payload=payload,
        identity=identity,
        sequence=sequence,
    )


def build_source_degraded(
    *,
    identity: ReporterIdentity,
    sequence: int,
    fact: SourceHealthFact,
) -> ReportingEnvelope:
    """``Source health DEGRADED`` → ``RULE_SOURCE_DEGRADED`` envelope."""
    _check_health_class(fact.health_class)
    payload: dict[str, Any] = {
        "source_id": fact.source_id,
        "health_class": fact.health_class,
        "reason_class": fact.reason_class,
    }
    if fact.epoch is not None and fact.revision is not None and fact.checksum is not None:
        payload["rule_version_epoch"] = fact.epoch
        payload["rule_version_revision"] = fact.revision
        payload["rule_version_checksum"] = fact.checksum
    if fact.reason_message:
        payload["reason_message"] = fact.reason_message
    return _build_envelope(
        event_kind=ReportingEventKind.RULE_SOURCE_DEGRADED,
        event_payload=payload,
        identity=identity,
        sequence=sequence,
    )


def build_rule_applied(
    *,
    identity: ReporterIdentity,
    sequence: int,
    fact: SlotExecFact,
) -> ReportingEnvelope:
    """``Slot exec APPLIED`` → ``RULE_APPLIED`` envelope (failure_class=None)."""
    _check_exec_result(fact.exec_result)
    _check_reason_class(fact.failure_class, fact.exec_result)
    payload: dict[str, Any] = {
        "source_id": fact.source_id,
        "rule_id": fact.rule_id,
        "exec_result": fact.exec_result,
        "failure_class": fact.failure_class,
        "rule_version_epoch": fact.epoch,
        "rule_version_revision": fact.revision,
        "rule_version_checksum": fact.checksum,
    }
    return _build_envelope(
        event_kind=ReportingEventKind.RULE_APPLIED,
        event_payload=payload,
        identity=identity,
        sequence=sequence,
    )


def build_rule_blocked(
    *,
    identity: ReporterIdentity,
    sequence: int,
    fact: SlotExecFact,
) -> ReportingEnvelope:
    """``Slot exec BLOCKED`` → ``RULE_BLOCKED`` envelope (failure_class=None)."""
    _check_exec_result(fact.exec_result)
    _check_reason_class(fact.failure_class, fact.exec_result)
    payload: dict[str, Any] = {
        "source_id": fact.source_id,
        "rule_id": fact.rule_id,
        "exec_result": fact.exec_result,
        "failure_class": fact.failure_class,
        "rule_version_epoch": fact.epoch,
        "rule_version_revision": fact.revision,
        "rule_version_checksum": fact.checksum,
    }
    return _build_envelope(
        event_kind=ReportingEventKind.RULE_BLOCKED,
        event_payload=payload,
        identity=identity,
        sequence=sequence,
    )


def build_rule_failed(
    *,
    identity: ReporterIdentity,
    sequence: int,
    fact: SlotExecFact,
) -> ReportingEnvelope:
    """``Slot exec FAILED`` → ``RULE_FAILED`` envelope (failure_class 必填)."""
    _check_exec_result(fact.exec_result)
    _check_reason_class(fact.failure_class, fact.exec_result)
    payload: dict[str, Any] = {
        "source_id": fact.source_id,
        "rule_id": fact.rule_id,
        "exec_result": fact.exec_result,
        "failure_class": fact.failure_class,
        "rule_version_epoch": fact.epoch,
        "rule_version_revision": fact.revision,
        "rule_version_checksum": fact.checksum,
    }
    return _build_envelope(
        event_kind=ReportingEventKind.RULE_FAILED,
        event_payload=payload,
        identity=identity,
        sequence=sequence,
    )


__all__ = [
    "RuleSourceActivationFact",
    "SlotExecFact",
    "SourceHealthFact",
    "build_rule_applied",
    "build_rule_blocked",
    "build_rule_failed",
    "build_rule_source_activated",
    "build_source_degraded",
    "build_source_stale",
]
