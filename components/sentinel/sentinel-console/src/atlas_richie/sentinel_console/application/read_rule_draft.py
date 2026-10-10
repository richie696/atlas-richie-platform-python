"""Read and verify one persisted draft in an exact binding scope."""

from __future__ import annotations

from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_drafts import StoredRuleDraft
from .rule_binding_errors import InvalidRuleIdentifier
from .rule_draft_detail_ports import RuleDraftDetailReader


class ReadRuleDraft:
    """Delegate to the durable authority and verify both path identities."""

    def __init__(self, reader: RuleDraftDetailReader) -> None:
        self._reader = reader

    async def execute(self, binding_id: str, draft_id: str) -> StoredRuleDraft:
        """Return only the requested draft owned by the requested binding."""
        if not is_rule_binding_identifier(binding_id) or not is_rule_binding_identifier(
            draft_id
        ):
            raise InvalidRuleIdentifier("rule draft identity is invalid")
        draft = await self._reader.read_rule_draft(binding_id, draft_id)
        if (
            not isinstance(draft, StoredRuleDraft)
            or draft.binding_id != binding_id
            or draft.id != draft_id
        ):
            raise ValueError("rule draft authority returned a mismatched identity")
        return draft

