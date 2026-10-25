"""Shared, bounded HTTP authentication helpers for Nacos 3.x adapters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import TYPE_CHECKING, TypeAlias

from ..application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
if TYPE_CHECKING:
    from .registered_source_checker import PinnedSourceTarget

JsonRequest: TypeAlias = Callable[
    ..., Awaitable[tuple[int, dict[str, object], dict[str, str]]]
]

NACOS_LOGIN_PATH = "/v3/auth/user/login"
NACOS_ACCESS_TOKEN_HEADER = "accessToken"
NACOS_HTTP_DENIED_STATUSES = frozenset(
    {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}
)
NACOS_HTTP_OK_STATUS = HTTPStatus.OK
_MAX_NACOS_ACCESS_TOKEN_LENGTH = 8_192


class NacosAccessTokenRejected(RuntimeError):
    """Nacos rejected credentials or returned an unsafe token value."""


class NacosAccessTokenUnavailable(RuntimeError):
    """Nacos authentication did not produce a trustworthy result."""


async def resolve_nacos_access_token(
    connection: SourceConnectionInput,
    target: PinnedSourceTarget,
    request: JsonRequest,
) -> str | None:
    """Resolve direct Nacos credentials into an ephemeral HTTP header token.

    Credential references and retained credentials are resolved by the
    application use case before the infrastructure adapter is called. This
    helper therefore accepts only unauthenticated or direct connection facts.
    """
    if connection.authentication_mode is SourceCheckAuthenticationMode.NONE:
        return None
    if connection.authentication_mode is not SourceCheckAuthenticationMode.DIRECT:
        raise NacosAccessTokenUnavailable
    if connection.username is None or connection.password is None:
        raise NacosAccessTokenUnavailable

    status, payload, _headers = await request(
        target=target,
        endpoint=connection.endpoint,
        method="POST",
        path=NACOS_LOGIN_PATH,
        params={},
        headers={},
        form={"username": connection.username, "password": connection.password},
    )
    if status in NACOS_HTTP_DENIED_STATUSES:
        raise NacosAccessTokenRejected
    if status != NACOS_HTTP_OK_STATUS:
        raise NacosAccessTokenUnavailable

    token = payload.get("accessToken")
    if (
        not isinstance(token, str)
        or not token
        or len(token) > _MAX_NACOS_ACCESS_TOKEN_LENGTH
        or not is_safe_header_value(token)
    ):
        raise NacosAccessTokenRejected
    return token


def is_nacos_success_code(value: object) -> bool:
    """Accept documented JSON success representations without bool/int aliasing."""
    return (type(value) is int and value == 0) or (
        isinstance(value, str) and value == "0"
    )


def is_safe_header_value(value: str) -> bool:
    """Allow only visible ASCII in opaque provider values sent as HTTP headers."""
    return value.isascii() and value.isprintable()


__all__ = [
    "NACOS_ACCESS_TOKEN_HEADER",
    "NACOS_HTTP_DENIED_STATUSES",
    "NACOS_HTTP_OK_STATUS",
    "NACOS_LOGIN_PATH",
    "NacosAccessTokenRejected",
    "NacosAccessTokenUnavailable",
    "is_nacos_success_code",
    "is_safe_header_value",
    "resolve_nacos_access_token",
]
