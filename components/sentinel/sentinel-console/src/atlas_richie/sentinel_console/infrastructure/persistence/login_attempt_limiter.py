"""SQL implementation of the shared authentication-attempt policy Port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
import re
from typing import Callable, Mapping

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.login_ports import LoginAuthorityUnavailable
from .login_attempt_dialect_adapters import (
    LoginAttemptDialectAdapter,
    default_login_attempt_dialect_adapters,
)
from .models import LoginAttemptRecord

_CLIENT_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
_PRUNE_EVERY_MUTATIONS = 128
_PRUNE_BATCH_SIZE = 100
_MAX_FAILURE_COUNT = 2_147_483_647


@dataclass(frozen=True, slots=True)
class LoginAttemptLimitPolicy:
    """Explicit failure threshold, observation window, and temporary block."""

    failure_threshold: int
    window: timedelta
    block_duration: timedelta

    def __post_init__(self) -> None:
        if (
            isinstance(self.failure_threshold, bool)
            or not isinstance(self.failure_threshold, int)
            or not 1 <= self.failure_threshold <= _MAX_FAILURE_COUNT
        ):
            raise ValueError("failure_threshold is outside the supported range")
        if self.window <= timedelta(0) or self.block_duration <= timedelta(0):
            raise ValueError("login limit durations must be positive")

    @property
    def window_ms(self) -> int:
        return _duration_ms(self.window)

    @property
    def block_duration_ms(self) -> int:
        return _duration_ms(self.block_duration)


class SqlAlchemyLoginAttemptLimiter:
    """Serialize opaque-subject failure transitions through the shared SQL DB.

    Existing digest rows are locked with ``SELECT FOR UPDATE`` on supported
    production databases. Concurrent first failures use each dialect's native
    insert-if-absent operation before taking that row lock. SQLite is useful
    for local persistence tests but does not prove PostgreSQL/MySQL lock
    semantics. Login uses an HMAC of the resolved client address; own-password
    changes use a purpose-separated HMAC of the authenticated account ID.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        policy: LoginAttemptLimitPolicy,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        additional_dialect_adapters: tuple[LoginAttemptDialectAdapter, ...] = (),
    ) -> None:
        self._dialect_adapters = default_login_attempt_dialect_adapters(
            additional_adapters=additional_dialect_adapters
        )
        engine_dialect = getattr(engine, "dialect", None)
        if engine_dialect is not None:
            configured_dialects = {engine_dialect.name}
        else:
            configured_dialects = set(getattr(engine, "supported_dialects", ()))
        if (
            not configured_dialects
            or not configured_dialects <= self._dialect_adapters.supported_dialects
        ):
            raise ValueError("login limiter has no adapter for a configured SQL dialect")
        self._engine = engine
        self._policy = policy
        self._clock = clock
        self._mutation_count = 0

    async def retry_after_ms(self, client_identity_digest: str) -> int | None:
        """Read the current block without disclosing any identity or row data."""
        digest = _validated_digest(client_identity_digest)
        now_ms = _now_ms(self._clock())
        try:
            async with self._engine.begin() as connection:
                row = await connection.execute(
                    select(LoginAttemptRecord.blocked_until_ms)
                    .where(LoginAttemptRecord.client_identity_digest == digest)
                    .with_for_update()
                )
                blocked_until_ms = row.scalar_one_or_none()
        except SQLAlchemyError:
            raise LoginAuthorityUnavailable(
                "login attempt authority is unavailable"
            ) from None

        if blocked_until_ms is None or blocked_until_ms <= now_ms:
            return None
        return blocked_until_ms - now_ms

    async def record_failure(self, client_identity_digest: str) -> None:
        """Atomically advance one digest's fixed-window failure state."""
        digest = _validated_digest(client_identity_digest)
        now_ms = _now_ms(self._clock())

        try:
            async with self._engine.begin() as connection:
                await self._insert_if_absent(connection, digest, now_ms)
                result = await connection.execute(
                    select(
                        LoginAttemptRecord.window_started_at_ms,
                        LoginAttemptRecord.failure_count,
                        LoginAttemptRecord.blocked_until_ms,
                        LoginAttemptRecord.expires_at_ms,
                    )
                    .where(LoginAttemptRecord.client_identity_digest == digest)
                    .with_for_update()
                )
                row = result.mappings().one()
                state = self._next_failure_state(row, now_ms)
                await connection.execute(
                    update(LoginAttemptRecord)
                    .where(LoginAttemptRecord.client_identity_digest == digest)
                    .values(**state)
                )
                await self._prune_expired(connection, now_ms)
        except SQLAlchemyError:
            raise LoginAuthorityUnavailable(
                "login attempt authority is unavailable"
            ) from None

    async def record_success(self, client_identity_digest: str) -> None:
        """Clear the digest's failure window after successful authentication."""
        digest = _validated_digest(client_identity_digest)
        now_ms = _now_ms(self._clock())
        try:
            async with self._engine.begin() as connection:
                await connection.execute(
                    delete(LoginAttemptRecord).where(
                        LoginAttemptRecord.client_identity_digest == digest
                    )
                )
                await self._prune_expired(connection, now_ms)
        except SQLAlchemyError:
            raise LoginAuthorityUnavailable(
                "login attempt authority is unavailable"
            ) from None

    def _next_failure_state(
        self, row: Mapping[str, int | None] | None, now_ms: int
    ) -> dict[str, int | None]:
        if (
            row is None
            or row["failure_count"] == 0
            or row["expires_at_ms"] <= now_ms
        ):
            window_started_at_ms = now_ms
            failure_count = 1
            blocked_until_ms = None
        elif (
            row["blocked_until_ms"] is not None
            and row["blocked_until_ms"] > now_ms
        ):
            window_started_at_ms = row["window_started_at_ms"]
            failure_count = min(
                row["failure_count"] + 1, self._policy.failure_threshold
            )
            blocked_until_ms = row["blocked_until_ms"]
        elif row["blocked_until_ms"] is not None:
            window_started_at_ms = now_ms
            failure_count = 1
            blocked_until_ms = None
        elif now_ms >= row["window_started_at_ms"] + self._policy.window_ms:
            window_started_at_ms = now_ms
            failure_count = 1
            blocked_until_ms = None
        else:
            window_started_at_ms = row["window_started_at_ms"]
            failure_count = min(
                row["failure_count"] + 1, self._policy.failure_threshold
            )
            blocked_until_ms = None

        if failure_count >= self._policy.failure_threshold and blocked_until_ms is None:
            blocked_until_ms = now_ms + self._policy.block_duration_ms

        expires_at_ms = max(
            window_started_at_ms + self._policy.window_ms,
            blocked_until_ms or 0,
        )
        return {
            "window_started_at_ms": window_started_at_ms,
            "failure_count": failure_count,
            "blocked_until_ms": blocked_until_ms,
            "expires_at_ms": expires_at_ms,
        }

    async def _insert_if_absent(self, connection, digest: str, now_ms: int) -> None:
        """Use a dialect adapter's unique-key no-op for concurrent first failures."""
        values = {
            "client_identity_digest": digest,
            "window_started_at_ms": now_ms,
            "failure_count": 0,
            "blocked_until_ms": None,
            "expires_at_ms": now_ms + self._policy.window_ms,
        }
        try:
            adapter = self._dialect_adapters.resolve(connection.dialect.name)
        except ValueError:
            raise SQLAlchemyError(
                "login attempt authority has no adapter for the active SQL dialect"
            ) from None
        statement = adapter.insert_if_absent(values)
        await connection.execute(statement)

    async def _prune_expired(self, connection, now_ms: int) -> None:
        self._mutation_count += 1
        if self._mutation_count % _PRUNE_EVERY_MUTATIONS:
            return
        expired_rows = await connection.execute(
            select(LoginAttemptRecord.client_identity_digest)
            .where(LoginAttemptRecord.expires_at_ms <= now_ms)
            .limit(_PRUNE_BATCH_SIZE)
        )
        expired_digests = expired_rows.scalars().all()
        if expired_digests:
            await connection.execute(
                delete(LoginAttemptRecord).where(
                    LoginAttemptRecord.client_identity_digest.in_(expired_digests),
                    LoginAttemptRecord.expires_at_ms <= now_ms,
                )
            )


def _duration_ms(duration: timedelta) -> int:
    milliseconds = ceil(duration.total_seconds() * 1000)
    if milliseconds <= 0:
        raise ValueError("login limit duration is below one millisecond")
    return milliseconds


def _now_ms(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return an aware datetime")
    return int(value.timestamp() * 1000)


def _validated_digest(value: str) -> str:
    if not isinstance(value, str) or _CLIENT_DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError("client identity must be a lowercase SHA-256 HMAC digest")
    return value
