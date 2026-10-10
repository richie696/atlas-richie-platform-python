"""Consumer-owned authority boundary for one persisted rule-draft read."""

from __future__ import annotations

from typing import Protocol

from ..domain.rule_drafts import StoredRuleDraft


class RuleDraftDetailReader(Protocol):
    """Read one persisted draft within an exact binding scope."""

    async def read_rule_draft(
        self, binding_id: str, draft_id: str
    ) -> StoredRuleDraft:
        """Return only the requested draft owned by the requested binding."""


class RuleDraftDetailAuthorityUnavailable(RuntimeError):
    """The durable draft authority cannot provide a trustworthy draft."""


class RuleDraftDetailNotFound(LookupError):
    """The draft is missing, belongs elsewhere, or is not visible to this session."""


class RuleDraftDetailRateLimited(RuntimeError):
    """The durable draft authority declined this read within its rate budget."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or retry_after_ms < 0:
            raise ValueError("retry delay must be a non-negative integer")
        self.retry_after_ms = retry_after_ms
        super().__init__("rule draft detail read rate limited")

