"""Read and verify publication history for one exact rule binding."""

from __future__ import annotations

from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_publications import RulePublicationCollection
from .rule_binding_errors import InvalidRuleIdentifier
from .rule_publication_ports import RulePublicationReader


class ReadRulePublications:
    """Delegate publication history reads and validate binding ownership."""

    def __init__(self, reader: RulePublicationReader) -> None:
        self._reader = reader

    async def execute(self, binding_id: str) -> RulePublicationCollection:
        """Return only a collection whose binding matches the request."""
        if not is_rule_binding_identifier(binding_id):
            raise InvalidRuleIdentifier("rule binding identity is invalid")
        publications = await self._reader.read_rule_publications(binding_id)
        if (
            not isinstance(publications, RulePublicationCollection)
            or publications.binding_id != binding_id
        ):
            raise ValueError("publication authority returned another binding")
        return publications
