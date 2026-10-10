"""Consumer-owned ports for immutable rule-publication reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..domain.configuration_source import ConfigurationSourceProvider
from ..domain.rule_activation_plans import RuleActivationPlanPhase
from ..domain.rule_publications import (
    PublicationPhase,
    PublicationPhaseName,
    PublicationStage,
    RulePublication,
    RulePublicationCollection,
    RulePublicationReceipt,
    RulePublicationReceiptPage,
)
from ..domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
    RulePublicationTarget,
    VersionedRulePublicationTarget,
)
from ..domain.rule_versions import RuleSetVersion
from ..domain.utc_time import is_wire_utc_millisecond_instant
from .check_registered_source import SourceConnectionInput
from .mutate_rule_set import RuleOperationRejection


class RulePublicationReader(Protocol):
    """Read a complete bounded publication history for an exact binding."""

    async def read_rule_publications(
        self, binding_id: str
    ) -> RulePublicationCollection:
        """Return only publication facts belonging to the requested binding."""


class RulePublicationDetailReader(Protocol):
    """Read one publication attempt within its exact binding."""

    async def read_rule_publication(
        self, binding_id: str, publication_id: str
    ) -> RulePublication:
        """Return the exact publication or hide a missing/invisible target."""


class RulePublicationReceiptReader(Protocol):
    """Read one bounded page of instance outcomes for an exact publication."""

    async def read_rule_publication_receipts(
        self,
        binding_id: str,
        publication_id: str,
        page: int,
        page_size: int,
    ) -> RulePublicationReceiptPage:
        """Return receipt facts and counters from the requested authority."""


class RulePublicationReceiptWriter(Protocol):
    """Persist the latest trusted runtime outcome for one publication target."""

    async def record_rule_publication_receipt(
        self,
        binding_id: str,
        publication_id: str,
        receipt: RulePublicationReceipt,
    ) -> None:
        """Record a Collector-authoritative snapshot; reject stale replacements."""


class RulePublicationTargetReader(Protocol):
    """Resolve the exact write target for one binding without guessing defaults."""

    async def read_rule_publication_target(
        self, binding_id: str
    ) -> VersionedRulePublicationTarget | None:
        """Return a provider-specific target owned by this exact binding."""


class RulePublicationTargetWriter(Protocol):
    """Provision one exact binding target from a trusted server-side owner."""

    async def write_rule_publication_target(
        self,
        target: RulePublicationTarget,
        *,
        source_revision: str,
        expected_revision: str | None,
        now: datetime,
    ) -> VersionedRulePublicationTarget:
        """Create or compare-and-set a target; never expose secrets or guess keys."""


class RulePublicationTargetConflict(RuntimeError):
    """The target or registered-source revision changed before persistence."""


class RulePublicationPayloadEncoder(Protocol):
    """Encode one immutable version using the binding's selected rule profile."""

    def encode_rule_version(self, version: RuleSetVersion) -> bytes:
        """Return complete provider-neutral UTF-8 bytes or reject unsupported data."""


@dataclass(frozen=True, slots=True)
class RulePublishWorkClaim:
    """One leased, immutable publication command consumed by an application worker."""

    request_key: str
    operation_id: str
    binding_id: str
    publication_id: str
    version_id: str
    version_checksum: str
    expected_version_id: str | None
    expected_checksum: str
    expected_source_revision: str | None
    target_revision: str
    source_revision: str
    target: RulePublicationTarget
    claim_token: str
    lease_expires_at: datetime
    attempt: int
    origin_plan_id: str | None = None
    origin_phase: RuleActivationPlanPhase | None = None

    def __post_init__(self) -> None:
        text_values = (
            self.request_key,
            self.operation_id,
            self.binding_id,
            self.publication_id,
            self.version_id,
            self.version_checksum,
            self.expected_checksum,
            self.claim_token,
            self.target_revision,
            self.source_revision,
        )
        if any(
            not isinstance(value, str) or not value.strip() for value in text_values
        ):
            raise ValueError("publish work claim identity is invalid")
        if self.expected_version_id is not None and (
            not isinstance(self.expected_version_id, str)
            or not self.expected_version_id.strip()
        ):
            raise ValueError("publish work baseline identity is invalid")
        if (
            self.expected_source_revision is not None
            and not self.expected_source_revision.strip()
        ):
            raise ValueError("publish work source revision is invalid")
        if not is_wire_utc_millisecond_instant(self.lease_expires_at):
            raise ValueError("publish work lease expiry is invalid")
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("publish work attempt is invalid")
        if (
            not isinstance(
                self.target,
                (NacosRulePublicationTarget, ConsulRulePublicationTarget),
            )
            or self.target.binding_id != self.binding_id
        ):
            raise ValueError("publish target does not match its exact binding")
        if (self.origin_plan_id is None) != (self.origin_phase is None):
            raise ValueError("scheduled publication origin is incomplete")
        if self.origin_plan_id is not None and (
            not self.origin_plan_id.strip()
            or not isinstance(self.origin_phase, RuleActivationPlanPhase)
        ):
            raise ValueError("scheduled publication origin is invalid")


