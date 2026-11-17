# atlas-richie-statemachine-core

Framework-neutral state machine engine: states, transitions, guards, actions,
history and pluggable storage. Ported from the Java `atlas-richie-statemachine`.

**Zero runtime dependencies.**

## Usage

```python
from atlas_richie.statemachine_core import (
    State, StateMachineEngine, StateMachineModel, StateType, Transition,
)

model = StateMachineModel(name="order", initial_state="CREATED")
model.add_state(State("CREATED", type=StateType.INITIAL))
model.add_state(State("PAID"))
model.add_state(State("CLOSED", type=StateType.FINAL))
model.add_transition(Transition("pay", "CREATED", "PAID", event="PAY"))
model.add_transition(Transition(
    "refund", "PAID", "CLOSED", event="REFUND",
    condition=lambda ctx: ctx.get_attribute("amount", 0) > 0,
    action=lambda ctx: ctx.set_attribute("refunded", True),
))

engine = StateMachineEngine({"order": model})
result = engine.fire("order", "PAY", business_id=1001)
assert result.success and result.context.current_state == "PAID"
```

## Evaluation model — agreed deviation from Java

Java runs **easy-rules** (`DefaultRulesEngine` with configurable
`skipOnFirstAppliedRule` / `skipOnFirstFailedRule` / `skipOnFirstNonTriggeredRule`
and a priority threshold) and evaluates guards/actions as **SpEL** expressions.

This port instead:

1. collects transitions matching `(current_state, event)`,
2. sorts them by **descending priority**,
3. executes the **first whose guard passes**, then stops.

That is equivalent to easy-rules with `skipOnFirstAppliedRule=true`, the common
configuration. The other skip modes and the priority threshold are not exposed.

Guards and actions are **injected callables**, not expression strings. Substituting
an expression language would either add a dependency or create an injection
surface; `eval` is deliberately not used. The consequence is that definitions are
code/dataclasses — the Java YAML-driven definition loader is **not** ported.

## Semantics preserved from Java

- `Transition.from_state=None` is a wildcard matching any source state; likewise
  `event=None` in `get_transitions`.
- **Terminal states are closed**: when the current state is `FINAL` or `ERROR`,
  only transitions whose `attributes["reopen"] is True` are eligible.
- With no stored state, the machine's `initial_state` is used. Passing
  `current_state` explicitly skips the storage read (the Java fast path).
- Each applied transition allocates a monotonic `seq` into `context.attributes`.
- `enable_history` / `enable_events` switches mirror the Java properties.
- Failures are returned as `StateTransitionResult.failure(...)`, never raised —
  including guard/action exceptions, matching the Java outer catch.
- A failing event listener is logged and does not undo the transition.

## Storage and sequences are SPIs

`StateStorage` and `SequenceAllocator` are Protocols with thread-safe **per-process**
reference implementations. They are not durable and not shared across instances:
a multi-instance deployment must inject a shared store and a shared sequence
allocator (Java uses Redis INCR), otherwise states diverge and sequences collide.

Not ported: `RedisStateStorage`, `StateDbPersistenceService`,
`AsyncThreadStorageManager`, `StateSyncStreamConsumer`, `StateCleanupScheduler`,
the YAML config loader, and Spring auto-configuration — roughly 2900 lines of
infrastructure around a ~1500-line engine.

`can_fire` is a **structural** reachability check; it does not evaluate guards.
