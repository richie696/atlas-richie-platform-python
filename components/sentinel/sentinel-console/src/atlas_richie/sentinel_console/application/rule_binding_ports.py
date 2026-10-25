"""Consumer-owned authority boundary for rule binding directory reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from ..domain.rule_bindings import (
    RuleBinding,
    RuleBindingPage,
    RuleBindingQuery,
    RuleBindingScopeCatalog,
    RuleKind,
)
from ..domain.rule_publication_targets import RulePublicationTarget


class RuleBindingDirectoryReader(Protocol):
    """Read the authoritative, filtered rule-binding directory page."""

    async def read_rule_bindings(self, query: RuleBindingQuery) -> RuleBindingPage:
        """Return a page whose query exactly matches the submitted filters."""


class RuleBindingScopeReader(Protocol):
    """Read environment/application scopes proven by registered rule bindings."""

    async def read_rule_binding_scopes(self) -> RuleBindingScopeCatalog:
        """Return a complete bounded scope snapshot, including a valid empty snapshot."""


class RuleBindingScopeAuthorityUnavailable(RuntimeError):
    """The persisted rule-binding metadata cannot provide a trustworthy scope catalog."""


class RuleBindingAuthorityUnavailable(RuntimeError):
    """The binding authority cannot currently provide a trustworthy page."""


class RuleBindingTargetNotFound(LookupError):
    """The requested environment or application does not exist."""


class RuleBindingRateLimited(RuntimeError):
    """The authority declined this read within its current rate budget."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or retry_after_ms < 0:
            raise ValueError("retry delay must be a non-negative integer")
        self.retry_after_ms = retry_after_ms
        super().__init__("rule binding directory read rate limited")


@dataclass(frozen=True, slots=True)
class RegisterRuleBinding:
    """Create one Console binding and its exact, credential-free provider target."""

    request_key: str
    binding_id: str
    environment_id: str
    app_id: str
    kind: RuleKind
    profile: str
    source_revision: str
    target: RulePublicationTarget

    def __post_init__(self) -> None:
        identifiers = (
            self.request_key,
            self.binding_id,
            self.environment_id,
            self.app_id,
            self.profile,
            self.source_revision,
        )
        if any(
            not isinstance(value, str) or not value.strip() for value in identifiers
        ):
            raise ValueError("rule binding registration identity is invalid")
        if not isinstance(self.kind, RuleKind):
            raise ValueError("rule binding registration kind is invalid")
        if self.target.binding_id != self.binding_id:
            raise ValueError("rule binding target identity does not match")


class RuleBindingRegistrationAuthority(Protocol):
    """Atomically persist binding metadata, target mapping, receipt, and audit."""

    async def register_rule_binding(
        self,
        command: RegisterRuleBinding,
        *,
        actor_id: str,
        session_digest: str,
        csrf_digest: str,
        request_id: str,
        now: datetime,
    ) -> RuleBinding:
        """Return the original binding for an exact, safely repeatable command."""


class RuleBindingRegistrationReceiptStatus(StrEnum):
    """Finite outcome of a read-only binding registration receipt lookup."""

    COMPLETED = "completed"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class RuleBindingRegistrationReceipt:
    """Credential-free result for one actor-, binding-, and request-key lookup."""

    request_key: str
    binding_id: str
    status: RuleBindingRegistrationReceiptStatus
    binding: RuleBinding | None

    def __post_init__(self) -> None:
        if not self.request_key.strip() or not self.binding_id.strip():
            raise ValueError("binding registration receipt identity is invalid")
        if self.status is RuleBindingRegistrationReceiptStatus.COMPLETED:
            if self.binding is None or self.binding.id != self.binding_id:
                raise ValueError("completed binding receipt must contain its binding")
        elif self.status is RuleBindingRegistrationReceiptStatus.NOT_FOUND:
            if self.binding is not None:
                raise ValueError("not-found binding receipt cannot contain a binding")
        else:
            raise ValueError("binding registration receipt status is invalid")


class RuleBindingRegistrationReceiptReader(Protocol):
    """Read an original safe registration receipt after current admin reauthorization."""

    async def read_rule_binding_registration(
        self,
        binding_id: str,
        request_key: str,
        *,
        actor_id: str,
        session_digest: str,
        now: datetime,
    ) -> RuleBinding | None:
        """Return only the exact actor/binding/key receipt, or no visible operation."""


class RuleBindingRegistrationConflict(RuntimeError):
    """A binding scope, target, or idempotency key conflicts with stored facts."""


class RuleBindingRegistrationIdempotencyConflict(RuntimeError):
    """An idempotency key was reused for a different registration payload."""


class RuleBindingRegistrationForbidden(RuntimeError):
    """The actor/session cannot register or recover this binding operation."""


class RuleBindingRegistrationUnauthenticated(RuntimeError):
    """The session expired before the binding transaction could commit."""


class RuleBindingRegistrationAuthorityUnavailable(RuntimeError):
    """The durable binding-registration authority is unavailable."""
