"""Storage SPI plus in-memory reference implementations.

The Java side ships Redis, MyBatis/DB and async-thread persistence managers
(~1700 lines). Those are infrastructure, not engine semantics, so the core defines
a `StateStorage` Protocol and provides a per-process reference implementation.
A durable or shared implementation is injected by the caller.
"""

from __future__ import annotations

import threading
from typing import Protocol

from .model import StateContext, StateHistory


class StateStorage(Protocol):
    def save_current_state(
        self, state_machine_name: str, business_id: int, current_state: str, context: StateContext
    ) -> None: ...

    def get_current_state(self, state_machine_name: str, business_id: int) -> str | None: ...

    def save_state_history(
        self,
        state_machine_name: str,
        business_id: int,
        from_state: str | None,
        to_state: str,
        event: str | None,
        context: StateContext,
    ) -> None: ...

    def get_state_history(self, state_machine_name: str, business_id: int) -> list[StateHistory]: ...

    def delete_state(self, state_machine_name: str, business_id: int) -> None: ...


class SequenceAllocator(Protocol):
    """Allocates the monotonic `seq` recorded on each transition.

    Java uses a Redis INCR via `StateMachineKeyBuilder`. A multi-instance
    deployment must inject a shared allocator, otherwise sequences collide.
    """

    def next_seq(self, state_machine_name: str, business_id: int) -> int: ...


class InMemorySequenceAllocator:
    def __init__(self) -> None:
        self._counters: dict[tuple[str, int], int] = {}
        self._lock = threading.Lock()

    def next_seq(self, state_machine_name: str, business_id: int) -> int:
        key = (state_machine_name, business_id)
        with self._lock:
            value = self._counters.get(key, 0) + 1
            self._counters[key] = value
            return value


class InMemoryStateStorage:
    """Thread-safe per-process storage. Not durable and not shared across instances."""

    def __init__(self) -> None:
        self._current: dict[tuple[str, int], str] = {}
        self._history: dict[tuple[str, int], list[StateHistory]] = {}
        self._lock = threading.Lock()

    def save_current_state(
        self, state_machine_name: str, business_id: int, current_state: str, context: StateContext
    ) -> None:
        with self._lock:
            self._current[(state_machine_name, business_id)] = current_state

    def get_current_state(self, state_machine_name: str, business_id: int) -> str | None:
        with self._lock:
            return self._current.get((state_machine_name, business_id))

    def save_state_history(
        self,
        state_machine_name: str,
        business_id: int,
        from_state: str | None,
        to_state: str,
        event: str | None,
        context: StateContext,
    ) -> None:
        record = StateHistory(
            state_machine_name=state_machine_name,
            business_id=business_id,
            from_state=from_state,
            to_state=to_state,
            event=event,
            seq=context.get_attribute("seq"),
            operator=context.get_attribute("operator"),
            remark=context.get_attribute("remark"),
            attributes=dict(context.attributes),
        )
        with self._lock:
            self._history.setdefault((state_machine_name, business_id), []).append(record)

    def get_state_history(self, state_machine_name: str, business_id: int) -> list[StateHistory]:
        with self._lock:
            return list(self._history.get((state_machine_name, business_id), []))

    def delete_state(self, state_machine_name: str, business_id: int) -> None:
        with self._lock:
            self._current.pop((state_machine_name, business_id), None)
            self._history.pop((state_machine_name, business_id), None)


__all__ = [
    "InMemorySequenceAllocator",
    "InMemoryStateStorage",
    "SequenceAllocator",
    "StateStorage",
]
