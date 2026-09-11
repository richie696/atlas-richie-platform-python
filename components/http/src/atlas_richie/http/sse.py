"""RFC 8895 Server-Sent Event 值与增量解析器。
----
定义 SSE 协议的两种值：

- `SseEvent`：SSE 端点发出的一个完整事件（`data` / `event` /
  `event_id` / `retry_ms`）。
- `SseEventParser`：与 HTTPX 流解耦的增量状态机。
  调用方按行喂入（已剥离换行符），空行时 dispatch 出一个事件；
  流结束时调用 `flush()` 以处理没有空行收尾的尾巴。

行为细节：

- 注释行（以 `:` 开头）忽略，不重置状态。
- 多个 `data:` 行用换行符合并到 `data`。
- `retry` 仅在值是十进制数时被采用；否则视为未知。
- `flush()` 用来兜底"流结束时没有空行收尾"的情形，避免最后
  一个事件被吞掉。

English
--------
SSE (Server-Sent Event) values + incremental parser.

- `SseEvent`: one complete event emitted by an SSE endpoint
  (`data` / `event` / `event_id` / `retry_ms`).
- `SseEventParser`: incremental state machine independent of
  HTTPX streams. Feed lines (without their terminator); an empty
  line dispatches the current event. Call `flush()` at end-of-
  stream so a tail event without a final delimiter is not lost.

Behaviour:

- Comment lines (prefixed with `:`) are ignored without resetting
  state.
- Multiple `data:` lines are joined with newlines.
- `retry` is adopted only when the value is a decimal integer;
  otherwise the field is ignored.
- `flush()` covers the "stream ended without an empty line" case.
"""

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
    """SSE 端点发出的一个完整事件。

    English
    --------
    One complete event emitted by an SSE endpoint.
    """

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
    """与 HTTPX 流解耦的增量 SSE 状态机。

    English
    --------
    Owns the incremental SSE state machine independently of HTTPX
    streams.
    """

    def __init__(self) -> None:
        self._data: list[str] = []
        self._event_id: str | None = None
        self._event_name: str | None = None
        self._retry_ms: int | None = None

    def feed(self, line: str) -> SseEvent | None:
        """消费一行（不含行终止符），遇到空行时 dispatch 出一个事件。

        English
        --------
        Consume a line without its terminator and emit on an empty
        delimiter line.
        """

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
        """当 SSE 响应以非空行结束时，dispatch 最后一个未完成的事件。

        English
        --------
        Emit a final partial event when an SSE response ends
        without a delimiter.
        """

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
