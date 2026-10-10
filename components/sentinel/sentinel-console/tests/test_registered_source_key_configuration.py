"""Deployment key configuration parsing and source-store composition tests."""

from __future__ import annotations

import base64
import asyncio
import unittest

from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.infrastructure.persistence.registered_source_composition import (
    compose_registered_source_store,
)
from atlas_richie.sentinel_console.infrastructure.persistence.registered_source_store import (
    SqlAlchemyRegisteredSourceStore,
)
from atlas_richie.sentinel_console.infrastructure.security.registered_source_keys import (
    RegisteredSourceKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    SecretContext,
)

_SECRET_KEY = b"s" * 32
_RETIRED_SECRET_KEY = b"r" * 32
_FINGERPRINT_KEY = b"f" * 32


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _environment() -> dict[str, str]:
    return {
        "SENTINEL_CONSOLE_SOURCE_SECRET_ACTIVE_KEY_ID": "secret-v2",
        "SENTINEL_CONSOLE_SOURCE_SECRET_KEY_RING": (
            f"secret-v1={_encoded(_RETIRED_SECRET_KEY)};"
            f"secret-v2={_encoded(_SECRET_KEY)}"
        ),
        "SENTINEL_CONSOLE_SOURCE_FINGERPRINT_ACTIVE_KEY_ID": "fingerprint-v1",
        "SENTINEL_CONSOLE_SOURCE_FINGERPRINT_KEY_RING": (
            f"fingerprint-v1={_encoded(_FINGERPRINT_KEY)}"
        ),
    }


class RegisteredSourceKeyConfigurationTests(unittest.TestCase):
    def test_loads_active_and_retained_keyrings_and_hides_material(self) -> None:
        config = RegisteredSourceKeyConfiguration.from_environment(_environment())

        self.assertEqual(config.active_secret_key_id, "secret-v2")
        self.assertEqual(config.secret_keys["secret-v1"], _RETIRED_SECRET_KEY)
        self.assertEqual(config.secret_keys["secret-v2"], _SECRET_KEY)
        self.assertEqual(config.active_fingerprint_key_id, "fingerprint-v1")
        self.assertNotIn(_encoded(_SECRET_KEY), repr(config))
        self.assertNotIn(_encoded(_FINGERPRINT_KEY), repr(config))

    def test_loaded_keyring_constructs_cipher_and_encrypts_with_active_key(self) -> None:
        config = RegisteredSourceKeyConfiguration.from_environment(_environment())
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        store = compose_registered_source_store(engine, config)

        self.assertIsInstance(store, SqlAlchemyRegisteredSourceStore)
        cipher = config.create_secret_cipher()
        envelope = cipher.encrypt(
            "synthetic-credential",
            SecretContext("configuration-source", "source-1", "authentication"),
        )
        self.assertEqual(envelope.key_id, "secret-v2")
        self.assertEqual(
            cipher.decrypt(
                envelope,
                SecretContext(
                    "configuration-source", "source-1", "authentication"
                ),
            ),
            "synthetic-credential",
        )

        asyncio.run(engine.dispose())

    def test_rejects_missing_and_malformed_key_configuration(self) -> None:
        environment = _environment()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            RegisteredSourceKeyConfiguration.from_environment({})

        cases = (
            {
                **environment,
                "SENTINEL_CONSOLE_SOURCE_SECRET_KEY_RING": (
                    "secret-v1=YWJj;secret-v1=ZGVm"
                ),
            },
            {
                **environment,
                "SENTINEL_CONSOLE_SOURCE_SECRET_KEY_RING": "secret-v2=not-base64!",
            },
            {
                **environment,
                "SENTINEL_CONSOLE_SOURCE_SECRET_KEY_RING": "secret-v2=YWJj",
            },
            {
                **environment,
                "SENTINEL_CONSOLE_SOURCE_SECRET_ACTIVE_KEY_ID": "absent",
            },
            {
                **environment,
                "SENTINEL_CONSOLE_SOURCE_FINGERPRINT_KEY_RING": (
                    f"fingerprint-v1={_encoded(b'short')}"
                ),
            },
        )
        for invalid_environment in cases:
            with self.subTest(invalid_environment=invalid_environment):
                with self.assertRaises(ValueError):
                    RegisteredSourceKeyConfiguration.from_environment(
                        invalid_environment
                    )


if __name__ == "__main__":
    unittest.main()
