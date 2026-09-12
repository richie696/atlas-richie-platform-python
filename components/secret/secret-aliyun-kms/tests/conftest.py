"""Test fixtures for `atlas-richie-secret-aliyun-kms`.

中文
----
提供 `FakeAliyunGateway`(in-process,不走 SDK),让 unit 测试可以
验证完整 client 行为而不依赖阿里云环境。

`FakeAliyunGateway` 行为:
- `get_secret_value`:从内部 `dict[str, AliyunGetSecretValueResponse]`
  取(`put(name, response)` 注入),没有则返回 `None`(模拟 missing)
- `encrypt`:把 `plaintext_b64` 前面加 `cipher:` 前缀后作为
  `ciphertext_blob` 返回,`key_id` 透传(测试 wrap/unwrap 往返)
- `decrypt`:移除 `cipher:` 前缀,base64 解码后返回 plaintext
- `close`:no-op

测试中不引入 MagicMock;fake gateway 是 in-process 真对象,数据
流经 framework 全部 4 个 SPI。

English
--------
Provides `FakeAliyunGateway` (in-process, no SDK) so unit
tests can exercise the full client without an Aliyun Cloud
account. The fake is a real in-process object (not
MagicMock) so the entire 4-SPI data flow is exercised.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from atlas_richie.secret_aliyun_kms.client import (
    AliyunDecryptResponse,
    AliyunEncryptResponse,
    AliyunGetSecretValueResponse,
    AliyunKmsGateway,
)
from atlas_richie.secret_aliyun_kms.configuration import (
    AliyunConfigurationResolver,
    ResolvedAliyunConfiguration,
)
from atlas_richie.secret_aliyun_kms.properties import (
    AliyunSecretMapping,
    AliyunSecretProperties,
)


class FakeAliyunGateway(AliyunKmsGateway):
    """In-process stand-in for `alibabacloud_kms20160120.Client`.

    Implements the 4-method `AliyunKmsGateway` Protocol
    (`get_secret_value` / `encrypt` / `decrypt` / `close`).
    Stores secrets in an internal dict and reverses the
    `cipher:` prefix on decrypt for round-trip tests.
    """

    __slots__ = ("_close_calls", "_secrets")

    def __init__(self) -> None:
        self._secrets: dict[str, AliyunGetSecretValueResponse] = {}
        self._close_calls = 0

    def put(
        self,
        name: str,
        response: AliyunGetSecretValueResponse,
    ) -> None:
        self._secrets[name] = response

    def get_secret_value(
        self,
        secret_name: str,
        version_id: str | None,
        version_stage: str | None,
    ) -> AliyunGetSecretValueResponse | None:
        response = self._secrets.get(secret_name)
        if response is None:
            return None
        if version_id is not None and response.version_id != version_id:
            return None
        if version_stage is not None and version_stage not in response.version_stages:
            return None
        return response

    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
        encryption_context,
    ) -> AliyunEncryptResponse:
        return AliyunEncryptResponse(
            key_id=key_id,
            ciphertext_blob=f"cipher:{plaintext_b64}",
            request_id="fake-encrypt-request",
        )

    def decrypt(
        self,
        ciphertext_blob: str,
        encryption_context,
    ) -> AliyunDecryptResponse:
        if not ciphertext_blob.startswith("cipher:"):
            raise ValueError(
                f"FakeAliyunGateway: cannot decrypt non-fake ciphertext: {ciphertext_blob[:32]!r}",
            )
        plaintext_b64 = ciphertext_blob[len("cipher:"):]
        return AliyunDecryptResponse(
            key_id="alias/orders",
            plaintext=plaintext_b64,
            request_id="fake-decrypt-request",
        )

    def close(self) -> None:
        self._close_calls += 1

    @property
    def close_calls(self) -> int:
        return self._close_calls


@pytest.fixture
def fake_aliyun_gateway() -> Iterator[FakeAliyunGateway]:
    gateway = FakeAliyunGateway()
    try:
        yield gateway
    finally:
        gateway.close()


@pytest.fixture
def default_properties() -> AliyunSecretProperties:
    """Standard test properties (region `cn-hangzhou` + key bindings)."""
    return AliyunSecretProperties(
        region="cn-hangzhou",
        kms_key_bindings={"default-envelope": "alias/orders"},
    )


@pytest.fixture
def resolved_configuration(default_properties) -> ResolvedAliyunConfiguration:
    return AliyunConfigurationResolver().resolve(
        default_properties,
        provider_id="aliyun-test",
    )


@pytest.fixture
def secret_mapping() -> AliyunSecretMapping:
    return AliyunSecretMapping(secret_name="prod/orders/database", field="password")


@pytest.fixture
def client_with_gateway(
    fake_aliyun_gateway: FakeAliyunGateway,
    resolved_configuration: ResolvedAliyunConfiguration,
) -> AliyunSecretClient:
    """Wire a real `AliyunSecretClient` to a real `FakeAliyunGateway`.

    Tests that use this fixture exercise the full 4-SPI data
    path: `read` / `metadata` / `wrap` / `unwrap` / `bootstrap` /
    `descriptor` / `close` all run against the fake gateway
    (in-process, no SDK calls, no network).
    """
    from atlas_richie.secret_aliyun_kms.client import AliyunSecretClient

    # Update properties to include a path prefix so the tests
    # can use `prod/db` style logical paths in references.
    properties = resolved_configuration.properties.model_copy(
        update={"secrets_manager_path_prefix": "company"},
    )
    resolved = AliyunConfigurationResolver().resolve(
        properties,
        provider_id=resolved_configuration.provider_id,
    )
    return AliyunSecretClient(resolved, fake_aliyun_gateway)


__all__ = [
    "FakeAliyunGateway",
]
