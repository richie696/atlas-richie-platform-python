"""Barbican secret client — 3-SPI composite behaviour tests.

中文
----
通过 `httpx.MockTransport`(in-process,无网络)验证
`BarbicanSecretClient` 全部 3 个 SPI 角色的行为:

- `read` / `metadata`(SecretOperations)
- `bootstrap`(SecretBootstrapClient)
- `close` / `descriptor`(SecretProviderSession)

错误路径:
- 401 / 403 / 404 → 对应 `SEC-AUTH-001` / `SEC-AUTHZ-001` /
  `SEC-STORE-001`
- HTTP transport error → `SEC-PROVIDER-001`
- missing token / token file → `SEC-BOOT-003`

`httpx.MockTransport` 不是 MagicMock;每个 request 走
`httpx` 内部 transport → 真实 transport → mock handler,
所以整个 HTTP 状态机都被验证(headers / status / body /
encoding)。

English
--------
Tests `BarbicanSecretClient` end-to-end via
`httpx.MockTransport` (in-process; the data path is real
`httpx` internals, not MagicMock). Covers all 3 SPI roles
+ error paths.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from atlas_richie.secret.bootstrap.catalog import (
    RequiredWhen,
    SecretBinding,
    SecretBindingCatalog,
    SecretKind,
)
from atlas_richie.secret.bootstrap.spi import (
    DefaultBootstrapContext,
    SecretBootstrapRequest,
)
from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret.reference import SecretReference
from atlas_richie.secret_barbican.client import BarbicanSecretClient
from atlas_richie.secret_barbican.configuration import BarbicanConfigurationResolver
from atlas_richie.secret_barbican.properties import (
    AuthType,
    BarbicanSecretMapping,
    BarbicanSecretProperties,
)


# ---------------------------------------------------------------------------
# Mock transport helpers
# ---------------------------------------------------------------------------


def _meta_response(secret_id: str, status: str = "ACTIVE", name: str | None = None) -> dict[str, Any]:
    return {
        "id": secret_id,
        "name": name,
        "status": status,
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-09-12T10:00:00Z",
        "expiration": None,
        "content_types": ["text/plain"],
    }


def _make_transport(
    routes: dict[str, Callable[[httpx.Request], httpx.Response]],
) -> httpx.MockTransport:
    """Build a `httpx.MockTransport` from a route map.

    Routes are keyed on ``"<METHOD> <EXACT_PATH>"`` (e.g.
    ``"GET /v1/secrets/sec-123/payload"``). Each route
    handler returns the canned response.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        for key, response_fn in routes.items():
            method, path = key.split(" ", 1)
            if request.method == method and str(request.url).endswith(path):
                return response_fn(request)
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def _make_client(
    routes: dict[str, Callable[[httpx.Request], httpx.Response]],
    properties: BarbicanSecretProperties,
) -> BarbicanSecretClient:
    """Build a real `BarbicanSecretClient` over a `httpx.MockTransport`."""
    transport = _make_transport(routes)
    http = httpx.Client(transport=transport)
    resolved = BarbicanConfigurationResolver().resolve(properties)
    return BarbicanSecretClient(resolved=resolved, http_client=http)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_properties() -> BarbicanSecretProperties:
    return BarbicanSecretProperties(
        endpoint="https://barbican.example",
        project_id="project-1",
        auth_type=AuthType.TOKEN,
        auth_token="token-abc",
        secrets={
            "db-password": BarbicanSecretMapping(id="sec-123"),
            "binary": BarbicanSecretMapping(id="sec-456"),
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBarbicanRead:
    def test_read_text_secret(self, default_properties) -> None:
        def meta_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_meta_response("sec-123"))

        def payload_handler(request: httpx.Request) -> httpx.Response:
            assert "X-Auth-Token" in request.headers
            assert request.headers["X-Auth-Token"] == "token-abc"
            assert request.headers["X-Project-Id"] == "project-1"
            return httpx.Response(200, content=b"hunter2")

        client = _make_client(
            {
                "GET /v1/secrets/sec-123": meta_handler,
                "GET /v1/secrets/sec-123/payload": payload_handler,
            },
            default_properties,
        )
        try:
            value = client.read(SecretReference(provider="barbican", path="db-password"))
            assert value.plaintext == b"hunter2"
        finally:
            client.close()

    def test_read_binary_secret(self, default_properties) -> None:
        def meta_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_meta_response("sec-456"))

        def payload_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"\x00\x01\x02\x03")

        client = _make_client(
            {
                "GET /v1/secrets/sec-456": meta_handler,
                "GET /v1/secrets/sec-456/payload": payload_handler,
            },
            default_properties,
        )
        try:
            value = client.read(SecretReference(provider="barbican", path="binary"))
            assert value.plaintext == b"\x00\x01\x02\x03"
        finally:
            client.close()

    def test_read_unmapped_uses_path_as_id(self, default_properties) -> None:
        def meta_handler(request: httpx.Request) -> httpx.Response:
            assert "unmapped-secret" in str(request.url)
            return httpx.Response(200, json=_meta_response("unmapped-secret"))

        def payload_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"direct")

        client = _make_client(
            {
                "GET /v1/secrets/unmapped-secret": meta_handler,
                "GET /v1/secrets/unmapped-secret/payload": payload_handler,
            },
            default_properties,
        )
        try:
            value = client.read(SecretReference(provider="barbican", path="unmapped-secret"))
            assert value.plaintext == b"direct"
        finally:
            client.close()

    def test_read_missing_secret_raises_integrity(self, default_properties) -> None:
        client = _make_client({}, default_properties)
        try:
            with pytest.raises(SecretIntegrityException) as info:
                client.read(SecretReference(provider="barbican", path="nonexistent"))
            assert "missing" in str(info.value).lower()
        finally:
            client.close()

    def test_metadata_returns_version_and_status(self, default_properties) -> None:
        def meta_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_meta_response("sec-123", status="ACTIVE", name="orders-db"),
            )

        client = _make_client(
            {"GET /v1/secrets/sec-123": meta_handler},
            default_properties,
        )
        try:
            metadata = client.metadata(SecretReference(provider="barbican", path="db-password"))
            assert metadata.tags["status"] == "ACTIVE"
            assert metadata.tags["name"] == "orders-db"
            assert metadata.created_at is not None
        finally:
            client.close()


