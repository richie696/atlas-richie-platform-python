"""Stable, sanitized errors exposed by the rule receipt reporter."""

from __future__ import annotations

from enum import StrEnum


class RuleReceiptDeliveryCode(StrEnum):
    """Failure category without remote body, URL, or TLS details."""

    TRANSPORT_UNAVAILABLE = "transport_unavailable"
    RETRYABLE_REMOTE = "retryable_remote"
    PERMANENT_REMOTE = "permanent_remote"
    CREDENTIALS_UNAVAILABLE = "credentials_unavailable"


class RuleReceiptDeliveryError(Exception):
    """Sanitized receipt delivery failure suitable for logs and counters."""

    def __init__(self, code: RuleReceiptDeliveryCode, *, retryable: bool) -> None:
        super().__init__(code.value)
        self.code = code
        self.retryable = retryable


__all__ = ["RuleReceiptDeliveryCode", "RuleReceiptDeliveryError"]
