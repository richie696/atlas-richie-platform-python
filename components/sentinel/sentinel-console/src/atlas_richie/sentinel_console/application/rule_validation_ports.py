"""Consumer-owned profile validation and durable receipt capabilities."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..domain.rule_bindings import RuleBinding
from ..domain.rule_candidates import RuleSetCandidate
from ..domain.rule_validation import (
    RuleCandidateValidationReceipt,
    RuleValidationIssue,
)


class RuleValidationAuthorityUnavailable(RuntimeError):
    """The selected profile validator or receipt store is unavailable."""


class RuleCandidateConflict(RuntimeError):
    """The candidate no longer targets its exact source baseline."""


class RuleCandidateProfileValidator(Protocol):
    """Validate candidate semantics against one binding's provider profile."""

    def validate_candidate(
        self,
        binding: RuleBinding,
        candidate: RuleSetCandidate,
    ) -> tuple[RuleValidationIssue, ...]:
        """Return bounded issues; never publish or mutate configuration."""


class RuleValidationReceiptWriter(Protocol):
    """Persist validation evidence before the endpoint reports its result."""

    async def record_validation(
        self,
        receipt: RuleCandidateValidationReceipt,
        *,
        actor_id: str,
        request_id: str,
        created_at: datetime,
    ) -> None:
        """Atomically persist the receipt and its bounded audit fact."""


class RuleValidationReceiptReader(Protocol):
    """Read persisted validation evidence for later freeze-command checks."""

    async def read_validation(
        self, validation_id: str
    ) -> RuleCandidateValidationReceipt | None:
        """Return a receipt by exact identity, or ``None`` if not found."""