class TestBarbicanErrorMapping:
    def test_401_maps_to_sec_auth_001(self, default_properties) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        client = _make_client({"GET /v1/secrets/sec-123": handler}, default_properties)
        try:
            with pytest.raises(SecretException) as info:
                client.read(SecretReference(provider="barbican", path="db-password"))
            assert "SEC-AUTH-001" in str(info.value)
        finally:
            client.close()

    def test_403_maps_to_sec_authz_001(self, default_properties) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "forbidden"})

        client = _make_client({"GET /v1/secrets/sec-123": handler}, default_properties)
        try:
            with pytest.raises(SecretException) as info:
                client.read(SecretReference(provider="barbican", path="db-password"))
            assert "SEC-AUTHZ-001" in str(info.value)
        finally:
            client.close()

    def test_500_maps_to_sec_provider_001(self, default_properties) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        client = _make_client({"GET /v1/secrets/sec-123": handler}, default_properties)
        try:
            with pytest.raises(SecretException) as info:
                client.read(SecretReference(provider="barbican", path="db-password"))
            assert "SEC-PROVIDER-001" in str(info.value)
        finally:
            client.close()

    def test_token_file_missing_raises_at_construction(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="https://barbican.example",
            auth_type=AuthType.TOKEN_FILE,
            auth_token_file="/this/path/does/not/exist/kmip-token-xyz",
        )
        # Resolver only validates the path is non-blank;
        # the actual file read happens at client construction.
        resolved = BarbicanConfigurationResolver().resolve(properties)
        with pytest.raises(SecretConfigurationException) as info:
            BarbicanSecretClient(resolved=resolved, http_client=httpx.Client())
        assert "SEC-BOOT-003" in str(info.value)


