"""Focused contract checks for encrypted runtime database locator storage."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path

import pytest

from atlas_richie.sentinel_console.application.runtime_database_locator import (
    RuntimeDatabaseLocatorConflict,
    RuntimeDatabaseLocatorError,
    RuntimeDatabaseTarget,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    runtime_database_locator_file_store as locator_store,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    runtime_database_locator_configuration as locator_configuration,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)


def _store(
    path: Path, *, key: bytes | None = None
) -> locator_store.RuntimeDatabaseLocatorFileStore:
    return locator_store.RuntimeDatabaseLocatorFileStore(
        path,
        AesGcmSecretCipher("active", {"active": key or bytes(range(32))}),
    )


def test_locator_is_encrypted_and_compare_and_swap_is_enforced(
    tmp_path: Path,
) -> None:
    locator_path = tmp_path / "runtime.json"
    store = _store(locator_path)
    database_url = "postgresql+psycopg://operator:long-secret@db.local/console"

    async def scenario() -> None:
        assert await store.read() is None
        first = await store.write(database_url, expected_revision=None)

        assert first.database_url == database_url
        assert database_url.encode() not in locator_path.read_bytes()
        assert database_url not in repr(first)
        loaded_first = await store.read()
        assert loaded_first is not None
        assert loaded_first.database_url == database_url
        assert loaded_first.revision == first.revision
        assert locator_path.stat().st_mode & 0o777 == 0o600
        lock_mode = locator_path.with_name(".runtime.json.lock").stat().st_mode & 0o777
        assert lock_mode == 0o600

        updated = await store.write(
            "mysql+asyncmy://operator:other-secret@db.local/console",
            expected_revision=first.revision,
        )
        assert updated.revision != first.revision
        loaded_updated = await store.read()
        assert loaded_updated is not None
        assert loaded_updated.database_url == updated.database_url
        assert loaded_updated.revision == updated.revision

        with pytest.raises(RuntimeDatabaseLocatorConflict):
            await store.write(database_url, expected_revision=first.revision)

    asyncio.run(scenario())


def test_pinned_target_is_authenticated_inside_the_encrypted_locator(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.json"
    store = _store(path)
    database_url = "mysql+asyncmy://operator:long-secret@db.local/console"
    target = RuntimeDatabaseTarget(
        "db.local", ("10.20.0.4", "2001:db8::4")
    )

    async def scenario() -> None:
        written = await store.write(
            database_url,
            expected_revision=None,
            target=target,
        )
        raw = path.read_bytes()
        assert b"db.local" not in raw
        assert b"10.20.0.4" not in raw
        assert b"long-secret" not in raw
        loaded = await store.read()
        assert loaded == written
        assert loaded is not None
        assert loaded.target == target
        assert "long-secret" not in repr(loaded)
        assert "10.20.0.4" in repr(loaded)

    asyncio.run(scenario())


def test_legacy_v1_locator_remains_readable_without_claiming_a_pin(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.json"
    cipher = AesGcmSecretCipher("active", {"active": bytes(range(32))})
    revision = "a3f0c28b-05ee-4a8d-90e9-bdef63fdbff7"
    database_url = "postgresql+psycopg://operator:secret@db.local/console"
    envelope = cipher.encrypt(database_url, locator_store._context(revision))
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "revision": revision,
                "format": envelope.format.value,
                "key_id": envelope.key_id,
                "payload": base64.b64encode(envelope.payload).decode("ascii"),
            }
        )
    )
    os.chmod(path, 0o600)

    locator = asyncio.run(_store(path).read())
    assert locator is not None
    assert locator.database_url == database_url
    assert locator.target is None


def test_concurrent_first_writes_have_one_winner(tmp_path: Path) -> None:
    store = _store(tmp_path / "runtime.json")

    async def scenario() -> None:
        outcomes = await asyncio.gather(
            store.write("postgresql+psycopg://a:s@db/a", expected_revision=None),
            store.write("postgresql+psycopg://b:s@db/b", expected_revision=None),
            return_exceptions=True,
        )

        assert sum(not isinstance(item, BaseException) for item in outcomes) == 1
        conflicts = sum(
            isinstance(item, RuntimeDatabaseLocatorConflict) for item in outcomes
        )
        assert conflicts == 1
        assert await store.read() is not None

    asyncio.run(scenario())


def test_wrong_key_and_tampered_payload_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    asyncio.run(
        _store(path).write("postgresql+psycopg://a:s@db/a", expected_revision=None)
    )

    with pytest.raises(RuntimeDatabaseLocatorError):
        asyncio.run(_store(path, key=b"x" * 32).read())

    document = json.loads(path.read_text())
    document["payload"] = document["payload"][:-4] + "AAAA"
    path.write_text(json.dumps(document))
    os.chmod(path, 0o600)
    with pytest.raises(RuntimeDatabaseLocatorError):
        asyncio.run(_store(path).read())


def test_unsafe_locator_mode_and_symlink_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    path = tmp_path / "runtime.json"
    asyncio.run(
        _store(path).write("postgresql+psycopg://a:s@db/a", expected_revision=None)
    )
    os.chmod(path, 0o644)
    with pytest.raises(RuntimeDatabaseLocatorError):
        asyncio.run(_store(path).read())
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(RuntimeDatabaseLocatorError):
        asyncio.run(_store(path).read())


def test_deployment_configuration_keeps_key_material_hidden_and_builds_store(
    tmp_path: Path,
) -> None:
    active_key = bytes(range(32))
    retained_key = bytes(reversed(range(32)))
    configuration = (
        locator_configuration.RuntimeDatabaseLocatorConfiguration.from_environment(
            {
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH": str(
                    tmp_path / "runtime.json"
                ),
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_ACTIVE_KEY_ID": "active",
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_KEY_RING": (
                    f"active={base64.b64encode(active_key).decode()};"
                    f"retained={base64.b64encode(retained_key).decode()}"
                ),
            }
        )
    )
    assert active_key not in repr(configuration).encode()
    store = configuration.create_store()
    locator = asyncio.run(
        store.write(
            "postgresql+psycopg://operator:secret@db/console",
            expected_revision=None,
        )
    )
    assert locator.database_url.endswith("@db/console")


def test_deployment_configuration_rejects_missing_or_invalid_key_material() -> None:
    with pytest.raises(locator_configuration.RuntimeDatabaseLocatorConfigurationError):
        locator_configuration.RuntimeDatabaseLocatorConfiguration.from_environment({})

    with pytest.raises(locator_configuration.RuntimeDatabaseLocatorConfigurationError):
        locator_configuration.RuntimeDatabaseLocatorConfiguration.from_environment(
            {
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH": "relative/runtime.json",
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_ACTIVE_KEY_ID": "active",
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_KEY_RING": (
                    "active=" + base64.b64encode(b"short").decode()
                ),
            }
        )
