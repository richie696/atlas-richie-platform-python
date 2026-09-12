"""DefaultSecretResolver 单元测试。

中文
----
覆盖 `DefaultSecretResolver` 的路由 + callback 触发 + failure 转译。

English
--------
Unit tests for `DefaultSecretResolver`: routing, callback chain,
failure translation.
"""

from __future__ import annotations

import unittest

from atlas_richie.secret import (
    DefaultSecretResolver,
    InMemorySecretProviderFactory,
    SecretCallback,
    SecretConfigurationException,
    SecretException,
    SecretIntegrityException,
    SecretMetadata,
    SecretProviderConfiguration,
    SecretReference,
    SecretValue,
    StubSecretCallback,
)


def _config(name: str = "test") -> SecretProviderConfiguration:
    return SecretProviderConfiguration(name=name)


class ResolverRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        from atlas_richie.secret import SecretRegistry
        SecretRegistry.reset()
        self.registry = SecretRegistry.instance()
        self.factory = InMemorySecretProviderFactory()
        self.session = self.factory.create(_config())
        self.registry.register("a", self.session, factory=self.factory)

    def tearDown(self) -> None:
        from atlas_richie.secret import SecretRegistry
        SecretRegistry.reset()

    def test_resolve_known_provider(self) -> None:
        reference = SecretReference(provider="a", path="k")
        self.session.writer.put(reference, b"v")
        resolver = DefaultSecretResolver(providers={"a": self.session})
        self.assertEqual(resolver.resolve(reference).plaintext, b"v")

    def test_resolve_unknown_provider_raises(self) -> None:
        reference = SecretReference(provider="zzz", path="k")
        resolver = DefaultSecretResolver(providers={"a": self.session})
        with self.assertRaises(SecretConfigurationException):
            resolver.resolve(reference)

    def test_resolve_missing_secret_raises_integrity(self) -> None:
        reference = SecretReference(provider="a", path="absent")
        resolver = DefaultSecretResolver(providers={"a": self.session})
        with self.assertRaises(SecretIntegrityException):
            resolver.resolve(reference)

    def test_resolve_destroyable_zeroes(self) -> None:
        reference = SecretReference(provider="a", path="k")
        self.session.writer.put(reference, b"plain")
        resolver = DefaultSecretResolver(providers={"a": self.session})
        with resolver.resolve_destroyable(reference) as handle:
            self.assertEqual(handle.value.plaintext, b"plain")
        # after exiting the context, value is destroyed
        with self.assertRaises(RuntimeError):
            _ = handle.value.plaintext  # type: ignore[attr-defined]


class ResolverCallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        from atlas_richie.secret import SecretRegistry
        SecretRegistry.reset()
        self.registry = SecretRegistry.instance()
        self.factory = InMemorySecretProviderFactory()
        self.session = self.factory.create(_config())
        self.registry.register("a", self.session, factory=self.factory)

    def tearDown(self) -> None:
        from atlas_richie.secret import SecretRegistry
        SecretRegistry.reset()

    def test_callback_records_reads_writes_rotates(self) -> None:
        callback = StubSecretCallback()
        resolver = DefaultSecretResolver(
            providers={"a": self.session},
            callbacks=(callback,),
        )
        reference = SecretReference(provider="a", path="k")
        resolver.write(reference, b"v1")
        resolver.resolve(reference)
        resolver.rotate(reference, b"v2")
        self.assertEqual(len(callback.writes), 1)
        self.assertEqual(len(callback.reads), 1)
        self.assertEqual(len(callback.rotates), 1)
        self.assertEqual(callback.rotates[0][2].plaintext, b"v2")

    def test_callback_failure_on_missing(self) -> None:
        callback = StubSecretCallback()
        resolver = DefaultSecretResolver(
            providers={"a": self.session},
            callbacks=(callback,),
        )
        reference = SecretReference(provider="a", path="absent")
        with self.assertRaises(SecretIntegrityException):
            resolver.resolve(reference)
        self.assertEqual(len(callback.failures), 1)
        self.assertIsInstance(callback.failures[0][1], SecretException)

    def test_callback_exception_does_not_break_resolver(self) -> None:
        class BrokenCallback:
            def on_read(self, reference, value):
                raise RuntimeError("intentional")

            def on_write(self, reference, value):
                raise RuntimeError("intentional")

            def on_rotate(self, reference, previous, current):
                raise RuntimeError("intentional")

            def on_resolve_failure(self, reference, error):
                raise RuntimeError("intentional")

            def on_metadata(self, reference, metadata):
                raise RuntimeError("intentional")

        resolver = DefaultSecretResolver(
            providers={"a": self.session},
            callbacks=(BrokenCallback(),),
        )
        reference = SecretReference(provider="a", path="k")
        # Should not raise despite broken callback
        self.session.writer.put(reference, b"v")
        value = resolver.resolve(reference)
        self.assertEqual(value.plaintext, b"v")


if __name__ == "__main__":
    unittest.main()
