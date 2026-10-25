"""Explicit operator-managed links between observed hosts and runtime workers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class HostInstanceAssociation:
    """A persisted association; never inferred from scrape labels."""

    source_id: str
    environment_id: str
    host_id: str
    app_id: str
    instance_id: str
    process_id: str
    revision: str
    current_epoch: str | None
    last_received_at: datetime | None
    created_at: datetime
    reporter_active: bool


@dataclass(frozen=True, slots=True)
class HostAssociationPage:
    """Bounded association page plus bounded source-scoped host membership."""

    items: tuple[HostInstanceAssociation, ...]
    page: int
    page_size: int
    total: int
    associated_host_ids: tuple[str, ...]
    host_ids_complete: bool


class HostAssociationError(RuntimeError):
    """Safe finite failures for host association commands."""


class HostAssociationConflict(HostAssociationError):
    """The worker is already associated with a different host."""


class HostAssociationIdempotencyConflict(HostAssociationError):
    """The request key was already consumed by another command or session."""


class HostAssociationNotFound(HostAssociationError):
    """The configured monitoring source or enrolled worker is absent."""


class HostAssociationUnavailable(HostAssociationError):
    """The authoritative host-association SQL store is unavailable."""


__all__ = [
    "HostAssociationConflict",
    "HostAssociationError",
    "HostAssociationIdempotencyConflict",
    "HostAssociationNotFound",
    "HostAssociationPage",
    "HostAssociationUnavailable",
    "HostInstanceAssociation",
]
