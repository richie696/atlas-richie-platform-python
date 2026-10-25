"""Read and verify one exact immutable rule version."""

from __future__ import annotations

from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_versions import RuleSetVersion
from .rule_binding_errors import InvalidRuleIdentifier
from .rule_version_ports import RuleSetVersionDetailReader


class ReadRuleVersion:
    """Delegate a detail read and reject mismatched identities."""

    def __init__(self, reader: RuleSetVersionDetailReader) -> None:
        self._reader = reader

    async def execute(self, binding_id: str, version_id: str) -> RuleSetVersion:
        """Return a version whose source and identity match the request exactly."""
        if not all(
            is_rule_binding_identifier(value) for value in (binding_id, version_id)
        ):
            raise InvalidRuleIdentifier("rule version identity is invalid")
        version = await self._reader.read_rule_version(binding_id, version_id)
        if (
            not isinstance(version, RuleSetVersion)
            or version.binding_id != binding_id
            or version.id != version_id
        ):
            raise ValueError("rule version authority returned another version")
        return version
