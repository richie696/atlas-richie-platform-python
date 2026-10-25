"""Deployment parsing tests for the SQL-backed login-attempt policy."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel_console.infrastructure.persistence import (
    login_attempt_configuration,
)

LoginAttemptLimitConfiguration = (
    login_attempt_configuration.LoginAttemptLimitConfiguration
)
LoginAttemptLimitConfigurationError = (
    login_attempt_configuration.LoginAttemptLimitConfigurationError
)

_THRESHOLD = "SENTINEL_CONSOLE_LOGIN_FAILURE_THRESHOLD"
_WINDOW = "SENTINEL_CONSOLE_LOGIN_FAILURE_WINDOW_SECONDS"
_BLOCK = "SENTINEL_CONSOLE_LOGIN_BLOCK_DURATION_SECONDS"


class LoginAttemptLimitConfigurationTests(unittest.TestCase):
    def test_reads_all_required_values_and_builds_the_existing_policy(self) -> None:
        configuration = LoginAttemptLimitConfiguration.from_environment(
            {_THRESHOLD: "7", _WINDOW: "300", _BLOCK: "900"}
        )

        policy = configuration.to_policy()
        self.assertEqual(configuration.failure_threshold, 7)
        self.assertEqual(policy.failure_threshold, 7)
        self.assertEqual(policy.window.total_seconds(), 300)
        self.assertEqual(policy.block_duration.total_seconds(), 900)

    def test_missing_or_noncanonical_values_fail_without_echoing_input(self) -> None:
        valid = {_THRESHOLD: "5", _WINDOW: "60", _BLOCK: "600"}
        invalid_values = ("", "0", "-1", "+5", " 5", "05", "1.5", "secret")
        for name in (_THRESHOLD, _WINDOW, _BLOCK):
            with self.subTest(missing=name):
                settings = dict(valid)
                settings.pop(name)
                with self.assertRaises(LoginAttemptLimitConfigurationError):
                    LoginAttemptLimitConfiguration.from_environment(settings)
            for value in invalid_values:
                with self.subTest(name=name, value=value):
                    settings = {**valid, name: value}
                    with self.assertRaises(
                        LoginAttemptLimitConfigurationError
                    ) as raised:
                        LoginAttemptLimitConfiguration.from_environment(settings)
                    if value:
                        self.assertNotIn(value, str(raised.exception))

    def test_rejects_integer_overflow(self) -> None:
        for overflow in ("2147483648", "9" * 5_000):
            with self.subTest(length=len(overflow)):
                with self.assertRaises(LoginAttemptLimitConfigurationError):
                    LoginAttemptLimitConfiguration.from_environment(
                        {_THRESHOLD: overflow, _WINDOW: "60", _BLOCK: "600"}
                    )

    def test_rejects_non_integer_programmatic_values(self) -> None:
        with self.assertRaises(LoginAttemptLimitConfigurationError):
            LoginAttemptLimitConfiguration(True, 60, 600)


if __name__ == "__main__":
    unittest.main()
