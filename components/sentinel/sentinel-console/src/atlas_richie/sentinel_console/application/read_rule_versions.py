"""Read and verify immutable rule versions for one exact binding."""

from __future__ import annotations

from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_versions import RuleSetVersionCollection
from .rule_binding_errors import InvalidRuleIdentifier
from .rule_version_ports import RuleSetVersionReader


class ReadRuleVersions:
    """Delegate version authority reads and reject mismatched collections."""

    def __init__(self, reader: RuleSetVersionReader) -> None:
        self._reader = reader

    async def execute(self, binding_id: str) -> RuleSetVersionCollection:
        """Return only a complete immutable collection for the requested binding."""
        if not is_rule_binding_identifier(binding_id):
            raise InvalidRuleIdentifier("rule binding identity is invalid")
        versions = await self._reader.read_rule_versions(binding_id)
        if (
            not isinstance(versions, RuleSetVersionCollection)
            or versions.binding_id != binding_id
        ):
            raise ValueError("rule version authority returned another binding")
        return versions
