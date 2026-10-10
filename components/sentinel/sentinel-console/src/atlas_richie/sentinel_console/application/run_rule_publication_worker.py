"""Execute one durable rule publication through fenced provider phases."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Callable, Protocol

from ..domain.rule_publications import (
    PublicationPhase,
    PublicationPhaseName,
    PublicationReason,
    PublicationStage,
    RulePublication,
)
from ..domain.configuration_source import ConfigurationSourceProvider
from ..domain.rule_publication_targets import RulePublicationTarget
from ..domain.rule_versions import RuleSetVersion
from ..domain.utc_time import is_wire_utc_millisecond_instant
from .mutate_rule_set import RuleOperationRejection
from .read_rule_publication import ReadRulePublication
from .read_rule_version import ReadRuleVersion
from .rule_version_ports import (
    RuleSetVersionAuthorityUnavailable,
    RuleSetVersionNotFound,
)
from .resolve_registered_source_connection import (
    RegisteredSourceConnectionUnavailable,
    ResolveRegisteredSourceConnection,
)
from .rule_publication_ports import (
    RuleConfigurationSnapshot,
    RulePublicationPayloadEncoder,
    RulePublicationProvider,
    RulePublicationProviderConflict,
    RulePublicationProviderOutcomeUnknown,
    RulePublicationProfileUnsupported,
    RulePublicationProviderRejected,
    RulePublicationProviderUnavailable,
    RulePublicationValueUnsupported,
    RulePublishOutbox,
    RulePublishWorkClaim,
)

_MAX_LEASE = timedelta(minutes=5)
_MAX_CLAIM_BATCH = 100
_MIN_RENEWAL_INTERVAL_SECONDS = 0.001


class _RulePublishClaimView(Protocol):
    """Read-only fields shared by a stored claim and its live lease view."""

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


@dataclass(slots=True)
class _ActiveRulePublishClaim:
    """Keep the newest fenced claim snapshot while one operation is running."""

    current_claim: RulePublishWorkClaim

    @property
    def request_key(self) -> str:
        return self.current_claim.request_key

    @property
    def operation_id(self) -> str:
        return self.current_claim.operation_id

    @property
    def binding_id(self) -> str:
        return self.current_claim.binding_id

    @property
    def publication_id(self) -> str:
        return self.current_claim.publication_id

    @property
    def version_id(self) -> str:
        return self.current_claim.version_id

    @property
    def version_checksum(self) -> str:
        return self.current_claim.version_checksum

    @property
    def expected_version_id(self) -> str | None:
        return self.current_claim.expected_version_id

    @property
    def expected_checksum(self) -> str:
        return self.current_claim.expected_checksum

    @property
    def expected_source_revision(self) -> str | None:
        return self.current_claim.expected_source_revision

    @property
    def target_revision(self) -> str:
        return self.current_claim.target_revision

    @property
    def source_revision(self) -> str:
        return self.current_claim.source_revision

    @property
    def target(self) -> RulePublicationTarget:
        return self.current_claim.target

    @property
    def claim_token(self) -> str:
        return self.current_claim.claim_token

    @property
    def lease_expires_at(self) -> datetime:
        return self.current_claim.lease_expires_at

    @property
    def attempt(self) -> int:
        return self.current_claim.attempt


class RulePublicationWorkerOutcome(StrEnum):
    """Bounded result of one claimed publication attempt."""

    COMPLETED = "completed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class RunRulePublicationWorker:
    """Validate frozen facts, CAS-write and verify exact provider bytes.

    One worker instance is bound to one selected provider adapter and one rule
    profile encoder. Deployment composition chooses both; the worker never
    guesses a provider, source, or target from ambient configuration.
    """

    def __init__(
        self,
        *,
        outbox: RulePublishOutbox,
        publication_reader: ReadRulePublication,
        version_reader: ReadRuleVersion,
        source_connection_resolver: ResolveRegisteredSourceConnection,
        payload_encoder: RulePublicationPayloadEncoder,
        provider: RulePublicationProvider,
        clock: Callable[[], datetime],
        lease_duration: timedelta = timedelta(seconds=60),
    ) -> None:
        if not timedelta(milliseconds=1) <= lease_duration <= _MAX_LEASE:
            raise ValueError("publish worker lease duration is invalid")
        self._outbox = outbox
        self._publication_reader = publication_reader
        self._version_reader = version_reader
        self._source_connection_resolver = source_connection_resolver
        self._payload_encoder = payload_encoder
        self._provider = provider
        supported_providers = getattr(provider, "supported_providers", None)
        if (
            not isinstance(supported_providers, frozenset)
            or not supported_providers
            or any(
                not isinstance(item, ConfigurationSourceProvider)
                for item in supported_providers
            )
        ):
            raise ValueError("publication provider must declare supported providers")
        self._supported_providers = supported_providers
        self._clock = clock
        self._lease_duration = lease_duration

    async def run_once(
        self, *, limit: int = 1
    ) -> tuple[RulePublicationWorkerOutcome, ...]:
        """Claim work just before execution so queued work cannot lose its lease."""
        if type(limit) is not int or not 1 <= limit <= _MAX_CLAIM_BATCH:
            raise ValueError("publish worker limit is outside the supported range")
        outcomes = []
        seen_request_keys: set[str] = set()
        for _ in range(limit):
            now = _millisecond_instant(self._clock())
            claims = await self._outbox.claim_ready(
                now=now,
                lease_expires_at=now + self._lease_duration,
                supported_providers=self._supported_providers,
                limit=1,
            )
            if not claims:
                break
            if len(claims) != 1:
                raise RuntimeError("publish outbox exceeded the requested claim limit")
            claim = claims[0]
            if claim.request_key in seen_request_keys:
                break
            seen_request_keys.add(claim.request_key)
            outcomes.append(await self._execute(claim))
        return tuple(outcomes)

    async def _execute(
        self, claim: RulePublishWorkClaim
    ) -> RulePublicationWorkerOutcome:
        active_claim = _ActiveRulePublishClaim(claim)
        stop_renewal = asyncio.Event()
        execution = asyncio.create_task(self._execute_claimed(active_claim))
        renewal = asyncio.create_task(
            self._renew_claim_until_stopped(active_claim, stop_renewal)
        )
        try:
            done, _pending = await asyncio.wait(
                (execution, renewal), return_when=asyncio.FIRST_COMPLETED
            )
            if renewal in done and execution not in done:
                error = renewal.exception()
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
                if error is None:
                    raise RuntimeError("publish claim renewal stopped unexpectedly")
                raise error
            return await execution
        finally:
            stop_renewal.set()
            if not renewal.done():
                renewal.cancel()
            if not execution.done():
                execution.cancel()
            await asyncio.gather(renewal, execution, return_exceptions=True)

    async def _renew_claim_until_stopped(
        self,
        claim: _ActiveRulePublishClaim,
        stop: asyncio.Event,
    ) -> None:
        interval = max(
            _MIN_RENEWAL_INTERVAL_SECONDS,
            self._lease_duration.total_seconds() / 3,
        )
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                now = _millisecond_instant(self._clock())
                claim.current_claim = await self._outbox.renew_claim(
                    claim.current_claim,
                    now=now,
                    lease_expires_at=now + self._lease_duration,
                )

    async def _execute_claimed(
        self, claim: _RulePublishClaimView
    ) -> RulePublicationWorkerOutcome:
        publication = await self._publication_reader.execute(
            claim.binding_id, claim.publication_id
        )
        terminal_outcome = await self._finalize_known_failure(claim, publication)
        if terminal_outcome is not None:
            return terminal_outcome
        version = await self._version_reader.execute(claim.binding_id, claim.version_id)
        if not _claim_matches_version(claim, version, publication):
            return await self._preflight_failure(
                claim,
                publication,
                PublicationReason.CONFLICT,
                RuleOperationRejection.CONFLICT,
            )

        try:
            candidate = self._payload_encoder.encode_rule_version(version)
            baseline = await self._read_baseline(claim)
            connection = await self._source_connection_resolver.execute(
                claim.target.source_id,
                claim.source_revision,
                claim.target.provider,
            )
            current = await self._provider.read_configuration(
                connection, claim.target
            )
        except RegisteredSourceConnectionUnavailable:
            return await self._preflight_failure(
                claim,
                publication,
                PublicationReason.UNAVAILABLE,
                RuleOperationRejection.UNAVAILABLE,
            )
        except RulePublicationProviderRejected:
            return await self._preflight_failure(
                claim,
                publication,
                PublicationReason.REJECTED,
                RuleOperationRejection.UNSUPPORTED,
            )
        except RulePublicationProviderUnavailable:
            return await self._preflight_failure(
                claim,
                publication,
                PublicationReason.UNAVAILABLE,
                RuleOperationRejection.UNAVAILABLE,
            )
        except (RulePublicationProviderOutcomeUnknown, TimeoutError, OSError):
            return await self._preflight_failure(
                claim,
                publication,
                PublicationReason.UNAVAILABLE,
                RuleOperationRejection.UNAVAILABLE,
            )
        except (RulePublicationProfileUnsupported, RulePublicationValueUnsupported):
            return await self._preflight_failure(
                claim,
                publication,
                PublicationReason.UNSUPPORTED,
                RuleOperationRejection.VALIDATION,
            )
        except RuleSetVersionNotFound:
            return await self._preflight_failure(
                claim,
                publication,
                PublicationReason.CONFLICT,
                RuleOperationRejection.NOT_FOUND,
            )
        except ValueError:
            return await self._preflight_failure(
                claim,
                publication,
                PublicationReason.CONFLICT,
                RuleOperationRejection.CONFLICT,
            )
        except (RuleSetVersionAuthorityUnavailable, OSError, TimeoutError):
            return await self._preflight_failure(
                claim,
                publication,
                PublicationReason.UNAVAILABLE,
                RuleOperationRejection.UNAVAILABLE,
            )

        if current.value != baseline and not (
            publication.configuration_write.state
            in (PublicationStage.RUNNING, PublicationStage.UNKNOWN)
            and current.value == candidate
        ):
            if publication.configuration_write.state in {
                PublicationStage.RUNNING,
                PublicationStage.UNKNOWN,
            }:
                if publication.configuration_write.state is PublicationStage.RUNNING:
                    await self._advance(
                        claim,
                        publication,
                        PublicationPhaseName.CONFIGURATION_WRITE,
                        PublicationStage.RUNNING,
                        PublicationStage.UNKNOWN,
                        PublicationReason.UNKNOWN,
                    )
                return RulePublicationWorkerOutcome.UNKNOWN
            return await self._preflight_failure(
                claim,
                publication,
                PublicationReason.CONFLICT,
                RuleOperationRejection.CONFLICT,
            )

        publication = await self._succeed_validation(claim, publication)
        write_state = publication.configuration_write.state
        if write_state in (PublicationStage.RUNNING, PublicationStage.UNKNOWN):
            # A previous worker may have dispatched the CAS before losing its
            # lease. Reconcile exact provider state; never blindly resend it.
            if current.value == candidate:
                publication = await self._resolve_unknown_or_running(
                    claim,
                    publication,
                    PublicationPhaseName.CONFIGURATION_WRITE,
                    PublicationStage.SUCCEEDED,
                )
            else:
                if write_state is PublicationStage.RUNNING:
                    await self._advance(
                        claim,
                        publication,
                        PublicationPhaseName.CONFIGURATION_WRITE,
                        PublicationStage.RUNNING,
                        PublicationStage.UNKNOWN,
                        PublicationReason.UNKNOWN,
                    )
                return RulePublicationWorkerOutcome.UNKNOWN
        elif write_state is PublicationStage.AWAITING:
            publication = await self._advance(
                claim,
                publication,
                PublicationPhaseName.CONFIGURATION_WRITE,
                PublicationStage.AWAITING,
                PublicationStage.RUNNING,
            )
            try:
                await self._provider.write_configuration_if_revision(
                    connection,
                    claim.target,
                    expected_revision=current.revision,
                    value=candidate,
                )
            except RulePublicationProviderConflict:
                return await self._fail(
                    claim,
                    publication,
                    PublicationPhaseName.CONFIGURATION_WRITE,
                    PublicationReason.CONFLICT,
                    RuleOperationRejection.CONFLICT,
                )
            except RulePublicationProviderRejected:
                return await self._fail(
                    claim,
                    publication,
                    PublicationPhaseName.CONFIGURATION_WRITE,
                    PublicationReason.REJECTED,
                    RuleOperationRejection.UNSUPPORTED,
                )
            except RulePublicationProviderUnavailable:
                return await self._fail(
                    claim,
                    publication,
                    PublicationPhaseName.CONFIGURATION_WRITE,
                    PublicationReason.UNAVAILABLE,
                    RuleOperationRejection.UNAVAILABLE,
                )
            except RulePublicationProviderOutcomeUnknown:
                await self._advance(
                    claim,
                    publication,
                    PublicationPhaseName.CONFIGURATION_WRITE,
                    PublicationStage.RUNNING,
                    PublicationStage.UNKNOWN,
                    PublicationReason.UNKNOWN,
                )
                return RulePublicationWorkerOutcome.UNKNOWN
            publication = await self._advance(
                claim,
                publication,
                PublicationPhaseName.CONFIGURATION_WRITE,
                PublicationStage.RUNNING,
                PublicationStage.SUCCEEDED,
            )

        return await self._verify_read_back(claim, publication, connection, candidate)

    async def _read_baseline(self, claim: _RulePublishClaimView) -> bytes | None:
        if claim.expected_version_id is None:
            return None
        baseline = await self._version_reader.execute(
            claim.binding_id, claim.expected_version_id
        )
        if baseline.checksum != claim.expected_checksum:
            raise ValueError("publish baseline checksum changed")
        return self._payload_encoder.encode_rule_version(baseline)

    async def _succeed_validation(
        self, claim: _RulePublishClaimView, publication: RulePublication
    ) -> RulePublication:
        state = publication.validation.state
        if state is PublicationStage.SUCCEEDED:
            return publication
        if state is PublicationStage.UNKNOWN:
            return await self._advance(
                claim,
                publication,
                PublicationPhaseName.VALIDATION,
                PublicationStage.UNKNOWN,
                PublicationStage.SUCCEEDED,
            )
        if state is PublicationStage.AWAITING:
            publication = await self._advance(
                claim,
                publication,
                PublicationPhaseName.VALIDATION,
                PublicationStage.AWAITING,
                PublicationStage.RUNNING,
            )
        return await self._advance(
            claim,
            publication,
            PublicationPhaseName.VALIDATION,
            PublicationStage.RUNNING,
            PublicationStage.SUCCEEDED,
        )

    async def _verify_read_back(
        self,
        claim: _RulePublishClaimView,
        publication: RulePublication,
        connection: object,
        candidate: bytes,
    ) -> RulePublicationWorkerOutcome:
        state = publication.read_back.state
        if state is PublicationStage.SUCCEEDED:
            await self._outbox.complete_claimed_publication(
                _stored_claim(claim),
                completed_at=_millisecond_instant(self._clock()),
            )
            return RulePublicationWorkerOutcome.COMPLETED
        if state is PublicationStage.AWAITING:
            publication = await self._advance(
                claim,
                publication,
                PublicationPhaseName.READ_BACK,
                PublicationStage.AWAITING,
                PublicationStage.RUNNING,
            )
        try:
            observed = await self._provider.read_configuration(
                connection, claim.target
            )
        except (
            RulePublicationProviderUnavailable,
            RulePublicationProviderOutcomeUnknown,
            RulePublicationProviderRejected,
            OSError,
            TimeoutError,
        ):
            if publication.read_back.state is PublicationStage.RUNNING:
                await self._advance(
                    claim,
                    publication,
                    PublicationPhaseName.READ_BACK,
                    PublicationStage.RUNNING,
                    PublicationStage.UNKNOWN,
                    PublicationReason.UNKNOWN,
                )
            return RulePublicationWorkerOutcome.UNKNOWN
        if observed.value != candidate:
            return await self._fail(
                claim,
                publication,
                PublicationPhaseName.READ_BACK,
                PublicationReason.READBACK_MISMATCH,
                RuleOperationRejection.CONFLICT,
            )
        state = publication.read_back.state
        if state is PublicationStage.UNKNOWN:
            publication = await self._advance(
                claim,
                publication,
                PublicationPhaseName.READ_BACK,
                PublicationStage.UNKNOWN,
                PublicationStage.SUCCEEDED,
            )
        elif state is PublicationStage.RUNNING:
            publication = await self._advance(
                claim,
                publication,
                PublicationPhaseName.READ_BACK,
                PublicationStage.RUNNING,
                PublicationStage.SUCCEEDED,
            )
        await self._outbox.complete_claimed_publication(
            _stored_claim(claim),
            completed_at=_millisecond_instant(self._clock()),
        )
        return RulePublicationWorkerOutcome.COMPLETED

    async def _fail(
        self,
        claim: _RulePublishClaimView,
        publication: RulePublication,
        phase_name: PublicationPhaseName,
        reason: PublicationReason,
        rejection: RuleOperationRejection,
    ) -> RulePublicationWorkerOutcome:
        phase = getattr(publication, phase_name.value)
        if phase.state is PublicationStage.AWAITING:
            publication = await self._advance(
                claim,
                publication,
                phase_name,
                PublicationStage.AWAITING,
                PublicationStage.RUNNING,
            )
            phase = getattr(publication, phase_name.value)
        if phase.state in (PublicationStage.RUNNING, PublicationStage.UNKNOWN):
            await self._advance(
                claim,
                publication,
                phase_name,
                phase.state,
                PublicationStage.FAILED,
                reason,
            )
        await self._outbox.reject_claimed_publication(
            _stored_claim(claim),
            rejected_at=_millisecond_instant(self._clock()),
            reason=rejection,
        )
        return RulePublicationWorkerOutcome.REJECTED

    async def _finalize_known_failure(
        self, claim: _RulePublishClaimView, publication: RulePublication
    ) -> RulePublicationWorkerOutcome | None:
        phases = (
            publication.validation,
            publication.configuration_write,
            publication.read_back,
        )
        if not any(phase.state is PublicationStage.FAILED for phase in phases):
            return None
        if any(phase.state is PublicationStage.UNKNOWN for phase in phases):
            return RulePublicationWorkerOutcome.UNKNOWN
        reason = next(
            phase.reason
            for phase in phases
            if phase.state is PublicationStage.FAILED
        )
        rejection = {
            PublicationReason.CONFLICT: RuleOperationRejection.CONFLICT,
            PublicationReason.UNAVAILABLE: RuleOperationRejection.UNAVAILABLE,
            PublicationReason.REJECTED: RuleOperationRejection.UNSUPPORTED,
            PublicationReason.READBACK_MISMATCH: RuleOperationRejection.CONFLICT,
            PublicationReason.UNSUPPORTED: RuleOperationRejection.VALIDATION,
            PublicationReason.UNKNOWN: RuleOperationRejection.UNAVAILABLE,
        }[reason]
        await self._outbox.reject_claimed_publication(
            _stored_claim(claim),
            rejected_at=_millisecond_instant(self._clock()),
            reason=rejection,
        )
        return RulePublicationWorkerOutcome.REJECTED

    async def _preflight_failure(
        self,
        claim: _RulePublishClaimView,
        publication: RulePublication,
        reason: PublicationReason,
        rejection: RuleOperationRejection,
    ) -> RulePublicationWorkerOutcome:
        write_state = publication.configuration_write.state
        if write_state in (PublicationStage.RUNNING, PublicationStage.UNKNOWN):
            if write_state is PublicationStage.RUNNING:
                await self._advance(
                    claim,
                    publication,
                    PublicationPhaseName.CONFIGURATION_WRITE,
                    PublicationStage.RUNNING,
                    PublicationStage.UNKNOWN,
                    PublicationReason.UNKNOWN,
                )
            return RulePublicationWorkerOutcome.UNKNOWN
        if write_state is PublicationStage.SUCCEEDED:
            read_back_state = publication.read_back.state
            if read_back_state is PublicationStage.AWAITING:
                publication = await self._advance(
                    claim,
                    publication,
                    PublicationPhaseName.READ_BACK,
                    PublicationStage.AWAITING,
                    PublicationStage.RUNNING,
                )
                read_back_state = PublicationStage.RUNNING
            if read_back_state is PublicationStage.RUNNING:
                await self._advance(
                    claim,
                    publication,
                    PublicationPhaseName.READ_BACK,
                    PublicationStage.RUNNING,
                    PublicationStage.UNKNOWN,
                    PublicationReason.UNKNOWN,
                )
            return RulePublicationWorkerOutcome.UNKNOWN
        return await self._fail(
            claim,
            publication,
            _preflight_failure_phase(publication),
            reason,
            rejection,
        )

    async def _resolve_unknown_or_running(
        self,
        claim: _RulePublishClaimView,
        publication: RulePublication,
        phase_name: PublicationPhaseName,
        next_state: PublicationStage,
    ) -> RulePublication:
        phase = getattr(publication, phase_name.value)
        return await self._advance(
            claim, publication, phase_name, phase.state, next_state
        )

    async def _advance(
        self,
        claim: _RulePublishClaimView,
        publication: RulePublication,
        phase_name: PublicationPhaseName,
        expected: PublicationStage,
        next_state: PublicationStage,
        reason: PublicationReason | None = None,
    ) -> RulePublication:
        return await self._outbox.advance_claimed_phase(
            _stored_claim(claim),
            phase_name,
            expected_state=expected,
            next_phase=PublicationPhase(
                next_state,
                _millisecond_instant(self._clock()),
                reason,
            ),
        )


def _claim_matches_version(
    claim: _RulePublishClaimView,
    version: RuleSetVersion,
    publication: RulePublication,
) -> bool:
    return (
        version.id == claim.version_id
        and version.binding_id == claim.binding_id
        and version.checksum == claim.version_checksum
        and version.id == publication.target_version_id
        and version.checksum == publication.target_checksum
        and publication.base_version_id == claim.expected_version_id
    )


def _stored_claim(
    claim: _RulePublishClaimView,
) -> RulePublishWorkClaim:
    """Pass the latest immutable lease snapshot to the outbox Port."""
    if isinstance(claim, _ActiveRulePublishClaim):
        return claim.current_claim
    return claim


def _preflight_failure_phase(publication: RulePublication) -> PublicationPhaseName:
    if publication.configuration_write.state is PublicationStage.SUCCEEDED:
        return PublicationPhaseName.READ_BACK
    if publication.validation.state is PublicationStage.SUCCEEDED:
        return PublicationPhaseName.CONFIGURATION_WRITE
    return PublicationPhaseName.VALIDATION


def _millisecond_instant(value: datetime) -> datetime:
    if not is_wire_utc_millisecond_instant(value):
        raise ValueError("worker clock must return a UTC millisecond instant")
    return value


__all__ = ["RulePublicationWorkerOutcome", "RunRulePublicationWorker"]
