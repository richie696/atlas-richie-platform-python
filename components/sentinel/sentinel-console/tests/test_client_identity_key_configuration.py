"""Security configuration tests for login client identity pseudonymization."""

from __future__ import annotations

import base64
import unittest

from atlas_richie.sentinel_console.infrastructure.security.client_identity_key import (
    ClientIdentityKeyConfiguration,
    ClientIdentityKeyConfigurationError,
)

_ENV = "SENTINEL_CONSOLE_CLIENT_IDENTITY_HMAC_KEY"
_KEY = b"client-identity-key-for-tests-000000000000"


class ClientIdentityKeyConfigurationTests(unittest.TestCase):
    def test_decodes_and_hides_the_deployment_key(self) -> None:
        configuration = ClientIdentityKeyConfiguration.from_environment(
            {_ENV: base64.b64encode(_KEY).decode("ascii")}
        )

        self.assertEqual(configuration.hmac_key, _KEY)
        self.assertNotIn(_KEY.decode("ascii"), repr(configuration))

    def test_missing_invalid_and_short_keys_fail_closed(self) -> None:
        values = ({}, {_ENV: "%%"}, {_ENV: base64.b64encode(b"short").decode()})
        for environment in values:
            with self.subTest(environment=environment):
                with self.assertRaises(ClientIdentityKeyConfigurationError):
                    ClientIdentityKeyConfiguration.from_environment(environment)


if __name__ == "__main__":
    unittest.main()
