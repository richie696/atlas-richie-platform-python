"""Explicit, bounded delivery for typed Sentinel Incident Event V1 facts."""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from atlas_richie.contracts.incidents.v1 import (
    IncidentEventReceiptV1,
    IncidentEventV1,
    IncidentProtocolError,
    decode_incident_receipt,
    encode_incident_event,
)

from .errors import (
    IncidentReceiptMismatchError,
    IncidentReporterError,
    IncidentReporterErrorCode,
    IncidentRetryableRemoteError,
    IncidentTransportUnavailableError,
)


@runtime_checkable
class IncidentEventTransport(Protocol):
    """Send exact event bytes and return the Collector's durable ACK body."""

    async def send(self, payload: bytes) -> bytes: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class IncidentReporterConfig:
    """Bound the number and delay of attempts for one caller-submitted event."""

    max_attempts: int = 5
    retry_base_seconds: float = 0.25
    retry_max_seconds: float = 5.0

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 100:
            raise ValueError("max_attempts must be between 1 and 100")
        if (
            type(self.retry_base_seconds) not in (int, float)
            or type(self.retry_max_seconds) not in (int, float)
            or not math.isfinite(self.retry_base_seconds)
            or not math.isfinite(self.retry_max_seconds)
            or self.retry_base_seconds <= 0
            or self.retry_max_seconds < self.retry_base_seconds
        ):
            raise ValueError("retry delay bounds are invalid")


class IncidentEventReporter:
    """Report explicit incident facts without inventing alert policy.

    The caller owns the decision that an incident occurred and submits the
    complete typed fact. This object serializes it once, retries only identical
    bytes with the same event ID, and succeeds only after a matching durable
    Collector receipt. It has no queue, sampler, threshold policy, or background
    task; callers choose where to await this operation.
    """

    __slots__ = ("_config", "_sleep", "_transport")

    def __init__(
        self,
        transport: IncidentEventTransport,
        config: IncidentReporterConfig | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not isinstance(transport, IncidentEventTransport):
            raise TypeError("transport must implement IncidentEventTransport")
        if config is None:
            config = IncidentReporterConfig()
        if not isinstance(config, IncidentReporterConfig):
            raise TypeError("config must be IncidentReporterConfig")
        self._transport = transport
        self._config = config
        self._sleep = sleep

    async def report(self, event: IncidentEventV1) -> IncidentEventReceiptV1:
        """Return only the durable receipt correlated to this exact event."""
        payload = encode_incident_event(event)
        expected_digest = hashlib.sha256(payload).hexdigest()
        for attempt in range(self._config.max_attempts):
            try:
                body = await self._transport.send(payload)
                receipt = decode_incident_receipt(body)
                if (
                    receipt.event_id != event.event_id
                    or receipt.body_sha256 != expected_digest
                ):
                    raise IncidentReceiptMismatchError()
                return receipt
            except asyncio.CancelledError:
                raise
            except IncidentReceiptMismatchError:
                raise
            except IncidentProtocolError:
                raise IncidentReceiptMismatchError() from None
            except (IncidentRetryableRemoteError, IncidentTransportUnavailableError):
                if attempt + 1 == self._config.max_attempts:
                    raise
                await self._wait_before_retry(attempt)
            except IncidentReporterError:
                raise
            except Exception:  # noqa: BLE001 - transport detail may contain secrets
                raise IncidentReporterError(
                    IncidentReporterErrorCode.TRANSPORT_UNAVAILABLE
                ) from None
        raise AssertionError("bounded reporter loop must return or raise")

    async def _wait_before_retry(self, attempt: int) -> None:
        delay = min(
            self._config.retry_base_seconds * (2**attempt),
            self._config.retry_max_seconds,
        )
        try:
            await self._sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - sleep adapter detail is untrusted
            raise IncidentReporterError(
                IncidentReporterErrorCode.TRANSPORT_UNAVAILABLE
            ) from None

    async def aclose(self) -> None:
        """Release the owned transport resources."""
        await self._transport.aclose()


__all__ = [
    "IncidentEventReporter",
    "IncidentEventTransport",
    "IncidentReporterConfig",
]
