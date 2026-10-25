"""Read the paginated, per-worker Agent Reporting negotiation projection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from ..domain.protocol_negotiations import (
    MAX_PROTOCOL_OBSERVATIONS_PAGE,
    MAX_PROTOCOL_OBSERVATIONS_PAGE_SIZE,
    ProtocolNegotiationPage,
)
from .protocol_negotiation_ports import (
    AgentReportingNegotiationReader,
    IncidentEventNegotiationReader,
)


class ReadAgentReportingNegotiations:
    """Validate bounded paging and delegate to the durable observation source."""

    def __init__(
        self,
        store: AgentReportingNegotiationReader,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, *, page: int, page_size: int) -> ProtocolNegotiationPage:
        """Return the latest authority snapshot without lossy fleet aggregation."""
        return await _read_page(
            self._store.read_agent_reporting_negotiations,
            self._clock,
            page=page,
            page_size=page_size,
        )


class ReadIncidentEventNegotiations:
    """Read bounded per-worker Incident Event negotiation facts."""

    def __init__(
        self,
        store: IncidentEventNegotiationReader,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, *, page: int, page_size: int) -> ProtocolNegotiationPage:
        """Return only facts negotiated for Incident Event itself."""
        return await _read_page(
            self._store.read_incident_event_negotiations,
            self._clock,
            page=page,
            page_size=page_size,
        )


async def _read_page(
    read_page: Callable[..., Awaitable[ProtocolNegotiationPage]],
    clock: Callable[[], datetime],
    *,
    page: int,
    page_size: int,
) -> ProtocolNegotiationPage:
    """Share the common paging/time contract across protocol authorities."""
    if (
        type(page) is not int
        or not 1 <= page <= MAX_PROTOCOL_OBSERVATIONS_PAGE
        or type(page_size) is not int
        or not 1 <= page_size <= MAX_PROTOCOL_OBSERVATIONS_PAGE_SIZE
    ):
        raise ValueError("protocol observation query is invalid")
    as_of = clock()
    if (
        not isinstance(as_of, datetime)
        or as_of.tzinfo is None
        or as_of.utcoffset() != UTC.utcoffset(as_of)
    ):
        raise RuntimeError("Console clock must return an aware UTC instant")
    snapshot = await read_page(
        page=page, page_size=page_size, as_of=as_of.astimezone(UTC)
    )
    if not isinstance(snapshot, ProtocolNegotiationPage):
        raise TypeError("protocol observation store returned an invalid page")
    return snapshot


__all__ = ["ReadAgentReportingNegotiations", "ReadIncidentEventNegotiations"]
