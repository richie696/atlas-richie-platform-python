"""Read the exact provider destination configured for one rule binding."""

from __future__ import annotations

from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_publication_targets import VersionedRulePublicationTarget
from .rule_binding_errors import InvalidRuleIdentifier
from .rule_publication_ports import RulePublicationTargetReader


class ReadRulePublicationTarget:
    """Validate binding identity and delegate to the authoritative target reader."""

    def __init__(self, reader: RulePublicationTargetReader) -> None:
        self._reader = reader

    async def execute(
        self, binding_id: str
    ) -> VersionedRulePublicationTarget | None:
        """Return an exact versioned target or ``None`` when not configured."""
        if not is_rule_binding_identifier(binding_id):
            raise InvalidRuleIdentifier("rule binding identifier is invalid")
        target = await self._reader.read_rule_publication_target(binding_id)
        if target is not None and (
            not isinstance(target, VersionedRulePublicationTarget)
            or target.target.binding_id != binding_id
        ):
            raise ValueError("publication target authority returned another binding")
        return target
