"""Read and verify one complete authority snapshot for an exact binding."""

from __future__ import annotations

from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_snapshots import RuleSetSnapshot
from .rule_binding_errors import InvalidRuleIdentifier
from .rule_snapshot_ports import RuleSetSnapshotReader


class ReadRuleSetSnapshot:
    """Delegate to the rule authority and reject another binding's data."""

    def __init__(self, reader: RuleSetSnapshotReader) -> None:
        self._reader = reader

    async def execute(self, binding_id: str) -> RuleSetSnapshot:
        """Return a complete snapshot whose exact binding matches the path."""
        if not is_rule_binding_identifier(binding_id):
            raise InvalidRuleIdentifier("rule binding identity is invalid")
        snapshot = await self._reader.read_rule_set_snapshot(binding_id)
        if (
            not isinstance(snapshot, RuleSetSnapshot)
            or snapshot.binding.id != binding_id
        ):
            raise ValueError("rule authority returned a mismatched binding")
        return snapshot
