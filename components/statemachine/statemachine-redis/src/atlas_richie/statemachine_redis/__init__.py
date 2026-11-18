"""Redis-backed state storage and sequence allocation.

Ported from `RedisStateStorage` and the key layout of `StateMachineKeyBuilder`
(Java). Key names follow the Java convention:

    {prefix}:state:{machine}:{businessId}          current state, no expiry
    {prefix}:history:list:{machine}:{businessId}   history, TTL + length cap
    {prefix}:seq:{machine}:{businessId}            monotonic sequence (INCR)

Two deliberate improvements over Java are documented in the README: history is a
Redis LIST appended atomically (Java read-modify-writes a whole JSON array, which
loses entries under concurrent transitions), and the list is length-capped.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from atlas_richie.statemachine_core import StateContext, StateHistory

DEFAULT_PREFIX = "platform:statemachine"
DEFAULT_HISTORY_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_MAX_HISTORY = 1000


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)


class StateMachineKeyBuilder:
    """Key layout compatible with the Java `StateMachineKeyBuilder`."""

    def __init__(self, prefix: str = DEFAULT_PREFIX) -> None:
        self._prefix = prefix or DEFAULT_PREFIX

    @property
    def prefix(self) -> str:
        return self._prefix

    def current_state(self, machine: str, business_id: int) -> str:
        return f"{self._prefix}:state:{machine}:{business_id}"

    def history_list(self, machine: str, business_id: int) -> str:
        return f"{self._prefix}:history:list:{machine}:{business_id}"

    def sequence(self, machine: str, business_id: int) -> str:
        return f"{self._prefix}:seq:{machine}:{business_id}"


class RedisStateStorage:
    """Durable, cross-instance `StateStorage` backed by Redis.

    Current state never expires (a state machine must not forget its state).
    History carries a TTL — forced to 7 days if a non-positive value is configured,
    matching Java — and is trimmed to `max_history` newest entries.
    """

    def __init__(
        self,
        client,
        *,
        key_builder: StateMachineKeyBuilder | None = None,
        history_ttl_seconds: float = DEFAULT_HISTORY_TTL_SECONDS,
        max_history: int = DEFAULT_MAX_HISTORY,
    ) -> None:
        self._client = client
        self._keys = key_builder if key_builder is not None else StateMachineKeyBuilder()
        self._history_ttl = (
            history_ttl_seconds if history_ttl_seconds > 0 else DEFAULT_HISTORY_TTL_SECONDS
        )
        self._max_history = max(1, max_history)

    def save_current_state(
        self, state_machine_name: str, business_id: int, current_state: str, context: StateContext
    ) -> None:
        self._client.set(self._keys.current_state(state_machine_name, business_id), current_state)

    def get_current_state(self, state_machine_name: str, business_id: int) -> str | None:
        value = self._client.get(self._keys.current_state(state_machine_name, business_id))
        return None if value is None else _text(value)

    def save_state_history(
        self,
        state_machine_name: str,
        business_id: int,
        from_state: str | None,
        to_state: str,
        event: str | None,
        context: StateContext,
    ) -> None:
        seq = context.get_attribute("seq")
        record = StateHistory(
            state_machine_name=state_machine_name,
            business_id=business_id,
            from_state=from_state,
            to_state=to_state,
            event=event,
            seq=int(seq) if isinstance(seq, (int, float)) else 0,
            operator=context.get_attribute("operator"),
            remark=context.get_attribute("remark"),
            attributes=dict(context.attributes),
        )
        payload = asdict(record)
        payload["create_time"] = int(record.create_time.timestamp() * 1000)
        key = self._keys.history_list(state_machine_name, business_id)
        # Atomic append: no read-modify-write, so concurrent transitions cannot
        # drop each other's history entries.
        self._client.rpush(key, json.dumps(payload, ensure_ascii=False, default=str))
        self._client.ltrim(key, -self._max_history, -1)
        self._client.expire(key, int(self._history_ttl))

    def get_state_history(self, state_machine_name: str, business_id: int) -> list[StateHistory]:
        key = self._keys.history_list(state_machine_name, business_id)
        entries = self._client.lrange(key, 0, -1)
        histories: list[StateHistory] = []
        for entry in entries:
            try:
                payload = json.loads(_text(entry))
            except (TypeError, ValueError):
                continue
            histories.append(
                StateHistory(
                    state_machine_name=payload.get("state_machine_name", state_machine_name),
                    business_id=payload.get("business_id", business_id),
                    from_state=payload.get("from_state"),
                    to_state=payload.get("to_state", ""),
                    event=payload.get("event"),
                    seq=payload.get("seq"),
                    operator=payload.get("operator"),
                    remark=payload.get("remark"),
                    attributes=payload.get("attributes") or {},
                )
            )
        # Appended in chronological order; callers get newest first, as in Java.
        histories.reverse()
        return histories

    def delete_state(self, state_machine_name: str, business_id: int) -> None:
        self._client.delete(
            self._keys.current_state(state_machine_name, business_id),
            self._keys.history_list(state_machine_name, business_id),
            self._keys.sequence(state_machine_name, business_id),
        )


class RedisSequenceAllocator:
    """Cross-instance monotonic sequence via Redis INCR (Java uses the same key)."""

    def __init__(self, client, *, key_builder: StateMachineKeyBuilder | None = None) -> None:
        self._client = client
        self._keys = key_builder if key_builder is not None else StateMachineKeyBuilder()

    def next_seq(self, state_machine_name: str, business_id: int) -> int:
        return int(self._client.incr(self._keys.sequence(state_machine_name, business_id)))


__all__ = [
    "DEFAULT_HISTORY_TTL_SECONDS",
    "DEFAULT_MAX_HISTORY",
    "DEFAULT_PREFIX",
    "RedisSequenceAllocator",
    "RedisStateStorage",
    "StateMachineKeyBuilder",
]
