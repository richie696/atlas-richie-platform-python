"""GlobalSecret facade 单元测试。

中文
----
覆盖 `GlobalSecret` / `GlobalSecretManager` 的 facade 行为:
- `install` / `uninstall` / `is_initialized` / `active`
- 一行 `resolve` / `write` / `rotate`
- callback 注册

English
--------
Facade unit tests for `GlobalSecret` / `GlobalSecretManager`:
`install` / `uninstall` / `is_initialized` / `active`; one-line
`resolve` / `write` / `rotate`; callback registration.
"""

from __future__ import annotations

import unittest

from atlas_richie.secret import (
    GlobalSecret,
    GlobalSecretManager,
    InMemorySecretProviderFactory,
    SecretProviderConfiguration,
    SecretReference,
    SecretRegistry,
    StubSecretCallback,
)


def _config(name: str = "test") -> SecretProviderConfiguration:
    return SecretProviderConfiguration(name=name)


class GlobalSecretFacadeTest(unittest.TestCase):
    def setUp(self) -> None:
        SecretRegistry.reset()
        self.factory = InMemorySecretProviderFactory(name="test")
        self.session = self.factory.create(_config())
        self.session.writer.put(
            SecretReference(provider="test", path="k"),
            b"v",
        )
        self.manager = GlobalSecretManager.from_sessions(
            [self.session],
            factories={"test": self.factory},
        )
        GlobalSecret.install(self.manager)

    def tearDown(self) -> None:
        GlobalSecret.uninstall()
        SecretRegistry.reset()

    def test_install_initialized_active(self) -> None:
        self.assertTrue(GlobalSecret.is_initialized())
        self.assertEqual(GlobalSecret.active(), "test")

    def test_resolve(self) -> None:
        value = GlobalSecret.resolve(
            SecretReference(provider="test", path="k"),
        )
        self.assertEqual(value.plaintext, b"v")

    def test_write_then_resolve(self) -> None:
        GlobalSecret.write(
            SecretReference(provider="test", path="new"),
            b"newval",
        )
        self.assertEqual(
            GlobalSecret.resolve(
                SecretReference(provider="test", path="new"),
            ).plaintext,
            b"newval",
        )

    def test_rotate(self) -> None:
        new_value = GlobalSecret.rotate(
            SecretReference(provider="test", path="k"),
            b"rotated",
        )
        self.assertEqual(new_value.plaintext, b"rotated")

    def test_register_callback_fires(self) -> None:
        callback = StubSecretCallback()
        GlobalSecret.register_callback(callback)
        # Trigger a read so the callback fires
        GlobalSecret.resolve(SecretReference(provider="test", path="k"))
        # At least one read should be recorded
        self.assertGreaterEqual(len(callback.reads), 1)


class GlobalSecretUninitializedTest(unittest.TestCase):
    def setUp(self) -> None:
        SecretRegistry.reset()

    def tearDown(self) -> None:
        SecretRegistry.reset()

    def test_resolve_without_install_raises(self) -> None:
        from atlas_richie.secret import SecretException
        with self.assertRaises(SecretException):
            GlobalSecret.resolve(
                SecretReference(provider="missing", path="k"),
            )


if __name__ == "__main__":
    unittest.main()
