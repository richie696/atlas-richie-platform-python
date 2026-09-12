"""Secret registry 单元测试。

中文
----
覆盖 `SecretRegistry` 的互斥注册 + session 生命周期 + catalog 容器。

English
--------
Unit tests for `SecretRegistry`: mutex registration, session
lifecycle, and catalog container.
"""

from __future__ import annotations

import unittest

from atlas_richie.secret import (
    InMemorySecretProviderFactory,
    SecretBinding,
    SecretBindingCatalog,
    SecretException,
    SecretProviderConfiguration,
    SecretReference,
)


def _config(name: str = "test") -> SecretProviderConfiguration:
    return SecretProviderConfiguration(name=name)


class SecretRegistryMutexTest(unittest.TestCase):
    def setUp(self) -> None:
        from atlas_richie.secret import SecretRegistry
        SecretRegistry.reset()
        self.registry = SecretRegistry.instance()
        self.factory = InMemorySecretProviderFactory(name="test")
        self.session = self.factory.create(_config())

    def tearDown(self) -> None:
        from atlas_richie.secret import SecretRegistry
        SecretRegistry.reset()

    def test_register_creates_session(self) -> None:
        self.registry.register("test", self.session, factory=self.factory)
        self.assertEqual(self.registry.session("test").descriptor.name, "test")

    def test_double_register_raises(self) -> None:
        self.registry.register("test", self.session, factory=self.factory)
        with self.assertRaises(SecretException):
            self.registry.register("test", self.session, factory=self.factory)

    def test_unregister_closes_session(self) -> None:
        self.registry.register("test", self.session, factory=self.factory)
        self.assertFalse(self.session.is_closed)
        self.registry.unregister("test")
        self.assertTrue(self.session.is_closed)

    def test_unregister_unknown_is_noop(self) -> None:
        # Should not raise
        self.registry.unregister("never-registered")

    def test_active_single_provider(self) -> None:
        self.registry.register("only", self.session, factory=self.factory)
        self.assertEqual(self.registry.active(), "only")

    def test_active_multiple_providers_returns_none(self) -> None:
        self.registry.register("a", self.session, factory=self.factory)
        second = self.factory.create(_config())
        self.registry.register("b", second, factory=self.factory)
        self.assertIsNone(self.registry.active())


class SecretRegistryCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        from atlas_richie.secret import SecretRegistry
        SecretRegistry.reset()
        self.registry = SecretRegistry.instance()

    def tearDown(self) -> None:
        from atlas_richie.secret import SecretRegistry
        SecretRegistry.reset()

    def test_install_uninstall_catalog(self) -> None:
        binding = SecretBinding(
            name="db.password",
            reference=SecretReference(provider="vault", path="db/password"),
        )
        catalog = SecretBindingCatalog(name="default", bindings=(binding,))
        self.registry.install_catalog(catalog)
        catalogs = list(self.registry.catalogs())
        self.assertEqual(len(catalogs), 1)
        self.assertEqual(catalogs[0].name, "default")
        self.registry.uninstall_catalog("default")
        self.assertEqual(len(list(self.registry.catalogs())), 0)

    def test_install_replaces_by_name(self) -> None:
        first = SecretBindingCatalog(
            name="x",
            bindings=(SecretBinding(
                name="a",
                reference=SecretReference(provider="vault", path="a"),
            ),),
        )
        second = SecretBindingCatalog(
            name="x",
            bindings=(SecretBinding(
                name="b",
                reference=SecretReference(provider="vault", path="b"),
            ),),
        )
        self.registry.install_catalog(first)
        self.registry.install_catalog(second)
        catalogs = list(self.registry.catalogs())
        self.assertEqual(len(catalogs), 1)
        self.assertEqual(catalogs[0].bindings[0].name, "b")


if __name__ == "__main__":
    unittest.main()
