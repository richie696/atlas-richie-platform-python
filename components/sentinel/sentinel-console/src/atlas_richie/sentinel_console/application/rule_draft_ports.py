"""Consumer-owned authority boundary for persisted rule-draft reads."""

from __future__ import annotations

from typing import Protocol

from ..domain.rule_drafts import RuleDraftCollection


class RuleDraftReader(Protocol):
    """Read every persisted draft belonging to one exact rule binding."""

    async def read_rule_drafts(self, binding_id: str) -> RuleDraftCollection:
        """Return a complete, bounded collection bound to the requested source."""


class RuleDraftAuthorityUnavailable(RuntimeError):
    """The durable draft authority cannot provide a trustworthy collection."""


class RuleDraftNotFound(LookupError):
    """The binding is missing or is not visible to the current session."""


class RuleDraftRateLimited(RuntimeError):
    """The durable draft authority declined this read within its rate budget."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or retry_after_ms < 0:
            raise ValueError("retry delay must be a non-negative integer")
        self.retry_after_ms = retry_after_ms
        super().__init__("rule draft collection read rate limited")

