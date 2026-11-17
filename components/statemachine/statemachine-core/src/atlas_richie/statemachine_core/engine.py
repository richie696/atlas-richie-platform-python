"""State machine engine.

Ported from `cn.richie696.component.statemachine.engine.StateMachineEngine` (Java).

Evaluation model (agreed deviation): Java runs easy-rules with configurable
`skipOnFirstApplied/Failed/NonTriggered` and a priority threshold. This port sorts
matching transitions by descending priority and executes the **first whose guard
passes**, then stops — equivalent to easy-rules with `skipOnFirstAppliedRule=true`,
which is the common configuration. Guards and actions are injected callables.

Preserved semantics: wildcard `from_state`, the FINAL/ERROR `reopen` whitelist,
initial-state fallback, explicit current state skipping the storage read, `seq`
allocation, history/event switches, and failure results instead of raised errors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from .model import (
    StateContext,
    StateHistory,
    StateMachineModel,
    StateTransitionResult,
    StateType,
    Transition,
)
from .storage import (
    InMemorySequenceAllocator,
    InMemoryStateStorage,
    SequenceAllocator,
    StateStorage,
)

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StateChangedEvent:
    """Replaces Spring's `ApplicationEventPublisher` notification."""

    state_machine_name: str
    business_id: int
    event: str | None
    context: StateContext


class StateMachineEngine:
    def __init__(
        self,
        models: dict[str, StateMachineModel] | None = None,
        storage: StateStorage | None = None,
        sequence_allocator: SequenceAllocator | None = None,
        *,
        enable_history: bool = True,
        enable_events: bool = True,
        priority_based: bool = True,
        listeners: list[Callable[[StateChangedEvent], None]] | None = None,
    ) -> None:
        self._models: dict[str, StateMachineModel] = dict(models or {})
        self._storage = storage if storage is not None else InMemoryStateStorage()
        self._sequences = sequence_allocator if sequence_allocator is not None else InMemorySequenceAllocator()
        self._enable_history = enable_history
        self._enable_events = enable_events
        self._priority_based = priority_based
        self._listeners: list[Callable[[StateChangedEvent], None]] = list(listeners or [])

    def register(self, model: StateMachineModel) -> None:
        self._models[model.name] = model

    def add_listener(self, listener: Callable[[StateChangedEvent], None]) -> None:
        self._listeners.append(listener)

    def fire(
        self,
        state_machine_name: str,
        event: str,
        business_id: int,
        attributes: dict[str, Any] | None = None,
        current_state: str | None = None,
    ) -> StateTransitionResult:
        try:
            model = self._models.get(state_machine_name)
            if model is None:
                return StateTransitionResult.failure(f"状态机未找到: {state_machine_name}")

            context = StateContext(current_state=current_state, event=event)
            if attributes:
                for key, value in attributes.items():
                    context.set_attribute(key, value)
            if current_state is None:
                stored = self._storage.get_current_state(state_machine_name, business_id)
                context.current_state = stored if stored is not None else model.initial_state

            transitions = model.get_transitions(context.current_state, event)
            state_meta = model.get_state(context.current_state)
            if state_meta is not None and state_meta.type in (StateType.FINAL, StateType.ERROR):
                transitions = [
                    transition
                    for transition in transitions
                    if transition.attributes.get("reopen") is True
                ]
            if not transitions:
                return StateTransitionResult.failure("没有找到匹配的转换规则")

            ordered = (
                sorted(transitions, key=lambda transition: transition.priority, reverse=True)
                if self._priority_based and len(transitions) > 1
                else list(transitions)
            )

            applied: Transition | None = None
            for transition in ordered:
                if transition.condition is not None and not transition.condition(context):
                    continue
                if transition.action is not None:
                    transition.action(context)
                context.previous_state = context.current_state
                context.current_state = transition.to_state
                context.transition = transition
                context.touch()
                applied = transition
                break

            if applied is None:
                return StateTransitionResult.failure("状态转换失败")

            context.set_attribute("seq", self._sequences.next_seq(state_machine_name, business_id))
            self._storage.save_current_state(
                state_machine_name, business_id, context.current_state, context
            )
            if self._enable_history:
                self._storage.save_state_history(
                    state_machine_name,
                    business_id,
                    context.previous_state,
                    context.current_state,
                    event,
                    context,
                )
            if self._enable_events:
                notification = StateChangedEvent(state_machine_name, business_id, event, context)
                for listener in self._listeners:
                    try:
                        listener(notification)
                    except Exception:  # noqa: BLE001 — a listener must not undo a transition
                        _log.exception("state change listener failed; machine=%s", state_machine_name)
            return StateTransitionResult.ok(context)
        except Exception as error:  # noqa: BLE001 — Java returns a failure result, not a raise
            _log.error(
                "state transition failed; machine=%s exceptionType=%s",
                state_machine_name,
                type(error).__name__,
            )
            return StateTransitionResult.failure(f"状态转换异常: {error}")

    def get_current_state(self, state_machine_name: str, business_id: int) -> str | None:
        model = self._models.get(state_machine_name)
        stored = self._storage.get_current_state(state_machine_name, business_id)
        if stored is not None:
            return stored
        return model.initial_state if model is not None else None

    def can_fire(self, state_machine_name: str, event: str, business_id: int) -> bool:
        """Structural reachability check; guards are NOT evaluated here."""
        model = self._models.get(state_machine_name)
        if model is None:
            return False
        current = self.get_current_state(state_machine_name, business_id)
        transitions = model.get_transitions(current, event)
        state_meta = model.get_state(current)
        if state_meta is not None and state_meta.type in (StateType.FINAL, StateType.ERROR):
            transitions = [
                transition for transition in transitions if transition.attributes.get("reopen") is True
            ]
        return bool(transitions)

    def get_state_history(self, state_machine_name: str, business_id: int) -> list[StateHistory]:
        return self._storage.get_state_history(state_machine_name, business_id)

    def delete_state(self, state_machine_name: str, business_id: int) -> None:
        self._storage.delete_state(state_machine_name, business_id)


__all__ = ["StateChangedEvent", "StateMachineEngine"]
