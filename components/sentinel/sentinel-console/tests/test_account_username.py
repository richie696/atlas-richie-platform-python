"""Username identity vectors shared with the React account model."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel_console.domain.account_username import (
    AccountUsername,
    canonicalize_username,
)


class AccountUsernameTest(unittest.TestCase):
    def test_trim_case_and_compatibility_forms_share_one_identity(self) -> None:
        spellings = (" Admin ", "admin", "Ａdmin")
        identities = [AccountUsername(spelling) for spelling in spellings]

        self.assertEqual({identity.lookup_key for identity in identities}, {identities[0].lookup_key})
        self.assertEqual([identity.value for identity in identities], ["Admin", "admin", "Ａdmin"])
        self.assertEqual(len(identities[0].lookup_key), 64)

    def test_unicode_whitespace_and_composed_forms_are_canonical(self) -> None:
        self.assertEqual(canonicalize_username("\ufeff\u00a0Admin\u3000"), "admin")
        self.assertEqual(canonicalize_username("A\u030a"), canonicalize_username("Å"))
        self.assertEqual(canonicalize_username("ΟΣ"), "ος")

    def test_matches_browser_utf16_limit_and_rejects_invalid_input(self) -> None:
        self.assertEqual(AccountUsername("a" * 200).value, "a" * 200)
        self.assertEqual(AccountUsername("😀" * 100).value, "😀" * 100)
        for value in ("a" * 201, "😀" * 101, " \ufeff\u3000", "\ud800"):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                AccountUsername(value)
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                canonicalize_username(value)

    def test_value_is_immutable_and_rejects_non_string(self) -> None:
        identity = AccountUsername("Operator")
        with self.assertRaises((AttributeError, TypeError)):
            identity.value = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            AccountUsername(42)  # type: ignore[arg-type]
