"""Application contracts for the one-time Console initialization workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Protocol

from ..domain.account_password import AccountPassword
from ..domain.account_username import AccountUsername
from ..domain.bootstrap import OpenSetupBootstrap
from .bootstrap_ports import BootstrapOperatorSessionVerifier
from .bootstrap_database_check import BootstrapDatabaseCandidate
from .bootstrap_source_check import BootstrapSourceCandidate
from .errors import BootstrapAuthorityUnavailable
from .read_bootstrap import ReadBootstrap

_REQUEST_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")


class BootstrapInitializationReason(StrEnum):
    """Finite outcomes safe to return for a rejected initialization."""

    VALIDATION = "validation"
    SETUP_CLOSED = "setup-closed"
    DEPENDENCY = "dependency"


class BootstrapInitializationStatus(StrEnum):
    """Durable operation states exposed by the setup workflow."""

    NOT_FOUND = "not-found"
    PENDING = "pending"
    COMPLETED = "completed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class BootstrapInitializationInput:
    """Validated first-run values; credentials stay out of repr and receipts."""

    database: BootstrapDatabaseCandidate
    admin_username: AccountUsername
    admin_password: AccountPassword = field(repr=False, compare=False)
    source: BootstrapSourceCandidate

    def __post_init__(self) -> None:
        if not isinstance(self.database, BootstrapDatabaseCandidate):
            raise TypeError("bootstrap database candidate is required")
        if not isinstance(self.admin_username, AccountUsername):
            raise TypeError("bootstrap admin username is required")
        if not isinstance(self.admin_password, AccountPassword):
            raise TypeError("bootstrap admin password is required")
        if not isinstance(self.source, BootstrapSourceCandidate):
            raise TypeError("bootstrap source candidate is required")


@dataclass(frozen=True, slots=True)
class BootstrapInitializationReceipt:
    """Safe durable status correlated to the original idempotency key."""

    request_key: str
    status: BootstrapInitializationStatus
    operation_id: str | None = None
    reason: BootstrapInitializationReason | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_key, str)
            or _REQUEST_KEY_PATTERN.fullmatch(self.request_key) is None
        ):
            raise ValueError("bootstrap request key is invalid")
        if not isinstance(self.status, BootstrapInitializationStatus):
            raise ValueError("bootstrap operation status is invalid")
        has_operation = self.status is not BootstrapInitializationStatus.NOT_FOUND
        if has_operation != (self.operation_id is not None):
            raise ValueError("bootstrap operation identity does not match status")
        if self.operation_id is not None:
            if (
                not isinstance(self.operation_id, str)
                or _OPERATION_ID_PATTERN.fullmatch(self.operation_id) is None
            ):
                raise ValueError("bootstrap operation identity is invalid")
        if self.reason is not None and not isinstance(
            self.reason, BootstrapInitializationReason
        ):
            raise ValueError("bootstrap rejection reason is invalid")
        if (self.status is BootstrapInitializationStatus.REJECTED) != (
            self.reason is not None
        ):
            raise ValueError("bootstrap rejection reason does not match status")


class BootstrapInitializer(Protocol):
    """Coordinate one idempotent initialization under the current grant."""

    async def initialize(
        self,
        *,
        operator_session: str,
        request_key: str,
        input: BootstrapInitializationInput,
    ) -> BootstrapInitializationReceipt:
        """Recheck setup closure and persist only a secret-free receipt.

        The implementation must bind the operation to a one-way identity of the
        opaque grant; it must never persist the raw cookie, submitted credentials,
        or credential-bearing input object. The runtime-configuration authority
        and target database are separate stores, so the implementation must define
        restart-safe recovery across them rather than claim a distributed atomic
        transaction.
        """


class BootstrapInitializationOperationReader(Protocol):
    """Read only the original operator's bounded initialization receipt."""

    async def read(
        self, operator_session: str, request_key: str
    ) -> BootstrapInitializationReceipt | None:
        """Return an operation visible to this grant, if any."""


class InitializeConsole:
    """Authorize and delegate the one-time setup command."""

    def __init__(
        self,
        bootstrap_reader: ReadBootstrap,
        initializer: BootstrapInitializer | None,
    ) -> None:
        self._bootstrap_reader = bootstrap_reader
        self._initializer = initializer

    async def execute(
        self,
        *,
        operator_session: str | None,
        request_key: str,
        input: BootstrapInitializationInput,
    ) -> BootstrapInitializationReceipt:
        if self._initializer is None:
            raise BootstrapAuthorityUnavailable("initializer is unavailable")
        snapshot = await self._bootstrap_reader.execute(operator_session)
        if not isinstance(snapshot, OpenSetupBootstrap) or not (
            snapshot.setup_available and snapshot.operator_authorized
        ):
            raise BootstrapInitializationForbidden
        if operator_session is None:
            raise BootstrapInitializationForbidden
        return await self._initializer.initialize(
            operator_session=operator_session,
            request_key=request_key,
            input=input,
        )


class ReadBootstrapInitialization:
    """Authorize receipt recovery independently of the now-closed setup window."""

    def __init__(
        self,
        operator_verifier: BootstrapOperatorSessionVerifier,
        operation_reader: BootstrapInitializationOperationReader | None,
    ) -> None:
        self._operator_verifier = operator_verifier
        self._operation_reader = operation_reader

    async def execute(
        self, operator_session: str | None, request_key: str
    ) -> BootstrapInitializationReceipt | None:
        if operator_session is None:
            raise BootstrapInitializationForbidden
        if not await self._operator_verifier.is_current_operator(operator_session):
            raise BootstrapInitializationForbidden
        if self._operation_reader is None:
            raise BootstrapAuthorityUnavailable("operation reader is unavailable")
        return await self._operation_reader.read(operator_session, request_key)


class BootstrapInitializationForbidden(RuntimeError):
    """The current browser grant cannot initialize or inspect setup operations."""


class BootstrapInitializationIdempotencyConflict(RuntimeError):
    """An initialization request key was reused with different input."""


__all__ = [
    "BootstrapInitializationForbidden",
    "BootstrapInitializationIdempotencyConflict",
    "BootstrapInitializationInput",
    "BootstrapInitializationOperationReader",
    "BootstrapInitializationReason",
    "BootstrapInitializationReceipt",
    "BootstrapInitializationStatus",
    "BootstrapInitializer",
    "InitializeConsole",
    "ReadBootstrapInitialization",
]
