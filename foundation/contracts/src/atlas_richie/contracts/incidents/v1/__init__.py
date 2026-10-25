"""Sentinel Incident Event Protocol V1 values and strict JSON codec."""

from .incident_event import (
    INCIDENT_EVENT_PROTOCOL_V1,
    MAX_INCIDENT_EVENT_BODY_BYTES,
    IncidentEventReceiptV1,
    IncidentEventV1,
    IncidentFactKind,
    IncidentProtocolError,
    IncidentProtocolErrorCode,
    IncidentSeverity,
    ResourcePressureFact,
    ResourcePressureMetric,
    ResponseTimeFact,
    decode_incident_event,
    decode_incident_receipt,
    encode_incident_event,
    encode_incident_receipt,
)

__all__ = [
    "INCIDENT_EVENT_PROTOCOL_V1",
    "MAX_INCIDENT_EVENT_BODY_BYTES",
    "IncidentEventReceiptV1",
    "IncidentEventV1",
    "IncidentFactKind",
    "IncidentProtocolError",
    "IncidentProtocolErrorCode",
    "IncidentSeverity",
    "ResourcePressureFact",
    "ResourcePressureMetric",
    "ResponseTimeFact",
    "decode_incident_event",
    "decode_incident_receipt",
    "encode_incident_event",
    "encode_incident_receipt",
]
