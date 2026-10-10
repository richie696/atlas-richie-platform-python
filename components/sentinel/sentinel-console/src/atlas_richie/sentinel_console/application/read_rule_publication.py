"""Read and verify one exact publication attempt."""

from __future__ import annotations

from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_publications import RulePublication
from .rule_binding_errors import InvalidRuleIdentifier
from .rule_publication_ports import RulePublicationDetailReader


class ReadRulePublication:
    """Delegate a publication read and reject mismatched object identity."""

    def __init__(self, reader: RulePublicationDetailReader) -> None:
        self._reader = reader

    async def execute(self, binding_id: str, publication_id: str) -> RulePublication:
        """Return only the requested publication within its exact binding."""
        if not all(
            is_rule_binding_identifier(value) for value in (binding_id, publication_id)
        ):
            raise InvalidRuleIdentifier("publication identity is invalid")
        publication = await self._reader.read_rule_publication(
            binding_id, publication_id
        )
        if (
            not isinstance(publication, RulePublication)
            or publication.binding_id != binding_id
            or publication.id != publication_id
        ):
            raise ValueError("publication authority returned another publication")
        return publication
