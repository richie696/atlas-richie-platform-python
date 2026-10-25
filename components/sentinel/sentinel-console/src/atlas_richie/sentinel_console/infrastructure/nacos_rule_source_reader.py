"""Read one authoritative Nacos 3.x config and its provider MD5 revision."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
from http import HTTPStatus
import re

import aiohttp

from ..application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from ..domain.configuration_source import ConfigurationSourceProvider
from ..domain.rule_publication_targets import NacosRulePublicationTarget
from .nacos_source_support import (
    NACOS_ACCESS_TOKEN_HEADER,
    NACOS_HTTP_DENIED_STATUSES,
    NACOS_HTTP_OK_STATUS,
    NacosAccessTokenRejected,
    NacosAccessTokenUnavailable,
    is_nacos_success_code,
    resolve_nacos_access_token,
)
from .registered_source_checker import (
    JsonRequest,
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
    SourceTargetRejected,
)

_MAX_NACOS_CONFIG_BYTES = 512 * 1024
_NACOS_CONFIG_RESPONSE_BYTES = _MAX_NACOS_CONFIG_BYTES + 65_536
_NACOS_CONFIG_PATH = "/v3/admin/cs/config"
_NACOS_RESOURCE_NOT_FOUND_CODE = 20_004
_MD5_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")


class NacosRuleSourceReadRejected(RuntimeError):
    """Nacos explicitly denied access to the selected config."""


class NacosRuleSourceReadUnavailable(RuntimeError):
    """A fresh exact config value and provider revision could not be verified."""


class NacosRuleSourceAbsent(RuntimeError):
    """Nacos returned its authoritative config-not-found response for this key."""


@dataclass(frozen=True, slots=True)
class NacosRuleSourceSnapshot:
    """One existing exact config; content bytes are excluded from repr."""

    namespace: str
    group: str
    data_id: str
    value: bytes = field(repr=False)
    md5: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.namespace, self.group, self.data_id)
        ):
            raise ValueError("Nacos snapshot identity is invalid")
        if (
            not isinstance(self.value, bytes)
            or len(self.value) > _MAX_NACOS_CONFIG_BYTES
        ):
            raise ValueError("Nacos snapshot content is invalid")
        if not isinstance(self.md5, str) or _MD5_PATTERN.fullmatch(self.md5) is None:
            raise ValueError("Nacos snapshot MD5 is invalid")

    @property
    def revision(self) -> str:
        """Return the provider-owned MD5 used by the Nacos CAS request."""
        return self.md5


class NacosRuleSourceReader:
    """Read a single exact config via the pinned Nacos 3 Admin HTTP API."""

    def __init__(
        self,
        target_policy: RegisteredSourceTargetPolicy,
        http_client: PinnedAioHttpJsonClient | None = None,
    ) -> None:
        self._target_policy = target_policy
        self._http_client = http_client or PinnedAioHttpJsonClient(
            max_response_bytes=_NACOS_CONFIG_RESPONSE_BYTES
        )

    async def read(
        self,
        connection: SourceConnectionInput,
        target: NacosRulePublicationTarget,
    ) -> NacosRuleSourceSnapshot:
        """Return only a fresh server response for the exact frozen target."""
        _validate_request_identity(connection, target)
        try:
            pinned_target = await self._target_policy.resolve(connection)
            access_token = await resolve_nacos_access_token(
                connection, pinned_target, self._http_client.request
            )
            headers = (
                {NACOS_ACCESS_TOKEN_HEADER: access_token} if access_token else {}
            )
            status, payload, _response_headers = await self._http_client.request(
                target=pinned_target,
                endpoint=connection.endpoint,
                method="GET",
                path=_NACOS_CONFIG_PATH,
                params={
                    "namespaceId": target.namespace,
                    "groupName": target.group,
                    "dataId": target.data_id,
                },
                headers=headers,
            )
        except NacosAccessTokenRejected:
            raise NacosRuleSourceReadRejected from None
        except (
            NacosAccessTokenUnavailable,
            SourceTargetRejected,
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
        ):
            raise NacosRuleSourceReadUnavailable from None

        if status in NACOS_HTTP_DENIED_STATUSES:
            raise NacosRuleSourceReadRejected
        if status == HTTPStatus.NOT_FOUND:
            if (
                type(payload.get("code")) is int
                and payload.get("code") == _NACOS_RESOURCE_NOT_FOUND_CODE
            ):
                raise NacosRuleSourceAbsent
            raise NacosRuleSourceReadUnavailable
        if status != NACOS_HTTP_OK_STATUS or not is_nacos_success_code(
            payload.get("code")
        ):
            raise NacosRuleSourceReadUnavailable
        return _decode_snapshot(payload, target)


def _validate_request_identity(
    connection: SourceConnectionInput,
    target: NacosRulePublicationTarget,
) -> None:
    if connection.provider is not ConfigurationSourceProvider.NACOS:
        raise ValueError("Nacos rule reads require a Nacos connection")
    if connection.source_id != target.source_id:
        raise ValueError("Nacos rule target belongs to a different source")
    if connection.authentication_mode not in {
        SourceCheckAuthenticationMode.NONE,
        SourceCheckAuthenticationMode.DIRECT,
    }:
        raise ValueError("Nacos rule reads require resolved credentials")


def _decode_snapshot(
    payload: dict[str, object], target: NacosRulePublicationTarget
) -> NacosRuleSourceSnapshot:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise NacosRuleSourceReadUnavailable
    content = data.get("content")
    md5 = data.get("md5")
    if (
        data.get("namespaceId") != target.namespace
        or data.get("groupName") != target.group
        or data.get("dataId") != target.data_id
        or not isinstance(content, str)
        or not isinstance(md5, str)
        or _MD5_PATTERN.fullmatch(md5) is None
    ):
        raise NacosRuleSourceReadUnavailable
    try:
        value = content.encode("utf-8")
    except UnicodeEncodeError:
        raise NacosRuleSourceReadUnavailable from None
    if len(value) > _MAX_NACOS_CONFIG_BYTES:
        raise NacosRuleSourceReadUnavailable
    actual_md5 = hashlib.md5(value, usedforsecurity=False).hexdigest()
    if actual_md5.casefold() != md5.casefold():
        raise NacosRuleSourceReadUnavailable
    try:
        return NacosRuleSourceSnapshot(
            namespace=target.namespace,
            group=target.group,
            data_id=target.data_id,
            value=value,
            md5=md5.lower(),
        )
    except ValueError:
        raise NacosRuleSourceReadUnavailable from None


__all__ = [
    "NacosRuleSourceAbsent",
    "NacosRuleSourceReadRejected",
    "NacosRuleSourceReadUnavailable",
    "NacosRuleSourceReader",
    "NacosRuleSourceSnapshot",
]
