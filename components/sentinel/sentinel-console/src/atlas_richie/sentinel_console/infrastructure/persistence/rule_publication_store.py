"""Transactional persistence for monotonic publication-phase observations."""

from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_publication_ports import (
    RulePublicationAuthorityUnavailable,
    RulePublicationConflict,
    RulePublicationNotFound,
    RulePublicationRecorder,
)
from ...domain.rule_publications import (
    PublicationPhase,
    PublicationPhaseName,
    PublicationStage,
    RulePublication,
    advance_publication_phase,
)
from .models import RulePublicationRecord, RuleSetVersionRecord
from .rule_publication_mapping import publication_from_row


class SqlAlchemyRulePublicationStore(RulePublicationRecorder):
    """Persist publication attempts and CAS each independent phase transition."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create_rule_publication(self, publication: RulePublication) -> None:
        """Create a clean awaiting attempt tied to versions in the same binding."""
        if not isinstance(publication, RulePublication):
            raise ValueError("publication is invalid")
        if any(
            phase.state is not PublicationStage.AWAITING
            or phase.observed_at is not None
            or phase.reason is not None
            for phase in (
                publication.validation,
                publication.configuration_write,
                publication.read_back,
            )
        ):
            raise ValueError("new publication phases must all be awaiting")
        try:
            async with self._engine.begin() as connection:
                target = await connection.execute(
                    select(RuleSetVersionRecord.binding_id, RuleSetVersionRecord.checksum)
                    .where(RuleSetVersionRecord.version_id == publication.target_version_id)
                    .with_for_update()
                )
                target_row = target.one_or_none()
                if (
                    target_row is None
                    or target_row.binding_id != publication.binding_id
                    or target_row.checksum != publication.target_checksum
                ):
                    raise RulePublicationConflict(
                        "publication target version no longer matches"
                    )
                if publication.base_version_id is not None:
                    base = await connection.execute(
                        select(RuleSetVersionRecord.binding_id)
                        .where(
                            RuleSetVersionRecord.version_id == publication.base_version_id
                        )
                        .with_for_update()
                    )
                    base_row = base.one_or_none()
                    if base_row is None or base_row.binding_id != publication.binding_id:
                        raise RulePublicationConflict(
                            "publication baseline version no longer matches"
                        )
                await connection.execute(
                    insert(RulePublicationRecord).values(
                        **_publication_values(publication)
                    )
                )
        except (RulePublicationConflict, RulePublicationAuthorityUnavailable):
            raise
        except IntegrityError:
            raise RulePublicationConflict(
                "publication identity already exists or references are invalid"
            ) from None
        except SQLAlchemyError:
            raise RulePublicationAuthorityUnavailable(
                "publication could not be persisted"
            ) from None

    async def advance_rule_publication_phase(
        self,
        binding_id: str,
        publication_id: str,
        phase_name: PublicationPhaseName,
        *,
        expected_state: PublicationStage,
        next_phase: PublicationPhase,
    ) -> RulePublication:
        """Advance one phase once, requiring both a locked read and CAS update."""
        try:
            async with self._engine.begin() as connection:
                result = await connection.execute(
                    select(RulePublicationRecord.__table__)
                    .where(
                        RulePublicationRecord.binding_id == binding_id,
                        RulePublicationRecord.publication_id == publication_id,
                    )
                    .with_for_update()
                )
                row = result.mappings().one_or_none()
                if row is None:
                    raise RulePublicationNotFound(
                        "rule publication does not exist"
                    )
                current = publication_from_row(row)
                updated = advance_publication_phase(
                    current,
                    phase_name,
                    expected_state=expected_state,
                    next_phase=next_phase,
                )
                values = _phase_values(phase_name, next_phase)
                changed = await connection.execute(
                    update(RulePublicationRecord)
                    .where(
                        RulePublicationRecord.binding_id == binding_id,
                        RulePublicationRecord.publication_id == publication_id,
                        _phase_state_column(phase_name) == expected_state.value,
                    )
                    .values(**values)
                )
                if changed.rowcount != 1:
                    raise RulePublicationConflict(
                        "publication phase changed since it was read"
                    )
                return updated
        except (RulePublicationConflict, RulePublicationNotFound):
            raise
        except ValueError:
            raise RulePublicationConflict(
                "publication phase transition is invalid"
            ) from None
        except SQLAlchemyError:
            raise RulePublicationAuthorityUnavailable(
                "publication phase could not be persisted"
            ) from None


def _publication_values(publication: RulePublication) -> dict[str, object]:
    return {
        "publication_id": publication.id,
        "binding_id": publication.binding_id,
        "target_version_id": publication.target_version_id,
        "target_checksum": publication.target_checksum,
        "base_version_id": publication.base_version_id,
        "created_at": publication.created_at,
        **_phase_values(PublicationPhaseName.VALIDATION, publication.validation),
        **_phase_values(
            PublicationPhaseName.CONFIGURATION_WRITE,
            publication.configuration_write,
        ),
        **_phase_values(PublicationPhaseName.READ_BACK, publication.read_back),
    }


def _phase_values(
    phase_name: PublicationPhaseName, phase: PublicationPhase
) -> dict[str, object]:
    prefix = {
        PublicationPhaseName.VALIDATION: "validation",
        PublicationPhaseName.CONFIGURATION_WRITE: "write",
        PublicationPhaseName.READ_BACK: "read_back",
    }[phase_name]
    return {
        f"{prefix}_state": phase.state.value,
        f"{prefix}_observed_at": phase.observed_at,
        f"{prefix}_reason": phase.reason.value if phase.reason is not None else None,
    }


def _phase_state_column(phase_name: PublicationPhaseName):
    return {
        PublicationPhaseName.VALIDATION: RulePublicationRecord.validation_state,
        PublicationPhaseName.CONFIGURATION_WRITE: RulePublicationRecord.write_state,
        PublicationPhaseName.READ_BACK: RulePublicationRecord.read_back_state,
    }[phase_name]


__all__ = ["SqlAlchemyRulePublicationStore"]
