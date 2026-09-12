"""Testkit 单元测试:StubSecretCallback / RecordingSnapshotListener / bundle。

中文
----
覆盖 `atlas_richie.secret.testkit` 提供的可复用测试夹具。

English
--------
Unit tests for the testkit sub-package: StubSecretCallback,
RecordingSnapshotListener, ProviderBundle.
"""

from __future__ import annotations

import unittest

from atlas_richie.secret import (
    InMemorySecretProviderFactory,
    ProviderBundle,
    RecordingSnapshotListener,
    SecretMetadata,
    SecretProviderConfiguration,
    SecretReference,
    SecretSnapshotChangedEvent,
    SecretSnapshotManager,
    SecretValue,
    StubSecretCallback,
    in_memory_fixture,
)


def _config(name: str = "test") -> SecretProviderConfiguration:
    return SecretProviderConfiguration(name=name)


class StubSecretCallbackTest(unittest.TestCase):
    def test_records_each_method(self) -> None:
        callback = StubSecretCallback()
        ref = SecretReference(provider="t", path="k")
        meta = SecretMetadata(
            reference=ref,
            version=__import__(
                "atlas_richie.secret",
                fromlist=["SecretVersion"],
            ).SecretVersion(number="v1"),
            backend=__import__(
                "atlas_richie.secret",
                fromlist=["SecretBackend"],
            ).SecretBackend.IN_MEMORY,
            created_at=__import__("datetime").datetime.now(
                tz=__import__("datetime").timezone.utc,
            ),
            expires_at=None,
            tags={},
        )
        value = SecretValue(plaintext=b"v", metadata=meta)
        callback.on_read(ref, value)
        callback.on_write(ref, value)
        callback.on_rotate(ref, None, value)
        callback.on_resolve_failure(ref, ValueError("x"))
        callback.on_metadata(ref, meta)
        self.assertEqual(len(callback.reads), 1)
        self.assertEqual(len(callback.writes), 1)
        self.assertEqual(len(callback.rotates), 1)
        self.assertEqual(len(callback.failures), 1)
        self.assertEqual(len(callback.metadatas), 1)


class RecordingSnapshotListenerTest(unittest.TestCase):
    def test_captures_published_events(self) -> None:
        manager = SecretSnapshotManager()
        listener = RecordingSnapshotListener()
        manager.register(listener)
        ref = SecretReference(provider="t", path="k")
        from atlas_richie.secret import SecretBackend, SecretVersion
        from datetime import datetime, timezone

        meta = SecretMetadata(
            reference=ref,
            version=SecretVersion(number="v1"),
            backend=SecretBackend.IN_MEMORY,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=None,
            tags={},
        )
        manager.publish(
            SecretSnapshotChangedEvent(
                reference=ref,
                previous_metadata=None,
                current_metadata=meta,
            ),
        )
        self.assertEqual(len(listener.events), 1)
        self.assertEqual(listener.events[0].current_metadata, meta)


class InMemoryFixtureTest(unittest.TestCase):
    def test_returns_factory_and_bundle(self) -> None:
        factory, bundle = in_memory_fixture(name="fx", version="1.0.0")
        self.assertIsInstance(factory, InMemorySecretProviderFactory)
        self.assertEqual(factory.name, "fx")
        self.assertIsInstance(bundle, ProviderBundle)
        self.assertIs(bundle.factory, factory)
        # Bundle's configuration should match
        self.assertEqual(bundle.configuration.name, "fx")


if __name__ == "__main__":
    unittest.main()
