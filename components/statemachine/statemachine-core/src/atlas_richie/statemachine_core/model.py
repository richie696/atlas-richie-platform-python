"""State machine model, context, history and transition result.

Ported from `cn.richie696.component.statemachine.{model,context,storage,engine}`
(Java). Guards and actions are **callables**, not expression strings: the Java
side evaluates SpEL, and substituting an expression language would either add a
dependency or introduce an injection surface. Callers inject Python predicates
and actions instead, so definitions are code/dataclasses rather than YAML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StateType(StrEnum):
    NORMAL = "NORMAL"
    INITIAL = "INITIAL"
    FINAL = "FINAL"
    ERROR = "ERROR"


@dataclass
class State:
    name: str
    description: str | None = None
    type: StateType = StateType.NORMAL


@dataclass
class Transition:
    """One transition rule. `from_state=None` is a wildcard matching any state."""

    name: str
    from_state: str | None
    to_state: str
    event: str | None = None
    description: str | None = None
    condition: Callable[[StateContext], bool] | None = None
    action: Callable[[StateContext], None] | None = None
    priority: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class StateContext:
    """Mutable per-transition context handed to guards and actions."""

    current_state: str | None = None
    event: str | None = None
    previous_state: str | None = None
    transition: Transition | None = None
    create_time: datetime = field(default_factory=_now)
    update_time: datetime = field(default_factory=_now)
    attributes: dict[str, Any] = field(default_factory=dict)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def get_attribute(self, key: str, default: Any = None) -> Any:
        return self.attributes.get(key, default)

    def remove_attribute(self, key: str) -> Any:
        return self.attributes.pop(key, None)

    def touch(self) -> None:
        self.update_time = _now()


@dataclass
class StateMachineModel:
    name: str
    initial_state: str
    description: str | None = None
    states: list[State] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    version: str = "1.0.0"

    def add_state(self, state: State) -> None:
        self.states.append(state)

    def add_transition(self, transition: Transition) -> None:
        self.transitions.append(transition)

    def get_state(self, state_name: str | None) -> State | None:
        for state in self.states:
            if state.name == state_name:
                return state
        return None

    def get_transitions(self, from_state: str | None, event: str | None) -> list[Transition]:
        """Match by source state and event; `None` on either side is a wildcard."""
        return [
            transition
            for transition in self.transitions
            if (transition.from_state is None or transition.from_state == from_state)
            and (event is None or event == transition.event)
        ]


@dataclass
class StateHistory:
    state_machine_name: str
    business_id: int
    from_state: str | None
    to_state: str
    event: str | None
    seq: int | None = None
    operator: str | None = None
    remark: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    create_time: datetime = field(default_factory=_now)
    id: int | None = None


@dataclass
class StateTransitionResult:
    success: bool
    error_message: str | None = None
    context: StateContext | None = None

    @classmethod
    def ok(cls, context: StateContext) -> StateTransitionResult:
        return cls(True, None, context)

    @classmethod
    def failure(cls, error_message: str) -> StateTransitionResult:
        return cls(False, error_message, None)


__all__ = [
    "State",
    "StateContext",
    "StateHistory",
    "StateMachineModel",
    "StateTransitionResult",
    "StateType",
    "Transition",
]
