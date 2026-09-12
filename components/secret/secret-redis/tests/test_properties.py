"""`RedisSecretProperties` unit tests (no Redis required).

中文
----
覆盖 pydantic-settings env 注入 + key 校验 + 内部 cache-redis
properties 转换。

English
--------
Unit tests for `RedisSecretProperties`: env injection, key validation,
and the `to_cache_properties()` conversion.
"""

from __future__ import annotations

import base64
import os
import unittest

from atlas_richie.secret_redis.properties import RedisSecretProperties


def _key_b64(byte: int = 0) -> str:
    return base64.b64encode(bytes([byte] * 32)).decode("ascii")


class RedisSecretPropertiesValidationTest(unittest.TestCase):
    def test_minimal_valid_properties(self) -> None:
        os.environ["ATLAS_RICHIE_SECRET_REDIS_URL"] = "redis://127.0.0.1:16379"
        os.environ["ATLAS_RICHIE_SECRET_REDIS_LOCAL_ENCRYPTION_KEY_B64"] = _key_b64()
        try:
            properties = RedisSecretProperties()
            self.assertEqual(properties.url, "redis://127.0.0.1:16379")
            self.assertEqual(properties.namespace, "atlas-richie-secret")
            self.assertEqual(properties.default_ttl_seconds, 0)
            self.assertEqual(properties.key_purpose, "encrypt")
        finally:
            for key in (
                "ATLAS_RICHIE_SECRET_REDIS_URL",
                "ATLAS_RICHIE_SECRET_REDIS_LOCAL_ENCRYPTION_KEY_B64",
            ):
                os.environ.pop(key, None)

    def test_short_key_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RedisSecretProperties(
                url="redis://127.0.0.1:16379",
                local_encryption_key_b64=base64.b64encode(b"\x00" * 16).decode("ascii"),
            )

    def test_long_key_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RedisSecretProperties(
                url="redis://127.0.0.1:16379",
                local_encryption_key_b64=base64.b64encode(b"\x00" * 64).decode("ascii"),
            )

    def test_invalid_base64_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RedisSecretProperties(
                url="redis://127.0.0.1:16379",
                local_encryption_key_b64="!!not-base64!!",
            )

    def test_decode_local_key_returns_32_bytes(self) -> None:
        properties = RedisSecretProperties(
            url="redis://127.0.0.1:16379",
            local_encryption_key_b64=_key_b64(0xAA),
        )
        self.assertEqual(len(properties.decode_local_key()), 32)
        self.assertEqual(properties.decode_local_key()[0], 0xAA)


class RedisSecretPropertiesConversionTest(unittest.TestCase):
    def test_to_cache_properties_mirrors_redis_fields(self) -> None:
        properties = RedisSecretProperties(
            url="redis://127.0.0.1:16379",
            namespace="custom",
            local_encryption_key_b64=_key_b64(),
            max_connections=10,
            socket_timeout=2.5,
        )
        cache_props = properties.to_cache_properties()
        self.assertEqual(cache_props.url, "redis://127.0.0.1:16379")
        self.assertEqual(cache_props.namespace, "custom")
        self.assertEqual(cache_props.max_connections, 10)
        self.assertEqual(cache_props.socket_timeout, 2.5)
        self.assertTrue(cache_props.ping_before_activate)

    def test_key_purpose_enum(self) -> None:
        properties = RedisSecretProperties(
            url="redis://127.0.0.1:16379",
            local_encryption_key_b64=_key_b64(),
            key_purpose="wrap",
        )
        from atlas_richie.secret.crypto.key import KeyPurpose

        self.assertEqual(properties.key_purpose_enum(), KeyPurpose.WRAP)
