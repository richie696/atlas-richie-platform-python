"""Focused wiring tests for the SQL-backed account command composition."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from atlas_richie.sentinel_console.infrastructure.persistence import (
    account_command_composition,
)
from atlas_richie.sentinel_console.infrastructure.security.account_command_keys import (
    AccountCommandKeyConfiguration,
)


class AccountCommandCompositionTests(unittest.TestCase):
    def test_passes_engine_and_key_ring_to_existing_use_case(self) -> None:
        engine = object()
        key_configuration = AccountCommandKeyConfiguration(
            "current",
            {
                "current": b"account-command-current-test-key-000000000000",
                "retained": b"account-command-retained-test-key-000000000000",
            },
        )

        with (
            patch.object(
                account_command_composition, "SqlAlchemyAccountCommandStore"
            ) as store,
            patch.object(
                account_command_composition, "PasswordHashService"
            ) as password_hasher,
            patch.object(
                account_command_composition, "MutateAccount"
            ) as mutate_account,
        ):
            result = account_command_composition.compose_sql_account_commands(
                engine, key_configuration
            )

        store.assert_called_once_with(engine)
        password_hasher.assert_called_once_with()
        mutate_account.assert_called_once_with(
            store=store.return_value,
            password_hasher=password_hasher.return_value,
            fingerprint_keys=key_configuration.fingerprint_keys,
            active_fingerprint_key_id="current",
        )
        self.assertIs(result, mutate_account.return_value)


if __name__ == "__main__":
    unittest.main()
