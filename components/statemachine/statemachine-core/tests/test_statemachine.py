"""State machine engine contract tests.

Pins the semantics preserved from Java (wildcards, terminal-state reopen
whitelist, initial-state fallback, explicit-state fast path, seq allocation,
history/event switches, failure-not-raise) and the agreed evaluation deviation
(priority order, first passing guard wins).
"""

from __future__ import annotations

import pytest

from atlas_richie.statemachine_core import (
    InMemoryStateStorage,
    State,
    StateChangedEvent,
    StateMachineEngine,
    StateMachineModel,
    StateType,
    Transition,
)

pytestmark = pytest.mark.unit


def _order_model() -> StateMachineModel:
    model = StateMachineModel(name="order", initial_state="CREATED")
    model.add_state(State("CREATED", type=StateType.INITIAL))
    model.add_state(State("PAID"))
    model.add_state(State("SHIPPED"))
    model.add_state(State("CLOSED", type=StateType.FINAL))
    model.add_state(State("FAILED", type=StateType.ERROR))
    model.add_transition(Transition("pay", "CREATED", "PAID", event="PAY"))
    model.add_transition(Transition("ship", "PAID", "SHIPPED", event="SHIP"))
    model.add_transition(Transition("close", "SHIPPED", "CLOSED", event="CLOSE"))
    model.add_transition(Transition("fail", "PAID", "FAILED", event="FAIL"))
    return model


@pytest.fixture
def engine() -> StateMachineEngine:
    return StateMachineEngine({"order": _order_model()})


class TestBasicTransitions:
    def test_fire_from_initial_state(self, engine: StateMachineEngine) -> None:
        result = engine.fire("order", "PAY", 1)
        assert result.success is True
        assert result.context.current_state == "PAID"
        assert result.context.previous_state == "CREATED"
        assert result.context.transition.name == "pay"

    def test_state_persists_across_fires(self, engine: StateMachineEngine) -> None:
        engine.fire("order", "PAY", 1)
        result = engine.fire("order", "SHIP", 1)
        assert result.success
        assert result.context.current_state == "SHIPPED"
        assert engine.get_current_state("order", 1) == "SHIPPED"

    def test_business_ids_are_independent(self, engine: StateMachineEngine) -> None:
        engine.fire("order", "PAY", 1)
        assert engine.get_current_state("order", 2) == "CREATED"

    def test_unknown_machine_fails(self, engine: StateMachineEngine) -> None:
        result = engine.fire("nope", "PAY", 1)
        assert result.success is False
        assert "状态机未找到" in result.error_message

    def test_no_matching_transition_fails(self, engine: StateMachineEngine) -> None:
        result = engine.fire("order", "SHIP", 1)
        assert result.success is False
        assert result.error_message == "没有找到匹配的转换规则"

    def test_explicit_current_state_skips_storage_read(self) -> None:
        storage = InMemoryStateStorage()
        engine = StateMachineEngine({"order": _order_model()}, storage)
        result = engine.fire("order", "SHIP", 1, current_state="PAID")
        assert result.success
        assert result.context.previous_state == "PAID"
        assert storage.get_current_state("order", 1) == "SHIPPED"

    def test_attributes_reach_context(self, engine: StateMachineEngine) -> None:
        result = engine.fire("order", "PAY", 1, {"operator": "alice"})
        assert result.context.get_attribute("operator") == "alice"


