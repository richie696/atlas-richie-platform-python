"""Ports for explicit host-to-runtime association management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..domain.host_associations import HostAssociationPage


class HostAssociationStore(Protocol):
    """Durable authority for operator-managed associations."""

    async def list_host_associations(
        self,
        environment_id: str,
        *,
        source_id: str | None = None,
        app_id: str | None = None,
        instance_id: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> HostAssociationPage: ...

    async def put_host_association(
        self,
        *,
        source_id: str,
        environment_id: str,
        host_id: str,
        app_id: str,
        instance_id: str,
        expected_revision: str | None,
        request_key: str,
        actor_id: str,
        session_digest: str,
        request_id: str,
        now: datetime,
    ) -> dict[str, object]: ...

    async def delete_host_association(
        self,
        *,
        environment_id: str,
        app_id: str,
        instance_id: str,
        expected_revision: str,
        request_key: str,
        actor_id: str,
        session_digest: str,
        request_id: str,
        now: datetime,
    ) -> dict[str, object] | None: ...

    async def read_host_association_operation(
        self, request_key: str, *, actor_id: str, session_digest: str
    ) -> dict[str, object] | None: ...

    async def resolve_host_association_replay(
        self,
        request_key: str,
        *,
        actor_id: str,
        session_digest: str,
        kind: str,
        command: dict[str, object],
    ) -> dict[str, object] | None: ...


@dataclass(frozen=True, slots=True)
class ReadHostAssociations:
    """Read explicit mappings without attempting label-based discovery."""

    store: HostAssociationStore

    async def execute(
        self,
        environment_id: str,
        *,
        source_id: str | None = None,
        app_id: str | None = None,
        instance_id: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> HostAssociationPage:
        return await self.store.list_host_associations(
            environment_id,
            source_id=source_id,
            app_id=app_id,
            instance_id=instance_id,
            page=page,
            page_size=page_size,
        )


__all__ = ["HostAssociationStore", "ReadHostAssociations"]
