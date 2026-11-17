"""Framework-neutral state machine engine.

Zero runtime dependencies. Guards/actions are injected callables; persistence and
sequence allocation are SPIs with per-process reference implementations.
"""

import importlib.metadata

from .engine import StateChangedEvent, StateMachineEngine
from .model import (
    State,
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

__version__ = importlib.metadata.version("atlas-richie-statemachine-core")

__all__ = [
    "InMemorySequenceAllocator",
    "InMemoryStateStorage",
    "SequenceAllocator",
    "State",
    "StateChangedEvent",
    "StateContext",
    "StateHistory",
    "StateMachineEngine",
    "StateMachineModel",
    "StateStorage",
    "StateTransitionResult",
    "StateType",
    "Transition",
    "__version__",
]
