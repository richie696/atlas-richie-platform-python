"""Explicit SQL-backed composition for account mutation use cases."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.account_commands import MutateAccount
from ..security.account_command_keys import AccountCommandKeyConfiguration
from ..security.password_hash import PasswordHashService
from .account_command_store import SqlAlchemyAccountCommandStore


def compose_sql_account_commands(
    engine: AsyncEngine,
    key_configuration: AccountCommandKeyConfiguration,
    *,
    password_hasher: PasswordHashService | None = None,
) -> MutateAccount:
    """Wire the SQL transaction store and Argon2 hasher to the account use case."""
    return MutateAccount(
        store=SqlAlchemyAccountCommandStore(engine),
        password_hasher=(
            password_hasher
            if password_hasher is not None
            else PasswordHashService()
        ),
        fingerprint_keys=key_configuration.fingerprint_keys,
        active_fingerprint_key_id=key_configuration.active_fingerprint_key_id,
    )
