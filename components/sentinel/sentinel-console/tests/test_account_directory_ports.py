"""Value-object invariants for account-directory queries."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel_console.application.account_directory_ports import (
    MAX_ACCOUNT_DIRECTORY_PAGE,
    MAX_ACCOUNT_DIRECTORY_PAGE_SIZE,
    MAX_ACCOUNT_DIRECTORY_SEARCH_UNITS,
    AccountDirectoryQuery,
    AccountDirectoryStatus,
)


class AccountDirectoryQueryTest(unittest.TestCase):
    def test_accepts_inclusive_integer_and_utf16_boundaries(self) -> None:
        accepted_queries = (
            AccountDirectoryQuery(1, 1, "", None),
            AccountDirectoryQuery(
                MAX_ACCOUNT_DIRECTORY_PAGE,
                MAX_ACCOUNT_DIRECTORY_PAGE_SIZE,
                "a" * MAX_ACCOUNT_DIRECTORY_SEARCH_UNITS,
                AccountDirectoryStatus.ACTIVE,
            ),
            AccountDirectoryQuery(
                1,
                20,
                "😀" * (MAX_ACCOUNT_DIRECTORY_SEARCH_UNITS // 2),
                AccountDirectoryStatus.DISABLED,
            ),
        )

        self.assertEqual(len(accepted_queries), 3)

    def test_rejects_out_of_range_and_boolean_pagination(self) -> None:
        invalid_queries = (
            (0, 20, "", None),
            (MAX_ACCOUNT_DIRECTORY_PAGE + 1, 20, "", None),
            (1, 0, "", None),
            (1, MAX_ACCOUNT_DIRECTORY_PAGE_SIZE + 1, "", None),
        )

        for args in invalid_queries:
            with self.subTest(args=args), self.assertRaises(ValueError):
                AccountDirectoryQuery(*args)

        for args in ((True, 20, "", None), (1, False, "", None)):
            with self.subTest(args=args), self.assertRaises(TypeError):
                AccountDirectoryQuery(*args)

    def test_rejects_search_outside_scalar_safe_utf16_bound(self) -> None:
        invalid_searches = (
            "a" * (MAX_ACCOUNT_DIRECTORY_SEARCH_UNITS + 1),
            ("😀" * (MAX_ACCOUNT_DIRECTORY_SEARCH_UNITS // 2)) + "a",
            "\ud800",
        )

        for search in invalid_searches:
            with self.subTest(search=repr(search)), self.assertRaises(ValueError):
                AccountDirectoryQuery(1, 20, search, None)

        with self.assertRaises(TypeError):
            AccountDirectoryQuery(1, 20, None, None)

    def test_rejects_unknown_or_non_string_status(self) -> None:
        for invalid_status in ("pending", "active", 1):
            with self.subTest(status=invalid_status), self.assertRaises(TypeError):
                AccountDirectoryQuery(1, 20, "", invalid_status)

    def test_accepts_enum_status(self) -> None:
        query = AccountDirectoryQuery(1, 20, "", AccountDirectoryStatus.ACTIVE)
        self.assertIs(query.status, AccountDirectoryStatus.ACTIVE)
