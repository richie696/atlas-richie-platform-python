"""Local providers 单元测试: InMemory / Env / File。

中文
----
覆盖三种 in-process backend 的契约行为。

English
--------
Unit tests for the in-process backends: InMemory, Env, File.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from atlas_richie.secret import (
    EnvSecretProviderFactory,
    FileSecretProviderFactory,
    InMemorySecretProviderFactory,
    SecretBackend,
    SecretProviderConfiguration,
    SecretReference,
    SecretVersion,
    SecretVersionSelector,
)


def _config(name: str = "test", **params: str) -> SecretProviderConfiguration:
    return SecretProviderConfiguration(name=name, parameters=params)


class InMemoryBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = InMemorySecretProviderFactory()
        self.session = self.factory.create(_config())
        self.provider = self.session.descriptor.name

    def test_put_then_get(self) -> None:
        reference = SecretReference(provider=self.provider, path="db.password")
        written = self.session.writer.put(reference, b"s3cr3t")
        self.assertEqual(written.plaintext, b"s3cr3t")
        read = self.session.operations.get(reference)
        self.assertEqual(read.plaintext, b"s3cr3t")

    def test_get_missing_raises_integrity(self) -> None:
        reference = SecretReference(provider=self.provider, path="missing")
        from atlas_richie.secret import SecretIntegrityException
        with self.assertRaises(SecretIntegrityException):
            self.session.operations.get(reference)

    def test_rotate_increments_version(self) -> None:
        reference = SecretReference(provider=self.provider, path="token")
        self.session.writer.put(reference, b"v1")
        rotated = self.session.writer.rotate(reference, b"v2")
        self.assertEqual(rotated.metadata.version.number, "v2")
        # latest returns the rotated value
        self.assertEqual(self.session.operations.get(reference).plaintext, b"v2")

    def test_static_version_pinned(self) -> None:
        reference = SecretReference(provider=self.provider, path="k")
        first = self.session.writer.put(reference, b"old")
        self.session.writer.rotate(reference, b"new")
        static = SecretVersionSelector.of_static(
            SecretVersion(number=first.metadata.version.number),
        )
        reference = reference.with_version(static)
        self.assertEqual(
            self.session.operations.get(reference).plaintext,
            b"old",
        )

    def test_delete_removes(self) -> None:
        reference = SecretReference(provider=self.provider, path="ephemeral")
        self.session.writer.put(reference, b"x")
        self.assertTrue(self.session.operations.exists(reference))
        self.session.deletable.delete(reference)
        self.assertFalse(self.session.operations.exists(reference))

    def test_list_filtered(self) -> None:
        self.session.writer.put(
            SecretReference(provider=self.provider, path="app.db.password"),
            b"1",
        )
        self.session.writer.put(
            SecretReference(provider=self.provider, path="app.cache.key"),
            b"2",
        )
        self.session.writer.put(
            SecretReference(provider=self.provider, path="other.token"),
            b"3",
        )
        all_refs = self.session.operations.list()
        self.assertEqual(len(all_refs), 3)
        app_refs = self.session.operations.list("app.")
        self.assertEqual(len(app_refs), 2)

    def test_session_close_blocks_io(self) -> None:
        self.session.close()
        from atlas_richie.secret import SecretException
        reference = SecretReference(provider=self.provider, path="k")
        with self.assertRaises(SecretException):
            self.session.operations.get(reference)


class EnvBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = EnvSecretProviderFactory(upper=True)
        self._saved = {}
        for key in ("APP_TEST_TOKEN", "app_other", "MY_KEY"):
            self._saved[key] = os.environ.pop(key, None)
        os.environ["APP_TEST_TOKEN"] = "abc123"
        os.environ["app_other"] = "raw"
        os.environ["MY_KEY"] = "upper"
        # `from_env` style: env var names are upper-cased path; the
        # factory's `upper=True` (default) means any-case path works.
        self.session = self.factory.create(_config(name="env"))

    def tearDown(self) -> None:
        for key in ("APP_TEST_TOKEN", "app_other", "MY_KEY"):
            os.environ.pop(key, None)
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value

    def test_uppercase_lookup(self) -> None:
        reference = SecretReference(
            provider=self.session.descriptor.name,
            path="APP_TEST_TOKEN",
        )
        value = self.session.operations.get(reference)
        self.assertEqual(value.as_str(), "abc123")
        self.assertEqual(value.metadata.backend, SecretBackend.ENV)

    def test_lowercase_path_also_resolves_with_upper_flag(self) -> None:
        reference = SecretReference(
            provider=self.session.descriptor.name,
            path="app_test_token",
        )
        value = self.session.operations.get(reference)
        self.assertEqual(value.as_str(), "abc123")

    def test_missing_env_raises(self) -> None:
        from atlas_richie.secret import SecretIntegrityException
        reference = SecretReference(
            provider=self.session.descriptor.name,
            path="DOES_NOT_EXIST",
        )
        with self.assertRaises(SecretIntegrityException):
            self.session.operations.get(reference)

    def test_writer_is_none(self) -> None:
        self.assertIsNone(self.session.writer)

    def test_list_filters(self) -> None:
        refs = self.session.operations.list("APP_")
        paths = {ref.path for ref in refs}
        self.assertIn("APP_TEST_TOKEN", paths)


class FileBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.factory = FileSecretProviderFactory()
        self.session = self.factory.create(
            _config(name="file", base_dir=str(self.base)),
        )
        self.provider = self.session.descriptor.name

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_atomic_write_then_read(self) -> None:
        reference = SecretReference(provider=self.provider, path="app/password")
        self.session.writer.put(reference, b"topsecret")
        self.assertEqual(
            self.session.operations.get(reference).plaintext,
            b"topsecret",
        )
        # File on disk
        self.assertTrue((self.base / "app" / "password").is_file())

    def test_path_traversal_rejected(self) -> None:
        from atlas_richie.secret import SecretConfigurationException
        reference = SecretReference(provider=self.provider, path="../etc/passwd")
        with self.assertRaises(SecretConfigurationException):
            self.session.operations.get(reference)

    def test_rotate_emits_snapshot(self) -> None:
        from atlas_richie.secret.snapshot import SecretSnapshotChangedEvent
        received: list[SecretSnapshotChangedEvent] = []
        self.session.snapshot_manager.register(
            type("Listener", (), {
                "on_snapshot_changed": lambda self, event: received.append(event),
            })(),
        )
        reference = SecretReference(provider=self.provider, path="rotation")
        self.session.writer.put(reference, b"v1")
        self.session.writer.rotate(reference, b"v2")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].current_metadata.backend, SecretBackend.FILE)

    def test_delete_then_read_raises(self) -> None:
        from atlas_richie.secret import SecretIntegrityException
        reference = SecretReference(provider=self.provider, path="gone")
        self.session.writer.put(reference, b"x")
        self.session.deletable.delete(reference)
        with self.assertRaises(SecretIntegrityException):
            self.session.operations.get(reference)


if __name__ == "__main__":
    unittest.main()
