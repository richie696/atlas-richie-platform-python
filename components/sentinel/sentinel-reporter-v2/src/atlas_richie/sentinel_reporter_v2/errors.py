"""Redacted, stable Reporter failure categories."""

from enum import StrEnum


class MetricsReporterErrorCode(StrEnum):
    """Reporter failures safe to expose without transport details or secrets."""

    TRANSPORT_UNAVAILABLE = "transport_unavailable"
    CREDENTIALS_UNAVAILABLE = "credentials_unavailable"
    RECEIPT_MISMATCH = "receipt_mismatch"


class MetricsTransportError(RuntimeError):
    """A retryable transport failure with no raw URL, response, or secret text."""

    def __init__(self, code: MetricsReporterErrorCode) -> None:
        if not isinstance(code, MetricsReporterErrorCode):
            raise TypeError("transport error code must use MetricsReporterErrorCode")
        self.code = code
        super().__init__(code.value)


class MetricsReceiptMismatchError(RuntimeError):
    """An ACK did not correlate to the exact in-flight snapshot."""

    def __init__(self) -> None:
        self.code = MetricsReporterErrorCode.RECEIPT_MISMATCH
        super().__init__(self.code.value)


__all__ = [
    "MetricsReceiptMismatchError",
    "MetricsReporterErrorCode",
    "MetricsTransportError",
]
