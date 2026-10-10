"""Account-password domain validation matches the React wire contract."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel_console.domain.account_password import (
    AccountPassword,
    MAX_ACCOUNT_PASSWORD_UTF16_UNITS,
    MIN_ACCOUNT_PASSWORD_UTF16_UNITS,
)


class AccountPasswordTest(unittest.TestCase):
    def test_accepts_boundary_lengths_without_normalizing(self) -> None:
        minimum = " " + "a" * (MIN_ACCOUNT_PASSWORD_UTF16_UNITS - 2) + " "
        maximum = "p" * MAX_ACCOUNT_PASSWORD_UTF16_UNITS

        self.assertEqual(AccountPassword(minimum).value, minimum)
        self.assertEqual(AccountPassword(maximum).value, maximum)

    def test_counts_astral_characters_as_two_utf16_units(self) -> None:
        accepted = "😀" * (MIN_ACCOUNT_PASSWORD_UTF16_UNITS // 2)
        rejected = "😀" * (MIN_ACCOUNT_PASSWORD_UTF16_UNITS // 2 - 1) + "a"

        self.assertEqual(len(accepted.encode("utf-16-le")) // 2, 12)
        self.assertEqual(AccountPassword(accepted).value, accepted)
        with self.assertRaises(ValueError):
            AccountPassword(rejected)

    def test_rejects_out_of_range_and_unpaired_surrogate_inputs(self) -> None:
        for password in ("short", "p" * (MAX_ACCOUNT_PASSWORD_UTF16_UNITS + 1)):
            with self.subTest(length=len(password)), self.assertRaises(ValueError):
                AccountPassword(password)
        with self.assertRaises(ValueError):
            AccountPassword("p" * 11 + "\ud800")

    def test_representation_never_contains_the_secret(self) -> None:
        password = "synthetic-private-password"

        self.assertNotIn(password, repr(AccountPassword(password)))
