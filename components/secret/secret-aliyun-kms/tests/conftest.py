"""Test fixtures for `atlas-richie-secret-aliyun-kms`.

中文
----
提供:

- `FakeAliyunGateway` — 实现 `AliyunKmsGateway` Protocol 的内存
  mock,用于单元测试。不依赖 `MagicMock` —— 数据流真实流过
  `AliyunSecretClient`,只是 gateway 那一层换成 dict-backed fake。
- `fake_aliyun_gateway` — pytest fixture,每个测试一个新的
  `FakeAliyunGateway` 实例。
- `make_resolved` — 构造 `ResolvedAliyunConfiguration` 的 helper。

`FakeAliyunGateway` 的语义:

- `get_secret_value(secret_name, version_id, version_stage)` —
  从内部 `dict[str, AliyunGetSecretValueResponse]` 读,未命中返
  `None`。测试通过 `gateway.put(name, response)` 预置。
- `encrypt(...)` — `ciphertext_blob` 回显为 `cipher:<plaintext_b64>`,
  方便 wrap/unwrap 往返测试。
- `decrypt(ciphertext_blob, ...)` — 解 `cipher:` 前缀,反解回
  `plaintext_b64`;未带前缀时按原样回显(允许 round-trip 任意来源
  的 ciphertext)。
- `close()` — no-op。

English
--------
Pytest fixtures. `FakeAliyunGateway` is a real in-process
implementation of the `AliyunKmsGateway` Protocol — it is NOT a
MagicMock, so the data flow inside `AliyunSecretClient` is exercised
end-to-end. Unit tests use `gateway.put(name, response)` to seed
responses and assert against the client's return values.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import pytest

from atlas_richie.secret_aliyun_kms.client import (
    AliyunEncryptResponse,
    AliyunGetSecretValueResponse,
    AliyunKmsGateway,
)
from atlas_richie.secret_aliyun_kms.configuration import (
    AliyunConfigurationResolver,
    ResolvedAliyunConfiguration,
)
from atlas_richie.secret_aliyun_kms.properties import AliyunSecretProperties


class FakeAliyunGateway:
    """In-process stand-in for the real Alibaba SDK adapter.

    Stores `AliyunGetSecretValueResponse`s by physical secret name
    and round-trips `encrypt` / `decrypt` symmetrically so tests can
    exercise wrap/unwrap without a real KMS.
    """

    __slots__ = (
        "_closed",
        "_decrypt_table",
        "_secrets",
        "encrypt_calls",
        "decrypt_calls",
        "get_secret_value_calls",
    )

    def __init__(self) -> None:
        self._secrets: dict[str, AliyunGetSecretValueResponse] = {}
        self._closed = False
        # Map ciphertext_blob (base64) → (plaintext_b64, key_id).
        # Populated by `encrypt(...)`; consulted by `decrypt(...)`.
        # The pair is opaque to the client; the client just round-trips
        # through it.
        self._decrypt_table: dict[str, tuple[str, str]] = {}
        # Diagnostic counters — tests can assert how many times each
        # method was invoked.
        self.encrypt_calls: list[dict[str, Any]] = []
        self.decrypt_calls: list[dict[str, Any]] = []
        self.get_secret_value_calls: list[dict[str, Any]] = []

    # --- Seeding --------------------------------------------------------

    def put(
        self,
        secret_name: str,
        *,
        secret_data: str,
        secret_data_type: str = "Text",
        version_id: str = "v1",
        version_stages: tuple[str, ...] = ("ACSCurrent",),
        create_time: datetime | None = None,
        request_id: str = "req-1",
    ) -> AliyunGetSecretValueResponse:
        """Seed a canned response and return it for test convenience."""
        response = AliyunGetSecretValueResponse(
            secret_name=secret_name,
            secret_data=secret_data,
            secret_data_type=secret_data_type,
            version_id=version_id,
            version_stages=version_stages,
            create_time=create_time or datetime(2026, 1, 1, tzinfo=timezone.utc),
            request_id=request_id,
        )
        self._secrets[secret_name] = response
        return response

    # --- AliyunKmsGateway Protocol --------------------------------------

    def get_secret_value(
        self,
        secret_name: str,
        version_id: str | None,  # noqa: ARG002 - recorded for diagnostics
        version_stage: str | None,  # noqa: ARG002 - recorded for diagnostics
    ) -> AliyunGetSecretValueResponse | None:
        self.get_secret_value_calls.append(
            {
                "secret_name": secret_name,
                "version_id": version_id,
                "version_stage": version_stage,
            }
        )
        return self._secrets.get(secret_name)

    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
        encryption_context: dict[str, str],
    ) -> AliyunEncryptResponse:
        self.encrypt_calls.append(
            {
                "key_id": key_id,
                "plaintext_b64": plaintext_b64,
                "encryption_context": dict(encryption_context),
            }
        )
        # Produce a base64-encoded ciphertext that records the
        # plaintext + key_id so `decrypt(...)` can reverse it. The
        # wire shape is `base64(<decrypt-tag>::<plaintext_b64>)`.
        tagged = f"decrypt-tag::{plaintext_b64}".encode("utf-8")
        ciphertext_blob = base64.b64encode(tagged).decode("ascii")
        self._decrypt_table[ciphertext_blob] = (plaintext_b64, key_id)
        return AliyunEncryptResponse(
            ciphertext_blob=ciphertext_blob,
            key_id=key_id,
            request_id="req-encrypt",
        )

    def decrypt(
        self,
        ciphertext_blob: str,
        encryption_context: dict[str, str],
    ) -> Any:
        from atlas_richie.secret_aliyun_kms.client import AliyunDecryptResponse

        self.decrypt_calls.append(
            {
                "ciphertext_blob": ciphertext_blob,
                "encryption_context": dict(encryption_context),
            }
        )
        plaintext_b64, key_id = self._decrypt_table.get(
            ciphertext_blob, ("", "")
        )
        return AliyunDecryptResponse(
            plaintext=plaintext_b64,
            key_id=key_id,
            request_id="req-decrypt",
        )

    def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


@pytest.fixture
def fake_aliyun_gateway() -> Iterator[FakeAliyunGateway]:
    """Yield a fresh `FakeAliyunGateway` per test."""
    yield FakeAliyunGateway()


# --- Resolved configuration helpers -----------------------------------------


def make_properties(**overrides: Any) -> AliyunSecretProperties:
    """Build a valid `AliyunSecretProperties` with sensible defaults.

    Defaults: region = `cn-hangzhou`, no endpoint override, no
    bindings, no secret mappings, standard timeouts. Tests can
    override any field by passing it as a keyword argument.
    """
    fields: dict[str, Any] = {"region": "cn-hangzhou"}
    fields.update(overrides)
    return AliyunSecretProperties(**fields)


def make_resolved(**overrides: Any) -> ResolvedAliyunConfiguration:
    """Build a resolved configuration for tests.

    Returns a `ResolvedAliyunConfiguration` with provider_id
    `aliyun-test`. Tests that need to vary the provider_id can pass
    it explicitly; tests that want to drive the resolver directly
    should construct `AliyunConfigurationResolver()` and call
    `resolve(...)` themselves.
    """
    properties = make_properties(**overrides)
    return AliyunConfigurationResolver().resolve(
        properties,
        provider_id=overrides.pop("provider_id", "aliyun-test"),
    )


def decode_base64(b64: str) -> bytes:
    return base64.b64decode(b64.encode("ascii"))


__all__ = [
    "FakeAliyunGateway",
    "fake_aliyun_gateway",
    "make_properties",
    "make_resolved",
    "decode_base64",
]
