"""Explicit composition for the registered-source SQL adapter."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from ..security.registered_source_keys import RegisteredSourceKeyConfiguration
from .registered_source_store import SqlAlchemyRegisteredSourceStore


def compose_registered_source_store(
    engine: AsyncEngine,
    key_configuration: RegisteredSourceKeyConfiguration,
) -> SqlAlchemyRegisteredSourceStore:
    """Build one source store using deployment-owned key rings and engine."""
    return SqlAlchemyRegisteredSourceStore(
        engine,
        secret_cipher=key_configuration.create_secret_cipher(),
        fingerprint_keys=key_configuration.fingerprint_keys,
        active_fingerprint_key_id=key_configuration.active_fingerprint_key_id,
    )