class TestBarbicanBootstrap:
    def test_bootstrap_resolves_all_startup_bindings(self, default_properties) -> None:
        def meta_handler_1(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_meta_response("sec-123"))

        def meta_handler_2(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_meta_response("sec-456"))

        def payload_handler_factory(content: bytes) -> Callable[[httpx.Request], httpx.Response]:
            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, content=content)
            return handler

        routes = {
            "GET /v1/secrets/sec-123": meta_handler_1,
            "GET /v1/secrets/sec-123/payload": payload_handler_factory(b"v1"),
            "GET /v1/secrets/sec-456": meta_handler_2,
            "GET /v1/secrets/sec-456/payload": payload_handler_factory(b"v2"),
        }
        client = _make_client(routes, default_properties)
        try:
            request = SecretBootstrapRequest(
                catalog=SecretBindingCatalog(
                    name="default",
                    bindings=(
                        SecretBinding(
                            name="db-password",
                            reference=SecretReference(provider="barbican", path="db-password"),
                            kind=SecretKind.GENERIC,
                        ),
                        SecretBinding(
                            name="binary",
                            reference=SecretReference(provider="barbican", path="binary"),
                            kind=SecretKind.GENERIC,
                        ),
                    ),
                ),
            )
            result = client.bootstrap(request, DefaultBootstrapContext())
            assert "db-password" in result.resolved
            assert "binary" in result.resolved
        finally:
            client.close()

    def test_bootstrap_startup_missing_raises(self, default_properties) -> None:
        client = _make_client({}, default_properties)
        try:
            request = SecretBootstrapRequest(
                catalog=SecretBindingCatalog(
                    name="default",
                    bindings=(
                        SecretBinding(
                            name="db-password",
                            reference=SecretReference(provider="barbican", path="db-password"),
                            kind=SecretKind.GENERIC,
                        ),
                    ),
                ),
            )
            with pytest.raises(SecretException) as info:
                client.bootstrap(request, DefaultBootstrapContext())
            assert "SEC-STORE-001" in str(info.value)
        finally:
            client.close()

    def test_bootstrap_optional_missing_silently(self, default_properties) -> None:
        client = _make_client({}, default_properties)
        try:
            request = SecretBootstrapRequest(
                catalog=SecretBindingCatalog(
                    name="default",
                    bindings=(
                        SecretBinding(
                            name="db-password",
                            reference=SecretReference(provider="barbican", path="db-password"),
                            kind=SecretKind.GENERIC,
                            required_when=RequiredWhen.OPTIONAL,
                        ),
                    ),
                ),
            )
            result = client.bootstrap(request, DefaultBootstrapContext())
            assert result.missing == ("db-password",)
        finally:
            client.close()


class TestBarbicanSession:
    def test_descriptor_declares_barbican_backend(self, default_properties) -> None:
        client = _make_client({}, default_properties)
        try:
            descriptor = client.descriptor
            assert descriptor.backend is SecretBackend.BARBICAN
            assert descriptor.capability.can_read is True
            assert descriptor.capability.can_write is False
            assert descriptor.capability.signs_values is False
        finally:
            client.close()

    def test_writer_deletable_are_none(self, default_properties) -> None:
        client = _make_client({}, default_properties)
        try:
            assert client.writer is None
            assert client.deletable is None
        finally:
            client.close()

    def test_close_is_idempotent(self, default_properties) -> None:
        client = _make_client({}, default_properties)
        client.close()
        client.close()  # idempotent
        assert client.is_closed is True

    def test_read_after_close_raises(self, default_properties) -> None:
        client = _make_client({}, default_properties)
        client.close()
        with pytest.raises(SecretException):
            client.read(SecretReference(provider="barbican", path="db-password"))


__all__ = []