class RulePublishOutbox(Protocol):
    """Claim, fence, and finalize durable publish commands."""

    async def claim_ready(
        self,
        *,
        now: datetime,
        lease_expires_at: datetime,
        supported_providers: frozenset[ConfigurationSourceProvider],
        limit: int = 1,
    ) -> tuple[RulePublishWorkClaim, ...]: ...

    async def renew_claim(
        self,
        claim: RulePublishWorkClaim,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> RulePublishWorkClaim: ...

    async def advance_claimed_phase(
        self,
        claim: RulePublishWorkClaim,
        phase_name: PublicationPhaseName,
        *,
        expected_state: PublicationStage,
        next_phase: PublicationPhase,
    ) -> RulePublication: ...

    async def complete_claimed_publication(
        self, claim: RulePublishWorkClaim, *, completed_at: datetime
    ) -> object: ...

    async def reject_claimed_publication(
        self,
        claim: RulePublishWorkClaim,
        *,
        rejected_at: datetime,
        reason: RuleOperationRejection,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class RuleConfigurationSnapshot:
    """Exact provider value and CAS revision, or both absent for create-only."""

    revision: str | None
    value: bytes | None

    def __post_init__(self) -> None:
        if (self.revision is None) != (self.value is None):
            raise ValueError("provider snapshot revision and value must agree")
        if self.revision is not None and (
            not isinstance(self.revision, str) or not self.revision.strip()
        ):
            raise ValueError("provider snapshot revision is invalid")
        if self.value is not None and not isinstance(self.value, bytes):
            raise ValueError("provider snapshot value is invalid")


class RulePublicationProvider(Protocol):
    """Provider adapter for exact reads and compare-and-set writes."""

    @property
    def supported_providers(self) -> frozenset[ConfigurationSourceProvider]:
        """Finite provider set this adapter can safely execute."""

    async def read_configuration(
        self,
        connection: SourceConnectionInput,
        target: RulePublicationTarget,
    ) -> RuleConfigurationSnapshot: ...

    async def write_configuration_if_revision(
        self,
        connection: SourceConnectionInput,
        target: RulePublicationTarget,
        *,
        expected_revision: str | None,
        value: bytes,
    ) -> str: ...


class RulePublicationProviderConflict(RuntimeError):
    """Provider rejected a stale baseline without applying the candidate."""


class RulePublicationProviderRejected(RuntimeError):
    """Provider authoritatively rejected the write authorization."""


class RulePublicationProviderUnavailable(RuntimeError):
    """Provider could not be reached before dispatching a write."""


class RulePublicationProviderOutcomeUnknown(RuntimeError):
    """Write may have been dispatched but its outcome is not authoritative."""


class RulePublicationProfileUnsupported(RuntimeError):
    """The immutable version does not use this encoder's bound profile."""


class RulePublicationValueUnsupported(RuntimeError):
    """A typed rule contains fields that this Sentinel wire profile cannot encode."""


class RulePublicationRecorder(Protocol):
    """Persist one publication and compare-and-set its independent phases."""

    async def create_rule_publication(self, publication: RulePublication) -> None:
        """Persist a new attempt after confirming its immutable version baseline."""

    async def advance_rule_publication_phase(
        self,
        binding_id: str,
        publication_id: str,
        phase_name: PublicationPhaseName,
        *,
        expected_state: PublicationStage,
        next_phase: PublicationPhase,
    ) -> RulePublication:
        """CAS one phase and return the complete, newly persisted fact."""


class RulePublicationAuthorityUnavailable(RuntimeError):
    """The publication authority cannot return trustworthy facts."""


class RulePublicationNotFound(LookupError):
    """The binding or publication does not exist or is not visible."""


class RulePublicationConflict(RuntimeError):
    """A publication identity or phase no longer matches its expected state."""


class RulePublicationRateLimited(RuntimeError):
    """The authority declined a read within its rate budget."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or retry_after_ms < 0:
            raise ValueError("retry delay must be a non-negative integer")
        self.retry_after_ms = retry_after_ms
        super().__init__("rule publication read rate limited")
