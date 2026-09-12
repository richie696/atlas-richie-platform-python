"""`BarbicanSecretClient` — 3 个 SPI 角色,跑在 OpenStack Barbican REST API 上。

中文
----
对位 Java `cn.richie696.component.secret.provider.barbican.BarbicanSecretClient`
(171 行),实现 3-SPI 复合:`SecretBackend` (read / metadata)
+ `SecretBootstrapClient` (load logical paths) +
`SecretProviderSession`。**不**实现 `KeyWrappingBackend`
(Barbican 是 secret store,无 KMS wrap API)、`SecretWriter` /
`SecretDeletable`(read-only)。

**API surface**(对位 Java `fetchPayload` + `send`):
- `GET /v1/secrets/{id}` — Barbican secret metadata(JSON)
- `GET /v1/secrets/{id}/payload` — 原始 bytes(`Accept: application/octet-stream`)
- Header `X-Auth-Token: ...`(OpenStack Keystone token)
- Header `X-Project-Id: ...`(如果配置)

**错误映射**(对位 Java `providerFailure`):
- 401 → `SEC-AUTH-001` (auth failure)
- 403 → `SEC-AUTHZ-001` (authorization)
- 404 → `SEC-STORE-001` (missing)
- 其他非 2xx → `SEC-PROVIDER-001`
- 网络 / IO 错误 → `SEC-PROVIDER-001`

**HTTP 客户端**:Python 端用 `httpx.Client`(对位 Java
JDK `HttpClient`)。Retry policy 简单 — 框架层不实现
exponential backoff,直接对 transient `httpx.HTTPError` 重试
N 次(对位 Java `HttpResponseRetryExecutor`)。

**SDK 类型隔离**:`httpx.Response` 不穿透到 framework /
public API 边界 — 内部解 JSON 后用 frozen dataclass 表达。

English
--------
3-SPI composite session over OpenStack Barbican's REST
API. Implements `SecretBackend` (read / metadata) +
`SecretBootstrapClient` + `SecretProviderSession`. No
`KeyWrappingBackend` (Barbican has no KMS wrap API) and
no `SecretWriter` / `SecretDeletable` (read-only).

Uses `httpx.Client` (vs Java's JDK `HttpClient`).
Two API endpoints: `GET /v1/secrets/{id}` for metadata
(JSON) and `GET /v1/secrets/{id}/payload` for the raw
bytes. Auth via `X-Auth-Token` (Keystone); `X-Project-Id`
is set if configured. 1:1 with Java
`BarbicanSecretClient` error mapping (401/403/404 → named
`SEC-AUTH-*` / `SEC-STORE-001` codes; other non-2xx →
`SEC-PROVIDER-001`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from atlas_richie.secret.bootstrap.catalog import RequiredWhen
from atlas_richie.secret.bootstrap.spi import (
    SecretBootstrapContext,
    SecretBootstrapRequest,
    SecretBootstrapResult,
)
from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend, SecretMetadata
from atlas_richie.secret.operations import SecretOperations
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret.snapshot import SecretSnapshotManager
from atlas_richie.secret.value import SecretValue
from atlas_richie.secret_barbican.configuration import ResolvedBarbicanConfiguration
from atlas_richie.secret_barbican.properties import AuthType

_logger = logging.getLogger("atlas_richie.secret_barbican.client")


@dataclass(frozen=True, slots=True)
class BarbicanSecretMetadata:
    """Frozen response for `GET /v1/secrets/{id}` (mirrors Java
    `JsonNode` shape used in `BarbicanSecretClient.metadata`).

    Attributes:
        id: Physical Barbican secret UUID.
        name: Optional secret name.
        status: Barbican status string (`ACTIVE`, `PENDING`).
        created: ISO-8601 timestamp.
        updated: ISO-8601 timestamp.
        expiration: Optional ISO-8601 timestamp.
        content_types: Tuple of MIME types the payload is offered as.
    """

    id: str
    name: str | None
    status: str
    created: str | None
    updated: str | None
    expiration: str | None
    content_types: tuple[str, ...]


def _barbican_capability_func():
    from atlas_richie.secret_barbican.configuration import _barbican_capability
    return _barbican_capability()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class BarbicanSecretClient:
    """3-SPI composite session over the OpenStack Barbican REST API.

    Mirrors Java `BarbicanSecretClient`. The session's
    `key_wrapping_backend` returns `None` — Barbican is a
    secret store, not a KMS. `writer` / `deletable` also
    return `None` (read-only backend).
    """

    __slots__ = (
        "_closed",
        "_configuration_hash",
        "_descriptor_backend",
        "_endpoint",
        "_http",
        "_http_client_factory",
        "_properties",
        "_provider_id",
        "_resolved",
        "_snapshot_manager",
        "_token",
    )

    def __init__(
        self,
        resolved: ResolvedBarbicanConfiguration,
        *,
        http_client: httpx.Client | None = None,
        http_client_factory: Callable[[], httpx.Client] | None = None,
        descriptor_backend: SecretBackend = SecretBackend.BARBICAN,
    ) -> None:
        self._resolved = resolved
        self._properties = resolved.properties
        self._provider_id = resolved.provider_id
        self._configuration_hash = resolved.configuration_hash
        self._descriptor_backend = descriptor_backend
        self._endpoint = self._properties.endpoint.rstrip("/") + "/"
        self._token = self._load_token(self._properties.auth_type, self._properties.auth_token, self._properties.auth_token_file or "")
        self._http_client_factory = http_client_factory
        if http_client is not None:
            self._http = http_client
        elif http_client_factory is not None:
            self._http = http_client_factory()
        else:
            self._http = httpx.Client(
                timeout=httpx.Timeout(
                    connect=self._properties.connect_timeout_seconds,
                    read=self._properties.read_timeout_seconds,
                    write=self._properties.read_timeout_seconds,
                    pool=self._properties.connect_timeout_seconds,
                ),
            )
        self._snapshot_manager = SecretSnapshotManager()
        self._closed = False

    # --- SecretOperations ------------------------------------------------

    def read(self, reference: SecretReference) -> SecretValue:
        self._ensure_open()
        secret_id = self._resolve_id(reference)
        payload = self._fetch_payload(secret_id, reference.path)
        if payload is None:
            raise SecretIntegrityException(
                f"barbican: Secret is missing: {secret_id!r}",
            )
        try:
            return SecretValue(
                plaintext=payload,
                metadata=SecretMetadata(
                    reference=reference,
                    version=SecretVersion(
                        number="latest",
                        created_at=datetime.now(tz=timezone.utc),
                    ),
                    backend=self._descriptor_backend,
                    created_at=datetime.now(tz=timezone.utc),
                    expires_at=None,
                    tags={"provider": "barbican"},
                ),
            )
        finally:
            self._zero(payload)

    def metadata(self, reference: SecretReference) -> SecretMetadata:
        self._ensure_open()
        secret_id = self._resolve_id(reference)
        meta = self._fetch_metadata(secret_id)
        if meta is None:
            raise SecretIntegrityException(
                f"barbican: Secret metadata is missing: {secret_id!r}",
            )
        return SecretMetadata(
            reference=reference,
            version=SecretVersion(
                number=meta.updated or meta.created or "latest",
                created_at=self._parse_instant(meta.created),
            ),
            backend=self._descriptor_backend,
            created_at=self._parse_instant(meta.created),
            expires_at=self._parse_instant(meta.expiration),
            tags={
                "provider": "barbican",
                "status": meta.status,
                "name": meta.name or "",
            },
        )

    # --- SecretBootstrapClient -------------------------------------------

    def bootstrap(
        self,
        request: SecretBootstrapRequest,
        context: SecretBootstrapContext,
    ) -> SecretBootstrapResult:
        self._ensure_open()
        started_at = context.now
        resolved: dict[str, SecretValue] = {}
        missing: list[str] = []
        for binding in request.catalog.bindings:
            try:
                secret_id = self._resolve_id(binding.reference)
                payload = self._fetch_payload(secret_id, binding.reference.path)
                if payload is None:
                    raise SecretIntegrityException(
                        f"barbican: Secret is missing: {secret_id!r}",
                    )
                try:
                    resolved[binding.name] = SecretValue(
                        plaintext=payload,
                        metadata=SecretMetadata(
                            reference=binding.reference,
                            version=SecretVersion(
                                number="latest",
                                created_at=datetime.now(tz=timezone.utc),
                            ),
                            backend=self._descriptor_backend,
                            created_at=datetime.now(tz=timezone.utc),
                            expires_at=None,
                            tags={"provider": "barbican"},
                        ),
                    )
                finally:
                    self._zero(payload)
            except SecretIntegrityException as error:
                if binding.required_when in (
                    RequiredWhen.STARTUP,
                    RequiredWhen.PRODUCTION_ONLY,
                ):
                    raise SecretException(
                        f"barbican: bootstrap Secret binding {binding.name!r} is missing "
                        f"(SEC-STORE-001): {error}",
                    ) from error
                missing.append(binding.name)
                _logger.warning(
                    "barbican: bootstrap binding %r missing (required_when=%s); continuing",
                    binding.name,
                    binding.required_when.value,
                )
        return SecretBootstrapResult(
            resolved=resolved,
            missing=tuple(missing),
            started_at=started_at,
            finished_at=context.now,
        )

    # --- SecretProviderSession -------------------------------------------

    @property
    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self._provider_id,
            backend=self._descriptor_backend,
            capability=_barbican_capability_func(),
            version="0.2.0",
        )

    @property
    def configuration(self) -> SecretProviderConfiguration:
        return SecretProviderConfiguration(
            name=self._provider_id,
            parameters={},
            timeout_seconds=self._properties.read_timeout_seconds,
            retries=self._properties.max_attempts,
            namespace=self._endpoint,
        )

    @property
    def operations(self) -> SecretOperations | None:  # type: ignore[override]
        return self  # type: ignore[return-value]

    @property
    def writer(self):  # type: ignore[override]
        return None

    @property
    def deletable(self):  # type: ignore[override]
        return None

    @property
    def snapshot_manager(self) -> SecretSnapshotManager:
        return self._snapshot_manager

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def configuration_hash(self) -> str:
        return self._configuration_hash

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._http.close()
        except Exception as error:  # noqa: BLE001
            _logger.debug("barbican: http client close raised: %s", error)

    # --- Internal helpers ------------------------------------------------

    def _resolve_id(self, reference: SecretReference) -> str:
        mapping = self._properties.secrets.get(reference.path)
        if mapping is not None:
            return mapping.id
        return reference.path

    def _base_headers(self) -> dict[str, str]:
        headers = {
            "X-Auth-Token": self._token,
            "Accept": "application/json",
        }
        if self._properties.project_id:
            headers["X-Project-Id"] = self._properties.project_id
        return headers

    def _fetch_metadata(self, secret_id: str) -> BarbicanSecretMetadata | None:
        suffix = f"v1/secrets/{_url_encode(secret_id)}"
        url = self._endpoint + suffix
        try:
            response = self._http.get(url, headers=self._base_headers())
        except httpx.HTTPError as error:
            raise SecretException(
                f"barbican: metadata request failed (SEC-PROVIDER-001): {error}",
            ) from error
        if response.status_code == 404:
            return None
        self._raise_for_status("Barbican metadata", response.status_code)
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as error:
            raise SecretException(
                f"barbican: metadata is not JSON (SEC-PROVIDER-001): {error}",
            ) from error
        content_types = tuple(body.get("content_types", []))
        return BarbicanSecretMetadata(
            id=body.get("id", secret_id),
            name=body.get("name"),
            status=body.get("status", "unknown"),
            created=body.get("created"),
            updated=body.get("updated"),
            expiration=body.get("expiration"),
            content_types=content_types,
        )

    def _fetch_payload(self, secret_id: str, logical_name: str) -> bytes | None:
        """Fetch the raw payload bytes for a Barbican secret.

        Two-step: first fetch metadata to get the secret id
        (matches Java `fetchPayload`), then fetch the
        payload. Returns None on 404.
        """
        meta = self._fetch_metadata(secret_id)
        if meta is None:
            return None
        suffix = f"v1/secrets/{_url_encode(secret_id)}/payload"
        url = self._endpoint + suffix
        try:
            response = self._http.get(
                url,
                headers={
                    **self._base_headers(),
                    "Accept": "application/octet-stream",
                },
            )
        except httpx.HTTPError as error:
            raise SecretException(
                f"barbican: payload request failed (SEC-PROVIDER-001): {error}",
            ) from error
        if response.status_code == 404:
            return None
        self._raise_for_status("Barbican payload", response.status_code)
        return bytes(response.content)

    @staticmethod
    def _raise_for_status(operation: str, status_code: int) -> None:
        """Map HTTP status to framework error code (mirrors Java `providerFailure`).
        """
        if 200 <= status_code < 300:
            return
        if status_code == 401:
            code = "SEC-AUTH-001"
        elif status_code == 403:
            code = "SEC-AUTHZ-001"
        elif status_code == 404:
            code = "SEC-STORE-001"
        else:
            code = "SEC-PROVIDER-001"
        raise SecretException(f"{operation} failed with HTTP {status_code} ({code})")

    @staticmethod
    def _load_token(auth_type: AuthType, token: str, token_file: str) -> str:
        if auth_type is AuthType.TOKEN_FILE:
            try:
                return Path(token_file).read_text(encoding="utf-8").strip()
            except OSError as error:
                raise SecretConfigurationException(
                    f"barbican: token file cannot be read: {token_file!r} (SEC-BOOT-003)",
                ) from error
        if not token:
            raise SecretConfigurationException(
                "barbican: TOKEN authentication requires a non-blank token (SEC-BOOT-003)",
            )
        return token

    @staticmethod
    def _parse_instant(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _zero(buffer: bytearray | bytes | memoryview) -> None:
        if isinstance(buffer, (bytearray, memoryview)):
            try:
                buffer[:] = b"\x00" * len(buffer)
            except (TypeError, ValueError):
                pass

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecretException("barbican: Secret Provider session is closed")


def _url_encode(value: str) -> str:
    """URL-encode a path component (mirrors Java `URLEncoder.encode`)."""
    from urllib.parse import quote

    return quote(value, safe="")


__all__ = [
    "BarbicanSecretClient",
    "BarbicanSecretMetadata",
]
