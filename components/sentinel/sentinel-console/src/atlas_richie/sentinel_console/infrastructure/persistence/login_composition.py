"""Explicit SQL-backed composition for the Console login use case."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.login import Login
from .login_attempt_configuration import LoginAttemptLimitConfiguration
from .login_attempt_dialect_adapters import LoginAttemptDialectAdapter
from .login_attempt_limiter import SqlAlchemyLoginAttemptLimiter
from .login_credential_reader import SqlAlchemyLoginCredentialReader
from .login_session_writer import SqlAlchemyLoginSessionWriter
from ..security.password_hash import PasswordHashService


def compose_sql_login(
    engine: AsyncEngine,
    *,
    attempt_limit: LoginAttemptLimitConfiguration,
    session_ttl: timedelta,
    password_hasher: PasswordHashService | None = None,
    additional_login_attempt_dialect_adapters: tuple[
        LoginAttemptDialectAdapter, ...
    ] = (),
) -> Login:
    """Wire existing SQL adapters and password verification into ``Login``.

    Caller owns the engine lifecycle and supplies explicit rate-limit and
    session policies. This function does not connect, migrate, or start the
    Console application.
    """
    return Login(
        credential_reader=SqlAlchemyLoginCredentialReader(engine),
        session_writer=SqlAlchemyLoginSessionWriter(engine),
        attempt_limiter=SqlAlchemyLoginAttemptLimiter(
            engine,
            policy=attempt_limit.to_policy(),
            additional_dialect_adapters=additional_login_attempt_dialect_adapters,
        ),
        password_hasher=(
            password_hasher
            if password_hasher is not None
            else PasswordHashService()
        ),
        session_ttl=session_ttl,
    )