class TestGuardsAndActions:
    def test_guard_blocks_transition(self) -> None:
        model = StateMachineModel(name="m", initial_state="A")
        model.add_transition(
            Transition("vip-go", "A", "B", event="GO",
                       condition=lambda ctx: ctx.get_attribute("vip") is True)
        )
        engine = StateMachineEngine({"m": model})
        assert engine.fire("m", "GO", 1).success is False
        assert engine.fire("m", "GO", 1, {"vip": True}).success is True

    def test_action_runs_and_can_mutate_context(self) -> None:
        model = StateMachineModel(name="m", initial_state="A")
        model.add_transition(
            Transition("go", "A", "B", event="GO",
                       action=lambda ctx: ctx.set_attribute("ran", True))
        )
        result = StateMachineEngine({"m": model}).fire("m", "GO", 1)
        assert result.context.get_attribute("ran") is True

    def test_priority_order_first_passing_guard_wins(self) -> None:
        model = StateMachineModel(name="m", initial_state="A")
        model.add_transition(Transition("low", "A", "LOW", event="GO", priority=1))
        model.add_transition(Transition("high", "A", "HIGH", event="GO", priority=10))
        result = StateMachineEngine({"m": model}).fire("m", "GO", 1)
        assert result.context.current_state == "HIGH"

    def test_high_priority_guard_failing_falls_through(self) -> None:
        model = StateMachineModel(name="m", initial_state="A")
        model.add_transition(
            Transition("high", "A", "HIGH", event="GO", priority=10, condition=lambda ctx: False)
        )
        model.add_transition(Transition("low", "A", "LOW", event="GO", priority=1))
        result = StateMachineEngine({"m": model}).fire("m", "GO", 1)
        assert result.context.current_state == "LOW"

    def test_only_first_applied_transition_runs(self) -> None:
        model = StateMachineModel(name="m", initial_state="A")
        calls: list[str] = []
        model.add_transition(
            Transition("first", "A", "B", event="GO", priority=10,
                       action=lambda ctx: calls.append("first"))
        )
        model.add_transition(
            Transition("second", "A", "C", event="GO", priority=1,
                       action=lambda ctx: calls.append("second"))
        )
        result = StateMachineEngine({"m": model}).fire("m", "GO", 1)
        assert calls == ["first"]
        assert result.context.current_state == "B"

    def test_all_guards_failing_is_a_failure_result(self) -> None:
        model = StateMachineModel(name="m", initial_state="A")
        model.add_transition(Transition("go", "A", "B", event="GO", condition=lambda ctx: False))
        result = StateMachineEngine({"m": model}).fire("m", "GO", 1)
        assert result.success is False
        assert result.error_message == "状态转换失败"

    def test_guard_exception_is_false_and_falls_through_to_next_rule(self) -> None:
        """Java StateTransitionRule: a guard that throws evaluates to false,
        so the next candidate rule is still tried."""
        def boom(ctx):
            raise RuntimeError("guard exploded")

        model = StateMachineModel(name="m", initial_state="A")
        model.add_transition(
            Transition("high", "A", "B", event="GO", priority=10, condition=boom)
        )
        model.add_transition(Transition("low", "A", "C", event="GO", priority=1))
        result = StateMachineEngine({"m": model}).fire("m", "GO", 1)
        assert result.success is True
        assert result.context.current_state == "C"

    def test_guard_exception_with_no_other_rule_is_a_failure_result(self) -> None:
        def boom(ctx):
            raise RuntimeError("guard exploded")

        model = StateMachineModel(name="m", initial_state="A")
        model.add_transition(Transition("go", "A", "B", event="GO", condition=boom))
        result = StateMachineEngine({"m": model}).fire("m", "GO", 1)
        assert result.success is False
        assert result.error_message == "状态转换失败"

    def test_action_exception_still_commits_the_transition(self) -> None:
        """Java executeAction logs and swallows; the state change still commits."""
        def boom(ctx):
            raise ValueError("action exploded")

        model = StateMachineModel(name="m", initial_state="A")
        model.add_transition(Transition("go", "A", "B", event="GO", action=boom))
        engine = StateMachineEngine({"m": model})
        result = engine.fire("m", "GO", 1)
        assert result.success is True
        assert result.context.current_state == "B"
        assert engine.get_current_state("m", 1) == "B", "迁移必须已落库"


class TestWildcardAndTerminalStates:
    def test_wildcard_from_state_matches_any(self) -> None:
        model = _order_model()
        model.add_transition(Transition("audit", None, "PAID", event="AUDIT"))
        engine = StateMachineEngine({"order": model})
        assert engine.fire("order", "AUDIT", 1).context.current_state == "PAID"
        engine.fire("order", "PAY", 2)
        assert engine.fire("order", "AUDIT", 2).context.previous_state == "PAID"

    def test_final_state_blocks_transitions(self, engine: StateMachineEngine) -> None:
        engine.fire("order", "PAY", 1)
        engine.fire("order", "SHIP", 1)
        engine.fire("order", "CLOSE", 1)
        assert engine.get_current_state("order", 1) == "CLOSED"
        result = engine.fire("order", "PAY", 1)
        assert result.success is False

    def test_error_state_blocks_transitions(self, engine: StateMachineEngine) -> None:
        engine.fire("order", "PAY", 1)
        engine.fire("order", "FAIL", 1)
        assert engine.fire("order", "SHIP", 1).success is False

    def test_reopen_whitelist_allows_leaving_final(self) -> None:
        model = _order_model()
        model.add_transition(
            Transition("reopen", "CLOSED", "CREATED", event="REOPEN", attributes={"reopen": True})
        )
        engine = StateMachineEngine({"order": model})
        engine.fire("order", "PAY", 1)
        engine.fire("order", "SHIP", 1)
        engine.fire("order", "CLOSE", 1)
        result = engine.fire("order", "REOPEN", 1)
        assert result.success
        assert result.context.current_state == "CREATED"

    def test_non_reopen_transition_still_blocked_in_final(self) -> None:
        model = _order_model()
        model.add_transition(Transition("sneak", "CLOSED", "PAID", event="SNEAK"))
        model.add_transition(
            Transition("reopen", "CLOSED", "CREATED", event="REOPEN", attributes={"reopen": True})
        )
        engine = StateMachineEngine({"order": model})
        engine.fire("order", "PAY", 1)
        engine.fire("order", "SHIP", 1)
        engine.fire("order", "CLOSE", 1)
        assert engine.fire("order", "SNEAK", 1).success is False

    def test_reopen_flag_must_be_exactly_true(self) -> None:
        model = _order_model()
        model.add_transition(
            Transition("reopen", "CLOSED", "CREATED", event="REOPEN", attributes={"reopen": "true"})
        )
        engine = StateMachineEngine({"order": model})
        engine.fire("order", "PAY", 1)
        engine.fire("order", "SHIP", 1)
        engine.fire("order", "CLOSE", 1)
        assert engine.fire("order", "REOPEN", 1).success is False


