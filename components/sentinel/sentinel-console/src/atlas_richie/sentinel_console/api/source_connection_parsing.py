"""Strict shared parsing for provider connection inputs across Console writes."""

from __future__ import annotations

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.source_endpoint import (
    MAX_SOURCE_ENDPOINT_UNITS,
    is_safe_source_endpoint,
)
from atlas_richie.sentinel_console.domain.wire_strings import (
    is_bounded_wire_identifier,
    is_bounded_wire_text,
)

_INVALID = object()


def parse_source_connection(
    body: dict[str, object] | None,
    *,
    source_id: object,
    expected_revision: object,
) -> SourceConnectionInput | None:
    """Parse one strict provider/authentication union and its revision identity."""
    parsed_source_id = _optional_identifier(source_id)
    parsed_revision = _optional_identifier(expected_revision)
    if body is None or parsed_source_id is _INVALID or parsed_revision is _INVALID:
        return None
    try:
        provider = ConfigurationSourceProvider(body.get("provider"))
    except (TypeError, ValueError):
        return None
    location_name = (
        "namespace"
        if provider is ConfigurationSourceProvider.NACOS
        else "datacenter"
    )
    if set(body) != {"provider", "endpoint", location_name, "authentication"}:
        return None
    endpoint = body.get("endpoint")
    location = body.get(location_name)
    authentication = body.get("authentication")
    if (
        not isinstance(endpoint, str)
        or not is_bounded_wire_text(endpoint, MAX_SOURCE_ENDPOINT_UNITS)
        or not is_safe_source_endpoint(endpoint)
        or not isinstance(location, str)
        or not is_bounded_wire_text(location, 200)
        or not isinstance(authentication, dict)
    ):
        return None
    parsed_authentication = _parse_authentication(provider, authentication)
    if parsed_authentication is None:
        return None
    mode, secret_fields = parsed_authentication
    try:
        return SourceConnectionInput(
            source_id=parsed_source_id,
            expected_revision=parsed_revision,
            provider=provider,
            endpoint=endpoint,
            location=location,
            authentication_mode=mode,
            **secret_fields,
        )
    except ValueError:
        return None


def _optional_identifier(value: object) -> str | None | object:
    if value is None:
        return None
    if is_bounded_wire_identifier(value, 200):
        return value
    return _INVALID


def _parse_authentication(
    provider: ConfigurationSourceProvider,
    body: dict[str, object],
) -> tuple[SourceCheckAuthenticationMode, dict[str, str]] | None:
    mode = body.get("mode")
    if mode == "keep" and set(body) == {"mode"}:
        return SourceCheckAuthenticationMode.KEEP, {}
    if mode == "none" and set(body) == {"mode"}:
        return SourceCheckAuthenticationMode.NONE, {}
    if mode == "credential-reference" and set(body) == {"mode", "reference"}:
        reference = body.get("reference")
        if is_bounded_wire_identifier(reference, 512):
            return (
                SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE,
                {"credential_reference": reference},
            )
        return None
    if mode != "direct":
        return None
    if provider is ConfigurationSourceProvider.NACOS:
        if set(body) != {"mode", "username", "password"}:
            return None
        username, password = body.get("username"), body.get("password")
        if (
            isinstance(username, str)
            and is_bounded_wire_identifier(username, 200)
            and isinstance(password, str)
            and password
            and is_bounded_wire_text(password, 1024)
        ):
            return SourceCheckAuthenticationMode.DIRECT, {
                "username": username,
                "password": password,
            }
        return None
    if set(body) != {"mode", "aclToken"}:
        return None
    token = body.get("aclToken")
    if isinstance(token, str) and token and is_bounded_wire_text(token, 1024):
        return SourceCheckAuthenticationMode.DIRECT, {"acl_token": token}
    return None
