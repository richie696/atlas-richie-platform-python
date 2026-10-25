"""Focused wiring tests for the SQL-backed login composition."""

from __future__ import annotations

from datetime import timedelta
import unittest
from unittest.mock import patch

from atlas_richie.sentinel_console.infrastructure.persistence import (
    login_attempt_configuration,
    login_composition,
)

LoginAttemptLimitConfiguration = (
    login_attempt_configuration.LoginAttemptLimitConfiguration
)


class SqlLoginCompositionTests(unittest.TestCase):
    def test_passes_explicit_engine_and_policies_to_existing_login_ports(self) -> None:
        engine = object()
        attempt_limit = LoginAttemptLimitConfiguration(6, 120, 900)
        session_ttl = timedelta(hours=8)

        with (
            patch.object(
                login_composition, "SqlAlchemyLoginCredentialReader"
            ) as credential_reader,
            patch.object(
                login_composition, "SqlAlchemyLoginSessionWriter"
            ) as session_writer,
            patch.object(
                login_composition, "SqlAlchemyLoginAttemptLimiter"
            ) as attempt_limiter,
            patch.object(
                login_composition, "PasswordHashService"
            ) as password_hasher,
            patch.object(login_composition, "Login") as login,
        ):
            result = login_composition.compose_sql_login(
                engine,
                attempt_limit=attempt_limit,
                session_ttl=session_ttl,
            )

        credential_reader.assert_called_once_with(engine)
        session_writer.assert_called_once_with(engine)
        attempt_limiter.assert_called_once_with(
            engine,
            policy=attempt_limit.to_policy(),
            additional_dialect_adapters=(),
        )
        password_hasher.assert_called_once_with()
        login.assert_called_once_with(
            credential_reader=credential_reader.return_value,
            session_writer=session_writer.return_value,
            attempt_limiter=attempt_limiter.return_value,
            password_hasher=password_hasher.return_value,
            session_ttl=session_ttl,
        )
        self.assertIs(result, login.return_value)


if __name__ == "__main__":
    unittest.main()
