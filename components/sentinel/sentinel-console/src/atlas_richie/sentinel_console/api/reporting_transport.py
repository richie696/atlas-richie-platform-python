"""Shared bounded JSON and verified-mTLS request handling for Reporters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..application.metrics_ingest_ports import VerifiedMetricsPeer


class ReportingPayloadTooLarge(ValueError):
    """A declared or streamed Reporter request exceeded its protocol limit."""


def reporting_error(code: str, status: int) -> JSONResponse:
    """Return a stable no-store error envelope without echoing input data."""
    return JSONResponse(
        {"error": {"code": code}},
        status_code=status,
        headers={"cache-control": "no-store"},
    )


def has_json_content_type(request: Request) -> bool:
    """Require exactly one application/json media type, ignoring parameters."""
    values = request.headers.getlist("content-type")
    return (
        len(values) == 1
        and values[0].partition(";")[0].strip().lower() == "application/json"
    )


async def read_bounded_body(request: Request, maximum_bytes: int) -> bytes:
    """Read a request body with framing validation and an enforced byte ceiling."""
    if type(maximum_bytes) is not int or maximum_bytes < 1:
        raise ValueError("body size limit must be a positive integer")
    lengths = request.headers.getlist("content-length")
    if len(lengths) > 1:
        raise ValueError("ambiguous content length")
    if lengths:
        value = lengths[0]
        if not value.isascii() or not value.isdigit():
            raise ValueError("invalid content length")
        if len(value) > 8 or int(value) > maximum_bytes:
            raise ReportingPayloadTooLarge
        declared_length = int(value)
    else:
        declared_length = None

    chunks: list[bytes] = []
    byte_count = 0
    async for chunk in request.stream():
        byte_count += len(chunk)
        if byte_count > maximum_bytes:
            raise ReportingPayloadTooLarge
        chunks.append(chunk)
    if declared_length is not None and declared_length != byte_count:
        raise ValueError("body length does not match content length")
    return b"".join(chunks)


def verified_reporter_peer(request: Request) -> VerifiedMetricsPeer | None:
    """Extract only the certificate exposed by the validated ASGI TLS session."""
    if request.scope.get("scheme") != "https":
        return None
    extensions = request.scope.get("extensions")
    if not isinstance(extensions, Mapping):
        return None
    tls = extensions.get("tls")
    if not isinstance(tls, Mapping):
        return None
    certificate_chain = tls.get("client_cert_chain", ())
    if not isinstance(certificate_chain, Iterable) or isinstance(
        certificate_chain, (str, bytes)
    ):
        return None
    try:
        certificate_pem = next(iter(certificate_chain))
        if not isinstance(certificate_pem, str):
            return None
        certificate = x509.load_pem_x509_certificate(certificate_pem.encode("ascii"))
    except (StopIteration, UnicodeEncodeError, ValueError):
        return None
    return VerifiedMetricsPeer(certificate.fingerprint(hashes.SHA256()).hex())


__all__ = [
    "ReportingPayloadTooLarge",
    "has_json_content_type",
    "read_bounded_body",
    "reporting_error",
    "verified_reporter_peer",
]
