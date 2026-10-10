"""Deployment key parsing and secrecy tests for rule commands."""

from __future__ import annotations

import base64
import unittest

from atlas_richie.sentinel_console.infrastructure.security.rule_command_keys import (
    RuleCommandKeyConfiguration,
    RuleCommandKeyConfigurationError,
)

_ACTIVE = "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID"
_RING = "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING"
_CURRENT_KEY = b"rule-command-current-test-key-000000000000"
_RETAINED_KEY = b"rule-command-retained-test-key-00000000000"


class RuleCommandKeyConfigurationTests(unittest.TestCase):
    def test_optional_environment_loader_distinguishes_absent_from_partial_keys(self) -> None:
        self.assertIsNone(RuleCommandKeyConfiguration.from_optional_environment({}))
        with self.assertRaises(RuleCommandKeyConfigurationError):
            RuleCommandKeyConfiguration.from_optional_environment({_ACTIVE: "current"})

    def test_loads_active_and_retained_keys_as_an_immutable_secret_ring(self) -> None:
        values = {
            _ACTIVE: "current",
            _RING: (
                f"current={base64.b64encode(_CURRENT_KEY).decode('ascii')};"
                f"retained={base64.b64encode(_RETAINED_KEY).decode('ascii')}"
            ),
        }

        configuration = RuleCommandKeyConfiguration.from_environment(values)

        self.assertEqual(configuration.active_fingerprint_key_id, "current")
        self.assertEqual(configuration.fingerprint_keys["current"], _CURRENT_KEY)
        self.assertEqual(configuration.fingerprint_keys["retained"], _RETAINED_KEY)
        self.assertNotIn(_CURRENT_KEY.decode("ascii"), repr(configuration))
        with self.assertRaises(TypeError):
            configuration.fingerprint_keys["new"] = b"x" * 32

    def test_missing_or_unknown_active_settings_fail_closed(self) -> None:
        with self.assertRaises(RuleCommandKeyConfigurationError):
            RuleCommandKeyConfiguration.from_environment({_ACTIVE: "current"})
        with self.assertRaises(RuleCommandKeyConfigurationError):
            RuleCommandKeyConfiguration.from_environment(
                {
                    _ACTIVE: "missing",
                    _RING: f"current={base64.b64encode(_CURRENT_KEY).decode('ascii')}",
                }
            )

    def test_rejects_invalid_key_rings_without_echo(self) -> None:
        invalid_rings = (
            "same=YWJj;same=ZGVm",
            "current=%%%@",
            f"current={base64.b64encode(b'short').decode('ascii')}",
        )
        for ring in invalid_rings:
            with self.subTest(ring=ring):
                with self.assertRaises(RuleCommandKeyConfigurationError) as raised:
                    RuleCommandKeyConfiguration.from_environment(
                        {_ACTIVE: "current", _RING: ring}
                    )
                self.assertNotIn(ring, str(raised.exception))

    def test_programmatic_configuration_rejects_invalid_ids_and_key_sizes(self) -> None:
        with self.assertRaises(RuleCommandKeyConfigurationError):
            RuleCommandKeyConfiguration("unknown", {"known": _CURRENT_KEY})
        with self.assertRaises(RuleCommandKeyConfigurationError):
            RuleCommandKeyConfiguration("current", {"current": b"short"})


if __name__ == "__main__":
    unittest.main()
