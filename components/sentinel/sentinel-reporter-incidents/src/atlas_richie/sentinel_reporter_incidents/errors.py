"""Stable, redacted failures exposed by the Incident Event Reporter."""

from enum import StrEnum


class IncidentReporterErrorCode(StrEnum):
    """Finite failure categories safe to expose to application code."""

    TRANSPORT_UNAVAILABLE = "transport_unavailable"
    CREDENTIALS_UNAVAILABLE = "credentials_unavailable"
    RECEIPT_MISMATCH = "receipt_mismatch"
    REMOTE_PERMANENT_FAILURE = "remote_permanent_failure"
    REMOTE_RETRYABLE_FAILURE = "remote_retryable_failure"


class IncidentRemoteErrorCode(StrEnum):
    """Allowlisted Collector rejection categories; arbitrary body text is ignored."""

    INVALID_REQUEST = "invalid_request"
    INVALID_JSON = "invalid_json"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    INVALID_EVENT = "invalid_event"
    IDENTITY_NOT_ENROLLED = "identity_not_enrolled"
    IDENTITY_MISMATCH = "identity_mismatch"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    INVALID_CONTENT_TYPE = "invalid_content_type"
    SERVICE_UNAVAILABLE = "service_unavailable"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


class IncidentReporterError(RuntimeError):
    """A transport failure whose message never contains URLs or response text."""

    def __init__(self, code: IncidentReporterErrorCode) -> None:
        if not isinstance(code, IncidentReporterErrorCode):
            raise TypeError("code must use IncidentReporterErrorCode")
        self.code = code
        super().__init__(code.value)


class IncidentReceiptMismatchError(IncidentReporterError):
    """Collector ACK did not correlate with the submitted immutable event."""

    def __init__(self) -> None:
        super().__init__(IncidentReporterErrorCode.RECEIPT_MISMATCH)


class IncidentRemoteError(IncidentReporterError):
    """Non-2xx Collector response with bounded, stable and secret-safe metadata."""

    def __init__(
        self,
        *,
        status_code: int,
        remote_code: IncidentRemoteErrorCode,
        retryable: bool,
    ) -> None:
        if type(status_code) is not int or not 100 <= status_code <= 599:
            raise ValueError("remote status code must be a valid HTTP status")
        if not isinstance(remote_code, IncidentRemoteErrorCode):
            raise TypeError("remote_code must use IncidentRemoteErrorCode")
        self.status_code = status_code
        self.remote_code = remote_code
        self.retryable = retryable
        super().__init__(
            IncidentReporterErrorCode.REMOTE_RETRYABLE_FAILURE
            if retryable
            else IncidentReporterErrorCode.REMOTE_PERMANENT_FAILURE
        )


class IncidentRetryableRemoteError(IncidentRemoteError):
    """Collector response that may become successful after a bounded retry."""

    def __init__(
        self, *, status_code: int, remote_code: IncidentRemoteErrorCode
    ) -> None:
        super().__init__(
            status_code=status_code, remote_code=remote_code, retryable=True
        )


class IncidentPermanentRemoteError(IncidentRemoteError):
    """Collector response that must be surfaced without retrying the request."""

    def __init__(
        self, *, status_code: int, remote_code: IncidentRemoteErrorCode
    ) -> None:
        super().__init__(
            status_code=status_code, remote_code=remote_code, retryable=False
        )


class IncidentTransportUnavailableError(IncidentReporterError):
    """Known network/transport failure eligible for bounded Reporter retry."""

    def __init__(self) -> None:
        super().__init__(IncidentReporterErrorCode.TRANSPORT_UNAVAILABLE)


__all__ = [
    "IncidentPermanentRemoteError",
    "IncidentReceiptMismatchError",
    "IncidentRemoteError",
    "IncidentRemoteErrorCode",
    "IncidentReporterError",
    "IncidentReporterErrorCode",
    "IncidentRetryableRemoteError",
    "IncidentTransportUnavailableError",
]
