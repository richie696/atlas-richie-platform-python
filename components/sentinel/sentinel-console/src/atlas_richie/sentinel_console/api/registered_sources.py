"""Administrator-only HTTP adapter for registered configuration-source reads."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_registered_sources import ReadRegisteredSources
from ..application.read_session import ReadSession
from ..application.registered_source_ports import RegisteredSourcesAuthorityUnavailable
from ..domain.configuration_source import ConfigurationSourceProvider
from ..domain.registered_sources import (
    RegisteredConfigurationSource,
    RegisteredSourcesSnapshot,
)
from ..domain.session import AccountRole
from .http_support import error_response
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
    utc_timestamp,
)


def registered_sources_route(
    read_session: ReadSession,
    read_sources: ReadRegisteredSources | None,
) -> Route:
    """Create the admin-protected, credential-free source-registry read route."""

    async def read_registry(request: Request) -> Response:
        request_id_value, identity, rejection = await authorize_system_read(
            request,
            read_session,
            invalid_request_code="invalid_request",
        )
        if rejection is not None:
            return rejection
        assert identity is not None
        if identity.role_id is not AccountRole.ADMIN:
            return error_response(request_id_value, "forbidden", 403)
        if read_sources is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            snapshot = await read_sources.execute()
        except RegisteredSourcesAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            _snapshot_body(snapshot), headers=system_read_headers(request_id_value)
        )

    return Route("/api/v1/system/sources", read_registry, methods=["GET"])


def _snapshot_body(snapshot: RegisteredSourcesSnapshot) -> dict[str, object]:
    return {
        "asOf": utc_timestamp(snapshot.as_of),
        "items": [_source_body(item) for item in snapshot.items],
    }


def _source_body(source: RegisteredConfigurationSource) -> dict[str, object]:
    body: dict[str, object] = {
        "id": source.id,
        "revision": source.revision,
        "name": source.name,
        "endpoint": source.endpoint,
        "authenticationMode": source.authentication_mode.value,
        "credentialConfigured": source.credential_configured,
        "provider": source.provider.value,
    }
    if source.provider is ConfigurationSourceProvider.NACOS:
        body["namespace"] = source.location
    else:
        body["datacenter"] = source.location
    return body
