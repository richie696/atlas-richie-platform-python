"""Deployment key parsing and secrecy tests for account commands."""

from __future__ import annotations

import base64
import unittest

from atlas_richie.sentinel_console.infrastructure.security.account_command_keys import (
    AccountCommandKeyConfiguration,
    AccountCommandKeyConfigurationError,
)

_ACTIVE = "SENTINEL_CONSOLE_ACCOUNT_FINGERPRINT_ACTIVE_KEY_ID"
_RING = "SENTINEL_CONSOLE_ACCOUNT_FINGERPRINT_KEY_RING"
_CURRENT_KEY = b"account-command-current-test-key-000000000000"
_RETAINED_KEY = b"account-command-retained-test-key-000000000000"


class AccountCommandKeyConfigurationTests(unittest.TestCase):
    def test_loads_active_and_retained_keys_as_an_immutable_secret_ring(self) -> None:
        values = {
            _ACTIVE: "current",
            _RING: (
                f"current={base64.b64encode(_CURRENT_KEY).decode('ascii')};"
                f"retained={base64.b64encode(_RETAINED_KEY).decode('ascii')}"
            ),
        }

        configuration = AccountCommandKeyConfiguration.from_environment(values)

        self.assertEqual(configuration.active_fingerprint_key_id, "current")
        self.assertEqual(configuration.fingerprint_keys["current"], _CURRENT_KEY)
        self.assertEqual(configuration.fingerprint_keys["retained"], _RETAINED_KEY)
        self.assertNotIn(_CURRENT_KEY.decode("ascii"), repr(configuration))
        with self.assertRaises(TypeError):
            configuration.fingerprint_keys["new"] = b"x" * 32

    def test_missing_settings_and_invalid_active_key_fail_closed(self) -> None:
        with self.assertRaises(AccountCommandKeyConfigurationError):
            AccountCommandKeyConfiguration.from_environment({_ACTIVE: "current"})
        with self.assertRaises(AccountCommandKeyConfigurationError):
            AccountCommandKeyConfiguration.from_environment(
                {
                    _ACTIVE: "missing",
                    _RING: f"current={base64.b64encode(_CURRENT_KEY).decode('ascii')}",
                }
            )

    def test_rejects_duplicate_ids_bad_base64_and_short_keys_without_echo(self) -> None:
        invalid_rings = (
            "same=YWJj;same=ZGVm",
            "current=%%%",
            f"current={base64.b64encode(b'short').decode('ascii')}",
        )
        for ring in invalid_rings:
            with self.subTest(ring=ring):
                with self.assertRaises(AccountCommandKeyConfigurationError) as raised:
                    AccountCommandKeyConfiguration.from_environment(
                        {_ACTIVE: "current", _RING: ring}
                    )
                self.assertNotIn(ring, str(raised.exception))

    def test_programmatic_configuration_requires_valid_ids_and_key_size(self) -> None:
        with self.assertRaises(AccountCommandKeyConfigurationError):
            AccountCommandKeyConfiguration("unknown", {"known": _CURRENT_KEY})
        with self.assertRaises(AccountCommandKeyConfigurationError):
            AccountCommandKeyConfiguration("current", {"current": b"short"})


if __name__ == "__main__":
    unittest.main()