class TestHistorySeqAndEvents:
    def test_seq_is_monotonic_per_business_id(self, engine: StateMachineEngine) -> None:
        first = engine.fire("order", "PAY", 1)
        second = engine.fire("order", "SHIP", 1)
        assert first.context.get_attribute("seq") == 1
        assert second.context.get_attribute("seq") == 2
        assert engine.fire("order", "PAY", 2).context.get_attribute("seq") == 1

    def test_history_records_transitions(self, engine: StateMachineEngine) -> None:
        engine.fire("order", "PAY", 1, {"operator": "alice", "remark": "paid"})
        engine.fire("order", "SHIP", 1)
        history = engine.get_state_history("order", 1)
        assert [(h.from_state, h.to_state, h.event) for h in history] == [
            ("CREATED", "PAID", "PAY"),
            ("PAID", "SHIPPED", "SHIP"),
        ]
        assert history[0].operator == "alice"
        assert history[0].remark == "paid"
        assert history[0].seq == 1

    def test_history_can_be_disabled(self) -> None:
        engine = StateMachineEngine({"order": _order_model()}, enable_history=False)
        engine.fire("order", "PAY", 1)
        assert engine.get_state_history("order", 1) == []
        assert engine.get_current_state("order", 1) == "PAID"

    def test_listeners_receive_event(self) -> None:
        seen: list[StateChangedEvent] = []
        engine = StateMachineEngine({"order": _order_model()}, listeners=[seen.append])
        engine.fire("order", "PAY", 7)
        assert len(seen) == 1
        assert (seen[0].state_machine_name, seen[0].business_id, seen[0].event) == ("order", 7, "PAY")
        assert seen[0].context.current_state == "PAID"

    def test_events_can_be_disabled(self) -> None:
        seen: list[StateChangedEvent] = []
        engine = StateMachineEngine(
            {"order": _order_model()}, enable_events=False, listeners=[seen.append]
        )
        engine.fire("order", "PAY", 1)
        assert seen == []

    def test_failing_listener_does_not_undo_transition(self) -> None:
        def bad_listener(event):
            raise RuntimeError("listener exploded")

        engine = StateMachineEngine({"order": _order_model()}, listeners=[bad_listener])
        result = engine.fire("order", "PAY", 1)
        assert result.success is True
        assert engine.get_current_state("order", 1) == "PAID"

    def test_delete_state_clears_current_and_history(self, engine: StateMachineEngine) -> None:
        engine.fire("order", "PAY", 1)
        engine.delete_state("order", 1)
        assert engine.get_current_state("order", 1) == "CREATED"
        assert engine.get_state_history("order", 1) == []


class TestCanFire:
    def test_structural_reachability(self, engine: StateMachineEngine) -> None:
        assert engine.can_fire("order", "PAY", 1) is True
        assert engine.can_fire("order", "SHIP", 1) is False
        engine.fire("order", "PAY", 1)
        assert engine.can_fire("order", "SHIP", 1) is True

    def test_does_not_evaluate_guards(self) -> None:
        model = StateMachineModel(name="m", initial_state="A")
        model.add_transition(Transition("go", "A", "B", event="GO", condition=lambda ctx: False))
        engine = StateMachineEngine({"m": model})
        assert engine.can_fire("m", "GO", 1) is True
        assert engine.fire("m", "GO", 1).success is False

    def test_terminal_state_respects_reopen(self, engine: StateMachineEngine) -> None:
        engine.fire("order", "PAY", 1)
        engine.fire("order", "SHIP", 1)
        engine.fire("order", "CLOSE", 1)
        assert engine.can_fire("order", "PAY", 1) is False

    def test_unknown_machine(self, engine: StateMachineEngine) -> None:
        assert engine.can_fire("nope", "PAY", 1) is False


class TestModelHelpers:
    def test_get_state_and_missing(self) -> None:
        model = _order_model()
        assert model.get_state("PAID").name == "PAID"
        assert model.get_state("NOPE") is None

    def test_get_transitions_event_wildcard(self) -> None:
        model = _order_model()
        assert len(model.get_transitions("CREATED", None)) == 1
        assert model.get_transitions("CREATED", "NOPE") == []

    def test_register_adds_model(self) -> None:
        engine = StateMachineEngine()
        engine.register(_order_model())
        assert engine.fire("order", "PAY", 1).success is True
