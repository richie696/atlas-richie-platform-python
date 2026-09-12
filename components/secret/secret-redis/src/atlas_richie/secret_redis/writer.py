"""Redis secret writer — put / rotate / delete via cache-redis infra + AES-GCM。

中文
----
对位 Java `cn.richie696.component.secret.provider.redis.RedisSecretWriter`。

`put` 流程:

1. 通过 `INCR @counter` 获取下一个单调版本号
2. `cipher.encrypt(plaintext, context)` → envelope
3. `codec.encode(envelope)` → JSON bytes
4. 写 `{path}@vN` 的值(可带 TTL)
5. 写 `{path}@current = "vN"` 指针

`rotate` 与 `put` 区别:rotate 强制生成新版本号(不覆盖已有);`put`
也是新版本号(不沿用旧)。Java 端 `put` 行为是"覆盖最新",Python
端选择"每次写都新版本号",因为 Redis K/V 便宜,版本历史是有用的
审计痕迹。

`delete` 流程:

1. 删除 `@current` 指针
2. 删 `@counter`
3. 删所有已存在的 `@vN` 键(通过 SCAN 找出)

`delete` 完成后,引用 resolve 抛 `SecretIntegrityException`(因为
`@current` 不存在)。

English
--------
Redis secret writer. `put` / `rotate` increment a counter, encrypt
the value via `DefaultSecretCipher`, store the envelope as JSON, and
update the `@current` pointer. `delete` removes the pointer, the
counter, and every `@vN` key.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from atlas_richie.cache_redis import RedisDistributedCache, RedisStringManager
from atlas_richie.secret.crypto import (
    ArseEnvelopeCodec,
    CipherEnvelope,
    CryptoContext,
    DefaultSecretCipher,
)
from atlas_richie.secret.errors import SecretException
from atlas_richie.secret.metadata import SecretBackend, SecretMetadata
from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret.snapshot import SecretSnapshotChangedEvent, SecretSnapshotManager
from atlas_richie.secret.value import SecretValue
from atlas_richie.secret.writer import SecretDeletable, SecretWriter

if TYPE_CHECKING:
    from atlas_richie.secret_redis.operations import RedisSecretOperations
    from atlas_richie.secret_redis.properties import RedisSecretProperties


_logger = logging.getLogger("atlas_richie.secret_redis.writer")


def _version_key(namespace: str, path: str, version_number: str) -> str:
    return f"{namespace}:{path}@v{version_number}"


def _current_key(namespace: str, path: str) -> str:
    return f"{namespace}:{path}@current"


def _counter_key(namespace: str, path: str) -> str:
    return f"{namespace}:{path}@counter"


def _list_versions_match(namespace: str, path: str) -> str:
    return f"{namespace}:{path}@v*"


@dataclass(slots=True)
class RedisSecretWriter:
    """`SecretWriter` + `SecretDeletable` implementation backed by Redis."""

    properties: "RedisSecretProperties"
    redis_string_manager: RedisStringManager
    redis_distributed_cache: RedisDistributedCache
    cipher: DefaultSecretCipher
    codec: ArseEnvelopeCodec
    operations: "RedisSecretOperations"
    snapshot_manager: SecretSnapshotManager

    def _build_secret_value(
        self,
        reference: SecretReference,
        plaintext: bytes,
        version_number: str,
    ) -> SecretValue:
        """Encrypt + serialize. The caller still needs to write
        the envelope bytes to Redis and update the @current pointer.
        """
        context = CryptoContext(
            primary_key=self.operations._key_ref(),  # noqa: SLF001 - same package
            purpose=self.properties.key_purpose_enum(),
            aad={
                "path": reference.path,
                "namespace": self.properties.namespace,
            },
        )
        envelope = self.cipher.encrypt(plaintext, context)
        serialized = self.codec.encode(envelope)
        now = datetime.now(tz=timezone.utc)
        metadata = SecretMetadata(
            reference=reference,
            version=SecretVersion(number=version_number, created_at=now),
            backend=SecretBackend.REDIS,
            created_at=now,
            expires_at=None,
            tags={
                "namespace": self.properties.namespace,
                "algorithm": envelope.algorithm,
            },
        )
        return SecretValue(plaintext=plaintext, metadata=metadata), serialized

    def _persist(
        self,
        reference: SecretReference,
        version_number: str,
        serialized: bytes,
    ) -> None:
        version_key = _version_key(
            self.properties.namespace, reference.path, version_number,
        )
        current_key = _current_key(self.properties.namespace, reference.path)
        if self.properties.default_ttl_seconds > 0:
            self.redis_string_manager.set_with_ttl(
                version_key,
                serialized,
                self.properties.default_ttl_seconds * 1000,
            )
        else:
            self.redis_string_manager.set(version_key, serialized)
        # Pointer update is the "publish" point — readers see the
        # new value as soon as the pointer flips. A crash between
        # the version write and the pointer write leaves the new
        # version orphaned (deleted by GC later) but never visible.
        self.redis_string_manager.set(current_key, version_number.encode("utf-8"))

    # --- SecretWriter protocol -----------------------------------------

    def put(
        self,
        reference: SecretReference,
        plaintext: bytes,
    ) -> SecretValue:
        counter_key = _counter_key(self.properties.namespace, reference.path)
        version_int = self.redis_string_manager.increment(counter_key)
        version_number = f"v{version_int}"
        value, serialized = self._build_secret_value(
            reference, plaintext, version_number,
        )
        self._persist(reference, version_number, serialized)
        return value

    def rotate(
        self,
        reference: SecretReference,
        new_plaintext: bytes,
    ) -> SecretValue:
        # `rotate` is implemented exactly like `put`: a new version is
        # always created. The snapshot event captures the previous
        # `current` value as `previous_metadata`.
        previous = None
        try:
            previous = self.operations.get(reference)
        except Exception:  # noqa: BLE001
            previous = None
        new_value = self.put(reference, new_plaintext)
        if previous is not None:
            self.snapshot_manager.publish(
                SecretSnapshotChangedEvent(
                    reference=reference,
                    previous_metadata=previous.metadata,
                    current_metadata=new_value.metadata,
                ),
            )
        return new_value

    # --- SecretDeletable protocol --------------------------------------

    def delete(self, reference: SecretReference) -> None:
        """Hard-delete all keys for `reference`: `@current`,
        `@counter`, and every `@vN` discovered via SCAN.
        """
        ns = self.properties.namespace
        path = reference.path
        # 1. Delete the versioned values via SCAN
        try:
            found = self.redis_string_manager.scan(
                _list_versions_match(ns, path), count=100, clazz=bytes,
            )
        except Exception as error:  # noqa: BLE001
            raise SecretException(
                f"redis: scan failed for {path!r}: {error}",
            ) from error
        for key in found:
            key_str = key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else str(key)
            try:
                self.redis_distributed_cache.delete(key_str)
            except Exception as error:  # noqa: BLE001
                _logger.warning(
                    "redis: failed to delete %s during delete(%r): %s",
                    key_str,
                    reference,
                    error,
                )
        # 2. Delete the current pointer and counter
        for key in (_current_key(ns, path), _counter_key(ns, path)):
            try:
                self.redis_distributed_cache.delete(key)
            except Exception as error:  # noqa: BLE001
                _logger.warning(
                    "redis: failed to delete %s during delete(%r): %s",
                    key,
                    reference,
                    error,
                )


__all__ = ["RedisSecretWriter"]


_ = (CipherEnvelope, Mapping, SecretDeletable, SecretWriter)
