"""Public Sentinel reporting boundary for optional reporting extensions.

Applications may install a reporting extension without coupling their
composition code to Sentinel's private capture implementation module.
The public values stay local to the process; they are not wire DTOs.
"""

from __future__ import annotations

from ._metrics_capture import (
    HttpMetricProducer,
    HttpMetricProducerSnapshot,
    HttpMetricSnapshot,
    MetricCapture,
    MetricCaptureSource,
    MetricsCaptureAdapter,
    MetricsReportingBuffer,
    MetricsReportingError,
    MetricsReportingPort,
)

__all__ = [
    "HttpMetricProducer",
    "HttpMetricProducerSnapshot",
    "HttpMetricSnapshot",
    "MetricCapture",
    "MetricCaptureSource",
    "MetricsCaptureAdapter",
    "MetricsReportingBuffer",
    "MetricsReportingError",
    "MetricsReportingPort",
]
