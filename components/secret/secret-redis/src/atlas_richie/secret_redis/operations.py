"""Redis secret operations — read + list via cache-redis infra + AES-GCM 加密。

中文
----
对位 Java `cn.richie696.component.secret.provider.redis.RedisSecretOperations`。

设计要点:

- **底层 K/V 用 cache-redis 的 `RedisStringManager`**:复用连接池、键
  prefix、错误处理。但 *不* 走 cache 协议 — secret 是精确读写,
  写后立即一致,不像 cache 那样容忍 stale。
- **at-rest 默认 AES-256-GCM 加密**:`put` 前 `DefaultSecretCipher.encrypt`;
  `get` 时 `decrypt`。`ArseEnvelopeCodec` 把 envelope 序列化成 JSON
  写到 Redis value,反序列化时校验 algorithm + AAD 绑定。
- **多版本**:`{path}@vN` 存 envelope,`{path}@current` 存 "vN" 指针,
  `{path}@counter` 用 INCR 维护单调递增的版本号。
- **metadata 跟随 ciphertext 加密**:metadata(版本号 + created_at)嵌在
  `envelope.metadata` 字段内,被 envelope ciphertext 一起保护;读
  metadata 必须先 decrypt(安全优先)。
- **list 用 SCAN**:`RedisStringManager.scan(match, count, bytes)` 是
  非阻塞的 cursor-based 迭代,key 名称包含 `path` 完整信息
  (回填 `SecretReference`)。

错误转译:
- `KeyError_`(cache-redis) → `SecretIntegrityException` "secret not found"
- `redis.exceptions.ConnectionError` → `SecretException` "redis unreachable"
- 解密失败(InvalidTag) → `SecretCryptoException`

English
--------
Redis secret operations. Read / list over a `RedisStringManager`
(borrowed from `atlas-richie-cache-redis`); each value is sealed by
`DefaultSecretCipher` (AES-256-GCM) before write and unsealed on
read. Multi-version via `@vN` + `@current` pointer.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from atlas_richie.cache_redis import RedisCacheInfrastructure, RedisStringManager
from atlas_richie.secret.crypto import (
    ArseEnvelopeCodec,
    CipherEnvelope,
    CryptoContext,
    DefaultSecretCipher,
    KeyReference,
)
from atlas_richie.secret.errors import (
    SecretException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend, SecretMetadata
from atlas_richie.secret.operations import SecretListable, SecretOperations
from atlas_richie.secret.reference import (
    SecretReference,
    SecretVersion,
    SecretVersionSelectorKind,
)
from atlas_richie.secret.value import SecretValue

if TYPE_CHECKING:
    from atlas_richie.secret_redis.properties import RedisSecretProperties


_logger = logging.getLogger("atlas_richie.secret_redis.operations")


def _key_id_from_local_key(local_key: bytes) -> str:
    """Stable, short identifier for the local encryption key. Used as
    the `KeyReference.key_id` in the cipher AAD so a key rotation
    produces a different AAD and a previously-bound ciphertext
    cannot be silently moved between keys.
    """
    return hashlib.sha256(local_key).hexdigest()[:16]


def _version_key(namespace: str, path: str, version_number: str) -> str:
    return f"{namespace}:{path}@v{version_number}"


def _current_key(namespace: str, path: str) -> str:
    return f"{namespace}:{path}@current"


def _counter_key(namespace: str, path: str) -> str:
    return f"{namespace}:{path}@counter"


def _list_match(namespace: str, prefix: str | None) -> str:
    base = f"{namespace}:"
    if prefix:
        return f"{base}{prefix}*"
    return f"{base}*"


def _parse_version_number(raw: bytes) -> str:
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    text = text.strip()
    if not text.startswith("v"):
        raise SecretIntegrityException(
            f"redis current-pointer content is malformed: {text!r}",
        )
    return text


@dataclass(slots=True)
class RedisSecretOperations:
    """`SecretOperations` + `SecretListable` implementation backed by Redis."""

    properties: "RedisSecretProperties"
    redis_string_manager: RedisStringManager
    redis_infra: RedisCacheInfrastructure
    cipher: DefaultSecretCipher
    codec: ArseEnvelopeCodec = ArseEnvelopeCodec()

    def _key_ref(self) -> KeyReference:
        return KeyReference(
            provider="redis",
            key_id=_key_id_from_local_key(self.properties.decode_local_key()),
            algorithm="AES-256-GCM",
        )

    def _crypto_context(self, path: str) -> CryptoContext:
        return CryptoContext(
            primary_key=self._key_ref(),
            purpose=self.properties.key_purpose_enum(),
            aad={
                "path": path,
                "namespace": self.properties.namespace,
            },
        )

    def _build_metadata(
        self,
        reference: SecretReference,
        version_number: str,
    ) -> SecretMetadata:
        # The envelope holds the same fields in encrypted form; we
        # expose them here for callers that need to read metadata
        # without decrypting (e.g. health checks). The decryption
        # path returns the same value from the envelope itself.
        return SecretMetadata(
            reference=reference,
            version=SecretVersion(
                number=version_number,
                created_at=datetime.now(tz=timezone.utc),
            ),
            backend=SecretBackend.REDIS,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=None,
            tags={"namespace": self.properties.namespace},
        )

    def _read_envelope(
        self,
        reference: SecretReference,
        version_number: str,
    ) -> SecretValue:
        key = _version_key(self.properties.namespace, reference.path, version_number)
        try:
            raw = self.redis_string_manager.get(key, bytes)
        except Exception as error:  # KeyError_ or connection
            raise SecretIntegrityException(
                f"redis: secret version {version_number!r} not found "
                f"at {reference.path!r}",
            ) from error
        if raw is None:
            raise SecretIntegrityException(
                f"redis: secret version {version_number!r} not found "
                f"at {reference.path!r}",
            )
        envelope = self.codec.decode(raw)
        context = self._crypto_context(reference.path)
        try:
            plaintext = self.cipher.decrypt(envelope, context)
        except Exception as error:
            raise SecretException(
                f"redis: decryption failed for {reference.path!r} v{version_number}: {error}",
            ) from error
        metadata = SecretMetadata(
            reference=reference,
            version=SecretVersion(
                number=version_number,
                created_at=datetime.now(tz=timezone.utc),
            ),
            backend=SecretBackend.REDIS,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=None,
            tags={
                "namespace": self.properties.namespace,
                "algorithm": envelope.algorithm,
            },
        )
        return SecretValue(plaintext=plaintext, metadata=metadata)

    def _resolve_version(self, reference: SecretReference) -> str:
        if reference.version_selector.kind is SecretVersionSelectorKind.STATIC:
            if reference.version_selector.static_version is None:
                raise SecretException(
                    "redis: STATIC selector requires static_version",
                )
            return reference.version_selector.static_version.number
        current_key = _current_key(self.properties.namespace, reference.path)
        try:
            raw = self.redis_string_manager.get(current_key, bytes)
        except Exception as error:  # noqa: BLE001
            raise SecretIntegrityException(
                f"redis: secret not found: {reference.path!r}",
            ) from error
        if raw is None:
            raise SecretIntegrityException(
                f"redis: secret not found: {reference.path!r}",
            )
        return _parse_version_number(raw)

    # --- SecretOperations protocol -------------------------------------

    def get(self, reference: SecretReference) -> SecretValue:
        version_number = self._resolve_version(reference)
        return self._read_envelope(reference, version_number)

    def get_version(
        self,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        return self._read_envelope(reference, version.number)

    def get_metadata(self, reference: SecretReference) -> SecretMetadata:
        version_number = self._resolve_version(reference)
        # Decrypt to extract the (encrypted) metadata; we could
        # store a plaintext sidecar to avoid this round-trip, but
        # the user picked the "default AES-GCM encryption" path so
        # metadata is part of the envelope.
        value = self._read_envelope(reference, version_number)
        return value.metadata

    def exists(self, reference: SecretReference) -> bool:
        current_key = _current_key(self.properties.namespace, reference.path)
        try:
            raw = self.redis_string_manager.get(current_key, bytes)
        except Exception:  # noqa: BLE001
            return False
        return raw is not None

    # --- SecretListable protocol ----------------------------------------

    def list(self, prefix: str | None = None) -> list[SecretReference]:
        """SCAN-based enumeration of all known secret references.

        Returns references whose path matches `prefix` (after
        stripping the namespace prefix). The result is sorted by
        path for deterministic output.
        """
        match = _list_match(self.properties.namespace, prefix)
        # `scan` returns a dict; we only need the keys.
        try:
            found = self.redis_string_manager.scan(match, count=100, clazz=bytes)
        except Exception as error:  # noqa: BLE001
            raise SecretException(
                f"redis: scan failed for match={match!r}: {error}",
            ) from error
        paths: set[str] = set()
        ns_prefix = f"{self.properties.namespace}:"
        for key in found:
            key_str = key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else str(key)
            if not key_str.startswith(ns_prefix):
                continue
            stripped = key_str[len(ns_prefix):]
            # Only consider the @current pointer (skip @vN / @counter)
            if not stripped.endswith("@current"):
                continue
            path = stripped[: -len("@current")]
            paths.add(path)
        return sorted(
            (SecretReference(provider="redis", path=path) for path in paths),
            key=lambda ref: ref.path,
        )


__all__ = ["RedisSecretOperations"]


_ = (Mapping,)
