"""Consumer-owned authority boundary for complete rule snapshot reads."""

from __future__ import annotations

from typing import Protocol

from ..domain.rule_snapshots import RuleSetSnapshot


class RuleSetSnapshotReader(Protocol):
    """Read the complete authoritative rule set for one binding identity."""

    async def read_rule_set_snapshot(self, binding_id: str) -> RuleSetSnapshot:
        """Return only the requested binding's latest source snapshot."""


class RuleSetSnapshotAuthorityUnavailable(RuntimeError):
    """The selected rule source cannot provide a trustworthy snapshot."""


class RuleSetSnapshotNotFound(LookupError):
    """The binding is missing or inaccessible to the current session."""


class RuleSetSnapshotRateLimited(RuntimeError):
    """The source authority declined this read within its rate budget."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or retry_after_ms < 0:
            raise ValueError("retry delay must be a non-negative integer")
        self.retry_after_ms = retry_after_ms
        super().__init__("rule set snapshot read rate limited")

