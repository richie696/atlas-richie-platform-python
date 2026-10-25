"""Application contracts for rule-set commands and original-operation reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypeAlias

from ..domain.rule_activation_plans import RuleActivationPlan
from ..domain.rule_candidates import RuleSetCandidate
from ..domain.rule_drafts import StoredRuleDraft
from ..domain.rule_publications import RulePublication
from ..domain.rule_versions import RuleSetVersion
from ..domain.rule_bindings import RuleBinding
from ..domain.rule_publication_targets import (
    RulePublicationTarget,
    VersionedRulePublicationTarget,
)


class RuleMutationKind(StrEnum):
    """The finite, independent rule-workflow commands supported by the API."""

    SAVE_DRAFT = "save_draft"
    DELETE_DRAFT = "delete_draft"
    FREEZE_VERSION = "freeze_version"
    PUBLISH = "publish"
    CREATE_PLAN = "create_plan"
    CANCEL_PLAN = "cancel_plan"
    CONFIGURE_TARGET = "configure_target"


@dataclass(frozen=True, slots=True)
class SaveRuleDraft:
    """Create or conditionally replace a mutable draft from a complete candidate."""

    draft_id: str | None
    expected_revision: str | None
    candidate: RuleSetCandidate


@dataclass(frozen=True, slots=True)
class DeleteRuleDraft:
    """Delete one draft only at its exact revision."""

    draft_id: str
    expected_revision: str


@dataclass(frozen=True, slots=True)
class FreezeRuleVersion:
    """Freeze a draft revision and validation receipt into an immutable version."""

    draft_id: str
    expected_revision: str
    validation_id: str
    candidate_checksum: str
    name: str
    note: str


@dataclass(frozen=True, slots=True)
class PublishRuleVersion:
    """Publish an immutable version against an explicit source baseline."""

    version_id: str
    version_checksum: str
    expected_version_id: str | None
    expected_checksum: str
    expected_source_revision: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class CreateRuleActivationPlan:
    """Persist a binding-scoped activation and restoration schedule."""

    version_id: str
    restore_version_id: str
    activate_at: datetime
    deactivate_at: datetime
    time_zone: str


@dataclass(frozen=True, slots=True)
class CancelRuleActivationPlan:
    """Cancel one pending plan at its exact revision."""

    plan_id: str
    expected_revision: str
    reason: str


@dataclass(frozen=True, slots=True)
class ConfigureRulePublicationTarget:
    """Create or compare-and-set one credential-free exact binding destination."""

    expected_source_revision: str
    expected_target_revision: str | None
    target: RulePublicationTarget


RuleMutation: TypeAlias = (
    SaveRuleDraft
    | DeleteRuleDraft
    | FreezeRuleVersion
    | PublishRuleVersion
    | CreateRuleActivationPlan
    | CancelRuleActivationPlan
    | ConfigureRulePublicationTarget
)


class RuleOperationStatus(StrEnum):
    """A safe observation state for a previously accepted command."""

    PENDING = "pending"
    NOT_FOUND = "not-found"
    COMPLETED = "completed"
    REJECTED = "rejected"


class RuleOperationRejection(StrEnum):
    """Finite command rejection reasons safe for the browser contract."""

    VALIDATION = "validation"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class FrozenRuleVersionResult:
    """The exact draft revision and immutable version produced by a freeze."""

    draft_id: str
    draft_revision: str
    version: RuleSetVersion


RuleMutationResult: TypeAlias = (
    StoredRuleDraft
    | FrozenRuleVersionResult
    | RuleSetVersion
    | RulePublication
    | RuleActivationPlan
    | VersionedRulePublicationTarget
    | str
)


@dataclass(frozen=True, slots=True)
class RuleMutationCommand:
    """One path-bound, idempotent mutation request with a typed payload."""

    binding_id: str
    request_key: str
    mutation: RuleMutation


@dataclass(frozen=True, slots=True)
class RuleMutationOperation:
    """Safe result lookup bound to one actor, binding and request key."""

    binding_id: str
    request_key: str
    status: RuleOperationStatus
    mutation_kind: RuleMutationKind | None = None
    result: RuleMutationResult | None = None
    reason: RuleOperationRejection | None = None

    def __post_init__(self) -> None:
        if not self.binding_id or not self.request_key:
            raise ValueError("rule operation identity is required")
        if not isinstance(self.status, RuleOperationStatus):
            raise ValueError("rule operation status is unsupported")
        if self.mutation_kind is not None and not isinstance(
            self.mutation_kind, RuleMutationKind
        ):
            raise ValueError("rule operation kind is unsupported")
        if self.status is RuleOperationStatus.COMPLETED:
            if (
                self.mutation_kind is None
                or self.result is None
                or self.reason is not None
            ):
                raise ValueError("completed rule operation requires one typed result")
        elif self.status is RuleOperationStatus.REJECTED:
            if self.reason is None or self.result is not None:
                raise ValueError("rejected rule operation requires one finite reason")
        elif (
            self.mutation_kind is not None
            or self.result is not None
            or self.reason is not None
        ):
            raise ValueError("incomplete rule operation cannot carry a terminal result")


class RuleMutationAuthorityUnavailable(RuntimeError):
    """The durable rule mutation authority cannot provide a trustworthy result."""


class RuleMutationForbidden(RuntimeError):
    """The current actor cannot mutate or inspect this rule operation."""


class RuleMutationUnauthenticated(RuntimeError):
    """The session became inactive before the rule command was committed."""


class RuleMutationIdempotencyConflict(RuntimeError):
    """A request key was reused for different rule-command input."""


class RuleMutationRateLimited(RuntimeError):
    """The rule authority declined the request within its rate budget."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or not 0 <= retry_after_ms <= 300_000:
            raise ValueError("retry delay must be bounded")
        self.retry_after_ms = retry_after_ms
        super().__init__("rule mutation rate limited")


class RuleMutationAuthority(Protocol):
    """Persist same-session command retries and query actor-owned receipts."""

    async def mutate(
        self,
        command: RuleMutationCommand,
        *,
        actor_id: str,
        session_digest: str,
        csrf_digest: str,
        request_id: str,
        now: datetime,
    ) -> RuleMutationOperation:
        """Reauthorize and atomically persist the command's own workflow facts."""

    async def read_operation(
        self,
        binding_id: str,
        request_key: str,
        *,
        actor_id: str,
        session_digest: str,
    ) -> RuleMutationOperation | None:
        """Reauthorize the current session, then read its actor-owned binding/key receipt."""


class RuleMutationBindingReader(Protocol):
    """Resolve one exact rule binding from its authoritative directory."""

    async def read_rule_binding(self, binding_id: str) -> RuleBinding | None:
        """Return the exact binding, or ``None`` when that identity is absent."""
