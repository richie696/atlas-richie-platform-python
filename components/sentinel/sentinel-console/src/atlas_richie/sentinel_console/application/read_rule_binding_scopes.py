"""Read rule selectors from the rule-binding authority, independently of metrics."""

from __future__ import annotations

from ..domain.rule_bindings import RuleBindingScopeCatalog
from .rule_binding_ports import (
    RuleBindingScopeAuthorityUnavailable,
    RuleBindingScopeReader,
)


class ReadRuleBindingScopes:
    """Validate and return the complete environment/application scope snapshot."""

    def __init__(self, reader: RuleBindingScopeReader) -> None:
        self._reader = reader

    async def execute(self) -> RuleBindingScopeCatalog:
        """Read the authority without consulting the Reporter/observation catalog."""
        snapshot = await self._reader.read_rule_binding_scopes()
        if not isinstance(snapshot, RuleBindingScopeCatalog):
            raise RuleBindingScopeAuthorityUnavailable(
                "rule binding scope authority returned an invalid snapshot"
            )
        return snapshot
