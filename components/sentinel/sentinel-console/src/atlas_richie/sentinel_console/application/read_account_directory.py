"""Read-only account directory use cases."""

from __future__ import annotations

from .account_directory_ports import (
    AccountDirectoryContractViolation,
    AccountDirectoryItem,
    AccountDirectoryPage,
    AccountDirectoryQuery,
    AccountDirectoryReader,
)


class ReadAccountDirectory:
    """Coordinate safe list and detail reads without owning HTTP or SQL policy."""

    def __init__(self, reader: AccountDirectoryReader) -> None:
        self._reader = reader

    async def list(self, query: AccountDirectoryQuery) -> AccountDirectoryPage:
        """Read one prevalidated page from the account authority."""
        try:
            page = await self._reader.list_accounts(query)
        except (TypeError, ValueError) as error:
            raise AccountDirectoryContractViolation(
                "account directory returned an invalid page"
            ) from error
        if not isinstance(page, AccountDirectoryPage):
            raise AccountDirectoryContractViolation(
                "account directory returned an invalid page"
            )
        if (
            page.page != query.page
            or page.page_size != query.page_size
            or (
                query.status is not None
                and any(item.status != query.status for item in page.items)
            )
        ):
            raise AccountDirectoryContractViolation(
                "account directory response does not match its query"
            )
        return page

    async def read(self, account_id: str) -> AccountDirectoryItem | None:
        """Read one account's safe projection."""
        try:
            item = await self._reader.read_account(account_id)
        except (TypeError, ValueError) as error:
            raise AccountDirectoryContractViolation(
                "account directory returned an invalid account"
            ) from error
        if item is not None and not isinstance(item, AccountDirectoryItem):
            raise AccountDirectoryContractViolation(
                "account directory returned an invalid account"
            )
        if item is not None and item.account_id != account_id:
            raise AccountDirectoryContractViolation(
                "account directory detail does not match its identifier"
            )
        return item
