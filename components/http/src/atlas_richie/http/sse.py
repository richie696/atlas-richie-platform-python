"""RFC 8895 Server-Sent Event values and an incremental parser."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


DEFAULT_EVENT_NAME = "message"
_FIELD_SEPARATOR = ":"
_SPACE = " "
_LINE_FEED = "\n"


class _SseField(StrEnum):
    ID = "id"
    EVENT = "event"
    DATA = "data"
    RETRY = "retry"


@dataclass(frozen=True, slots=True)
class SseEvent:
    """One complete event emitted by an SSE endpoint."""

    data: str | None = None
    event: str = DEFAULT_EVENT_NAME
    event_id: str | None = None
    retry_ms: int | None = None

    def __post_init__(self) -> None:
        if not self.event:
            raise ValueError("SSE event name must not be blank")
        if self.retry_ms is not None and self.retry_ms < 0:
            raise ValueError("SSE retry_ms must be non-negative when present")


class SseEventParser:
    """Owns the incremental SSE state machine independently of HTTPX streams."""

    def __init__(self) -> None:
        self._data: list[str] = []
        self._event_id: str | None = None
        self._event_name: str | None = None
        self._retry_ms: int | None = None

    def feed(self, line: str) -> SseEvent | None:
        """Consume a line without its terminator and emit on an empty delimiter line."""

        if not isinstance(line, str):
            raise TypeError("SSE line must be a string")
        if not line:
            return self._dispatch()
        if line.startswith(_FIELD_SEPARATOR):
            return None
        field, value = _split_field(line)
        if field == _SseField.ID:
            self._event_id = value
        elif field == _SseField.EVENT:
            self._event_name = value
        elif field == _SseField.DATA:
            self._data.append(value)
        elif field == _SseField.RETRY and value.isdecimal():
            self._retry_ms = int(value)
        return None

    def flush(self) -> SseEvent | None:
        """Emit a final partial event when an SSE response ends without a delimiter."""

        return self._dispatch()

    def _dispatch(self) -> SseEvent | None:
        if not self._data and self._event_id is None and self._event_name is None and self._retry_ms is None:
            return None
        event = SseEvent(
            data=_LINE_FEED.join(self._data) if self._data else None,
            event=self._event_name or DEFAULT_EVENT_NAME,
            event_id=self._event_id,
            retry_ms=self._retry_ms,
        )
        self._data.clear()
        self._event_id = None
        self._event_name = None
        self._retry_ms = None
        return event


def _split_field(line: str) -> tuple[str, str]:
    field, separator, value = line.partition(_FIELD_SEPARATOR)
    if not separator:
        return field, ""
    return field, value.removeprefix(_SPACE)
