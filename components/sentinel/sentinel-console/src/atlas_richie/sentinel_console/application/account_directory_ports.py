"""Consumer-owned account-directory persistence boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from ..domain.session import AccountRole
from ..domain.wire_strings import (
    has_non_blank_wire_content,
    is_bounded_wire_identifier,
    is_bounded_wire_text,
)

MAX_ACCOUNT_DIRECTORY_PAGE = 1_000_000
MAX_ACCOUNT_DIRECTORY_PAGE_SIZE = 100
MAX_ACCOUNT_DIRECTORY_TOTAL = 2**53 - 1
MAX_ACCOUNT_DIRECTORY_IDENTIFIER_UNITS = 200
MAX_ACCOUNT_DIRECTORY_USERNAME_UNITS = 200
MAX_ACCOUNT_DIRECTORY_REVISION = 2**63 - 1


class AccountDirectoryStatus(StrEnum):
    """Finite account states exposed by the Console directory protocol."""

    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class AccountDirectoryQuery:
    """Validated directory filters; HTTP parsing stays outside the use case."""

    page: int
    page_size: int
    search: str
    status: str | None


@dataclass(frozen=True, slots=True)
class AccountDirectoryItem:
    """Credential-free account facts required by the administrative UI."""

    account_id: str
    username: str
    role_id: str
    status: str
    built_in: bool
    last_login_at: datetime | None
    revision: int
    last_active_admin: bool

    def __post_init__(self) -> None:
        """Reject authority facts that the browser's account wire schema cannot accept."""
        if not is_bounded_wire_identifier(
            self.account_id, MAX_ACCOUNT_DIRECTORY_IDENTIFIER_UNITS
        ):
            raise ValueError("account directory identifier is invalid")
        if (
            not is_bounded_wire_text(
                self.username, MAX_ACCOUNT_DIRECTORY_USERNAME_UNITS
            )
            or not has_non_blank_wire_content(self.username)
        ):
            raise ValueError("account directory username is invalid")
        if not isinstance(self.role_id, str) or not isinstance(self.status, str):
            raise ValueError("account directory role or status is invalid")
        try:
            role = AccountRole(self.role_id)
            status = AccountDirectoryStatus(self.status)
        except ValueError as error:
            raise ValueError("account directory role or status is invalid") from error
        if type(self.built_in) is not bool or type(self.last_active_admin) is not bool:
            raise ValueError("account directory flags are invalid")
        if (
            type(self.revision) is not int
            or not 1 <= self.revision <= MAX_ACCOUNT_DIRECTORY_REVISION
        ):
            raise ValueError("account directory revision is invalid")
        active_admin = (
            role is AccountRole.ADMIN and status is AccountDirectoryStatus.ACTIVE
        )
        if (self.built_in or self.last_active_admin) and not active_admin:
            raise ValueError("account directory administrator fact is inconsistent")
        if self.last_login_at is not None and not isinstance(
            self.last_login_at, datetime
        ):
            raise ValueError("account directory timestamp is invalid")


@dataclass(frozen=True, slots=True)
class AccountDirectoryPage:
    """One bounded slice and its total directory count."""

    items: tuple[AccountDirectoryItem, ...]
    page: int
    page_size: int
    total: int

    def __post_init__(self) -> None:
        """Keep the authority projection within the exact browser paging contract."""
        if type(self.page) is not int or not 1 <= self.page <= MAX_ACCOUNT_DIRECTORY_PAGE:
            raise ValueError("account directory page is out of range")
        if (
            type(self.page_size) is not int
            or not 1 <= self.page_size <= MAX_ACCOUNT_DIRECTORY_PAGE_SIZE
        ):
            raise ValueError("account directory page size is out of range")
        if (
            type(self.total) is not int
            or not 0 <= self.total <= MAX_ACCOUNT_DIRECTORY_TOTAL
        ):
            raise ValueError("account directory total is out of range")
        if not isinstance(self.items, tuple) or any(
            not isinstance(item, AccountDirectoryItem) for item in self.items
        ):
            raise ValueError("account directory items are invalid")
        expected_count = min(
            self.page_size,
            max(0, self.total - (self.page - 1) * self.page_size),
        )
        identifiers = tuple(item.account_id for item in self.items)
        if len(self.items) != expected_count:
            raise ValueError("account directory page length is inconsistent")
        if any(
            not is_bounded_wire_identifier(
                value, MAX_ACCOUNT_DIRECTORY_IDENTIFIER_UNITS
            )
            for value in identifiers
        ):
            raise ValueError("account directory identifier is invalid")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("account directory page facts are inconsistent")


class AccountDirectoryReader(Protocol):
    """Read safe account facts from the configured identity authority."""

    async def list_accounts(self, query: AccountDirectoryQuery) -> AccountDirectoryPage:
        """Return a deterministic, bounded account directory page."""

    async def read_account(self, account_id: str) -> AccountDirectoryItem | None:
        """Return one account or ``None`` when the identifier is absent."""


class AccountDirectoryAuthorityUnavailable(RuntimeError):
    """The account directory cannot be read from its configured authority."""


class AccountDirectoryContractViolation(RuntimeError):
    """The account directory authority returned facts outside the Console contract."""
