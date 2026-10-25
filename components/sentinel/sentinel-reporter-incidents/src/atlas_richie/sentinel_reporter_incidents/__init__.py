"""Optional, independently versioned Sentinel Incident Event Reporter."""

from .errors import (
    IncidentPermanentRemoteError,
    IncidentReceiptMismatchError,
    IncidentRemoteError,
    IncidentRemoteErrorCode,
    IncidentReporterError,
    IncidentReporterErrorCode,
    IncidentRetryableRemoteError,
    IncidentTransportUnavailableError,
)
from .http_transport import (
    IncidentEventHttpTransport,
    IncidentTlsCredential,
    IncidentTlsCredentialProvider,
)
from .producer import IncidentEventProducer
from .reporter import (
    IncidentEventReporter,
    IncidentEventTransport,
    IncidentReporterConfig,
)

__all__ = [
    "IncidentEventHttpTransport",
    "IncidentEventProducer",
    "IncidentEventReporter",
    "IncidentEventTransport",
    "IncidentPermanentRemoteError",
    "IncidentReceiptMismatchError",
    "IncidentRemoteError",
    "IncidentRemoteErrorCode",
    "IncidentReporterConfig",
    "IncidentReporterError",
    "IncidentReporterErrorCode",
    "IncidentRetryableRemoteError",
    "IncidentTlsCredential",
    "IncidentTlsCredentialProvider",
    "IncidentTransportUnavailableError",
]
