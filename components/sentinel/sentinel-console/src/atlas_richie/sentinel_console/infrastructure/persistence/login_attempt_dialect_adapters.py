"""Narrow SQL dialect adapters for login-attempt first-row insertion."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.sql import Executable

from .models import LoginAttemptRecord


class LoginAttemptDialectAdapter(Protocol):
    """Build one provider's insert-if-absent statement for a digest row."""

    dialect: str

    def insert_if_absent(
        self, values: Mapping[str, int | str | None]
    ) -> Executable:
        """Return an idempotent unique-key insert without executing it."""


class PostgreSQLLoginAttemptDialectAdapter:
    """Use PostgreSQL ON CONFLICT DO NOTHING for concurrent first failures."""

    dialect = "postgresql"

    def insert_if_absent(
        self, values: Mapping[str, int | str | None]
    ) -> Executable:
        statement = postgresql_insert(LoginAttemptRecord).values(**values)
        return statement.on_conflict_do_nothing(
            index_elements=[LoginAttemptRecord.client_identity_digest]
        )


class SQLiteLoginAttemptDialectAdapter:
    """Use SQLite ON CONFLICT DO NOTHING for local persistence contracts."""

    dialect = "sqlite"

    def insert_if_absent(
        self, values: Mapping[str, int | str | None]
    ) -> Executable:
        statement = sqlite_insert(LoginAttemptRecord).values(**values)
        return statement.on_conflict_do_nothing(
            index_elements=[LoginAttemptRecord.client_identity_digest]
        )


class MySQLLoginAttemptDialectAdapter:
    """Use MySQL's key-preserving duplicate update for concurrent first failures."""

    dialect = "mysql"

    def insert_if_absent(
        self, values: Mapping[str, int | str | None]
    ) -> Executable:
        statement = mysql_insert(LoginAttemptRecord).values(**values)
        return statement.on_duplicate_key_update(
            client_identity_digest=statement.inserted.client_identity_digest
        )


class LoginAttemptDialectAdapterRegistry:
    """Resolve the required row-initialization primitive by active SQL dialect."""

    def __init__(self, adapters: tuple[LoginAttemptDialectAdapter, ...]) -> None:
        by_dialect = {adapter.dialect: adapter for adapter in adapters}
        if (
            not adapters
            or len(by_dialect) != len(adapters)
            or any(
                not isinstance(dialect, str) or not dialect for dialect in by_dialect
            )
        ):
            raise ValueError(
                "login-attempt dialect adapters must be unique and non-empty"
            )
        self._adapters = by_dialect

    def resolve(self, dialect: str) -> LoginAttemptDialectAdapter:
        """Return the explicit adapter or fail closed for an unsupported dialect."""
        try:
            return self._adapters[dialect]
        except KeyError:
            raise ValueError("login-attempt SQL dialect is unsupported") from None

    @property
    def supported_dialects(self) -> frozenset[str]:
        """Return the immutable dialect capability set for composition checks."""
        return frozenset(self._adapters)


def default_login_attempt_dialect_adapters(
    *, additional_adapters: tuple[LoginAttemptDialectAdapter, ...] = ()
) -> LoginAttemptDialectAdapterRegistry:
    """Compose built-in dialect primitives with explicit host-owned additions."""
    return LoginAttemptDialectAdapterRegistry(
        (
            PostgreSQLLoginAttemptDialectAdapter(),
            SQLiteLoginAttemptDialectAdapter(),
            MySQLLoginAttemptDialectAdapter(),
            *additional_adapters,
        )
    )


__all__ = [
    "LoginAttemptDialectAdapter",
    "LoginAttemptDialectAdapterRegistry",
    "MySQLLoginAttemptDialectAdapter",
    "PostgreSQLLoginAttemptDialectAdapter",
    "SQLiteLoginAttemptDialectAdapter",
    "default_login_attempt_dialect_adapters",
]
