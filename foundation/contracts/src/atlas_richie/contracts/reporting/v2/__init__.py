"""Frozen Atlas Richie Metrics Reporting Protocol V2 contract.

This package owns only immutable wire values and strict serialization. It does
not provide authentication, transport, persistence, or runtime composition.
Reporting V1 remains a separate, unchanged protocol.
"""

from .error_codes import MetricsV2ErrorCode
from .metrics_v2 import (
    HTTP_REQUEST_DURATION_BOUNDARIES_NS,
    MAX_DECIMAL_INTEGER_DIGITS,
    MAX_HISTOGRAM_BOUNDARIES,
    MAX_IDENTIFIER_LENGTH,
    MAX_SAFE_INTEGER,
    CounterName,
    CounterRateCalculation,
    CounterRateState,
    CounterReading,
    CumulativeDeltaState,
    GaugeName,
    GaugeQuality,
    GaugeReading,
    HistogramDelta,
    HistogramDeltaCalculation,
    HistogramName,
    HistogramReading,
    MetricsSnapshot,
    calculate_counter_rate,
    calculate_histogram_delta,
)
from .metrics_v2_codec import (
    METRICS_V2_CADENCE_SECONDS,
    METRICS_V2_MAX_ACTIVE_RESOURCES,
    METRICS_V2_MAX_RECORDS,
    METRICS_V2_MAX_SIZE_BYTES,
    METRICS_V2_PROTOCOL,
    MetricsV2ProtocolError,
    decode_metrics_snapshot,
    encode_metrics_snapshot,
)
from .receipt import (
    MetricsReceipt,
    MetricsReceiptProtocolError,
    decode_metrics_receipt,
    encode_metrics_receipt,
    receipt_for_body,
)

__all__ = [
    "HTTP_REQUEST_DURATION_BOUNDARIES_NS",
    "MAX_DECIMAL_INTEGER_DIGITS",
    "MAX_HISTOGRAM_BOUNDARIES",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_SAFE_INTEGER",
    "METRICS_V2_CADENCE_SECONDS",
    "METRICS_V2_MAX_ACTIVE_RESOURCES",
    "METRICS_V2_MAX_RECORDS",
    "METRICS_V2_MAX_SIZE_BYTES",
    "METRICS_V2_PROTOCOL",
    "CounterName",
    "CounterRateCalculation",
    "CounterRateState",
    "CounterReading",
    "CumulativeDeltaState",
    "GaugeName",
    "GaugeQuality",
    "GaugeReading",
    "HistogramDelta",
    "HistogramDeltaCalculation",
    "HistogramName",
    "HistogramReading",
    "MetricsReceipt",
    "MetricsReceiptProtocolError",
    "MetricsSnapshot",
    "MetricsV2ErrorCode",
    "MetricsV2ProtocolError",
    "calculate_counter_rate",
    "calculate_histogram_delta",
    "decode_metrics_receipt",
    "decode_metrics_snapshot",
    "encode_metrics_receipt",
    "encode_metrics_snapshot",
    "receipt_for_body",
]
