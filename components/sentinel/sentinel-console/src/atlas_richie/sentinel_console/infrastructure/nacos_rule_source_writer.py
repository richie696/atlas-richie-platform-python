"""Nacos 3.x gRPC compare-and-set with exact Admin API read-back."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import re
from time import time_ns
from uuid import uuid4

import aiohttp

from ..application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from ..domain.configuration_source import ConfigurationSourceProvider
from ..domain.rule_publication_targets import NacosRulePublicationTarget
from .nacos_grpc_transport import (
    NacosGrpcConflict,
    NacosGrpcOutcomeUnknown,
    NacosGrpcRejected,
    NacosGrpcRequestClient,
    NacosGrpcTransport,
    NacosGrpcUnavailable,
)
from .nacos_rule_source_reader import (
    NacosRuleSourceReadRejected,
    NacosRuleSourceReadUnavailable,
    NacosRuleSourceReader,
)
from .nacos_source_support import (
    NACOS_ACCESS_TOKEN_HEADER,
    NacosAccessTokenRejected,
    NacosAccessTokenUnavailable,
    resolve_nacos_access_token,
)
from .registered_source_checker import (
    PinnedAioHttpJsonClient,
    PinnedSourceTarget,
    RegisteredSourceTargetPolicy,
    SourceTargetRejected,
)

_MD5_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")
_MAX_NACOS_CONFIG_BYTES = 512 * 1024
_NACOS_GRPC_PORT_OFFSET = 1000
_NACOS_RESOURCE_CONFLICT_CODE = 20_005
_NACOS_CAS_CONFLICT_STATUS = 500
_NACOS_CAS_CONFLICT_MESSAGE = "Cas publish fail, server md5 may have changed."
_NACOS_REQUEST_TOKEN_HEADER = "requestToken"


class NacosRuleSourceConflict(RuntimeError):
    """The exact Nacos baseline changed before the provider accepted the write."""


class NacosRuleSourceWriteRejected(RuntimeError):
    """Nacos denied the request or the operation is unsupported by its CAS API."""


class NacosRuleSourceOutcomeUnknown(RuntimeError):
    """Nacos may have accepted the write but exact read-back was not confirmed."""


class NacosRuleSourceUnavailable(RuntimeError):
    """The provider target was not reachable under the configured network policy."""


@dataclass(frozen=True, slots=True)
class NacosRuleSourceWrite:
    """One exact Nacos config update; create-only CAS is not supported."""

    connection: SourceConnectionInput
    target: NacosRulePublicationTarget
    expected_md5: str
    value: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if self.connection.provider is not ConfigurationSourceProvider.NACOS:
            raise ValueError("Nacos rule writes require a Nacos connection")
        if self.connection.authentication_mode not in {
            SourceCheckAuthenticationMode.NONE,
            SourceCheckAuthenticationMode.DIRECT,
        }:
            raise ValueError("Nacos rule writes require resolved credentials")
        if self.connection.source_id != self.target.source_id:
            raise ValueError("Nacos rule target belongs to another source")
        if (
            not isinstance(self.expected_md5, str)
            or _MD5_PATTERN.fullmatch(self.expected_md5) is None
        ):
            raise ValueError("Nacos CAS requires an existing provider MD5 revision")
        if (
            not isinstance(self.value, bytes)
            or not self.value
            or len(self.value) > _MAX_NACOS_CONFIG_BYTES
        ):
            raise ValueError("Nacos rule content exceeds the supported size")
        try:
            self.value.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Nacos rule content must be UTF-8") from error


@dataclass(frozen=True, slots=True)
class NacosRuleSourceWriteReceipt:
    """Provider MD5 read back after the exact candidate bytes were confirmed."""

    md5: str

    def __post_init__(self) -> None:
        if not isinstance(self.md5, str) or _MD5_PATTERN.fullmatch(self.md5) is None:
            raise ValueError("Nacos write receipt requires a valid provider MD5")


class NacosRuleSourceWriter:
    """Perform one gRPC CAS, then verify the exact config over the Admin API."""

    def __init__(
        self,
        target_policy: RegisteredSourceTargetPolicy,
        reader: NacosRuleSourceReader,
        *,
        http_client: PinnedAioHttpJsonClient | None = None,
        grpc_client: NacosGrpcRequestClient | None = None,
        clock_ns: Callable[[], int] = time_ns,
        request_id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._target_policy = target_policy
        self._reader = reader
        self._http_client = http_client or PinnedAioHttpJsonClient()
        self._grpc_client = grpc_client or NacosGrpcTransport()
        self._clock_ns = clock_ns
        self._request_id_factory = request_id_factory

    async def write(
        self, command: NacosRuleSourceWrite
    ) -> NacosRuleSourceWriteReceipt:
        """Dispatch a single non-retried CAS and require exact provider read-back."""
        try:
            http_target = await self._target_policy.resolve(command.connection)
            grpc_target = self._target_policy.with_port(
                command.connection,
                http_target,
                http_target.port + _NACOS_GRPC_PORT_OFFSET,
            )
        except (SourceTargetRejected, OSError, TimeoutError) as error:
            raise NacosRuleSourceUnavailable from error

        try:
            access_token = await resolve_nacos_access_token(
                command.connection, http_target, self._http_client.request
            )
        except NacosAccessTokenRejected:
            raise NacosRuleSourceWriteRejected from None
        except (
            NacosAccessTokenUnavailable,
            aiohttp.ClientError,
            TimeoutError,
            OSError,
        ):
            raise NacosRuleSourceUnavailable from None

        headers = _request_headers(
            access_token=access_token,
            timestamp_ms=self._clock_ns() // 1_000_000,
        )
        request_id = self._request_id_factory()
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("Nacos request id is invalid")
        body: dict[str, object] = {
            "headers": {},
            "requestId": request_id,
            "module": "config",
            "group": command.target.group,
            "dataId": command.target.data_id,
            "tenant": command.target.namespace,
            "content": command.value.decode("utf-8"),
            "casMd5": command.expected_md5,
            "additionMap": {
                "type": "json",
                "tag": "",
                "appName": "",
                "betaIps": "",
                "src_user": "",
                "encryptedDataKey": "",
            },
        }
        try:
            response_type, response = await self._grpc_client.request(
                grpc_target,
                request_type="ConfigPublishRequest",
                body=body,
                headers=headers,
            )
        except NacosGrpcConflict:
            raise NacosRuleSourceConflict from None
        except NacosGrpcRejected:
            raise NacosRuleSourceWriteRejected from None
        except NacosGrpcUnavailable:
            raise NacosRuleSourceUnavailable from None
        except NacosGrpcOutcomeUnknown:
            raise NacosRuleSourceOutcomeUnknown from None

        _verify_publish_response(response_type, response)
        try:
            snapshot = await self._reader.read(command.connection, command.target)
        except (NacosRuleSourceReadRejected, NacosRuleSourceReadUnavailable):
            raise NacosRuleSourceOutcomeUnknown from None
        if snapshot.value != command.value:
            raise NacosRuleSourceOutcomeUnknown
        if snapshot.md5.casefold() != _md5(command.value):
            raise NacosRuleSourceOutcomeUnknown
        return NacosRuleSourceWriteReceipt(snapshot.md5)


def _request_headers(*, access_token: str | None, timestamp_ms: int) -> dict[str, str]:
    timestamp = str(timestamp_ms)
    headers = {
        "clientAppName": "atlas-richie-sentinel-console",
        "clientRequestTS": timestamp,
        _NACOS_REQUEST_TOKEN_HEADER: hashlib.md5(
            timestamp.encode("ascii"), usedforsecurity=False
        ).hexdigest(),
        "exConfigInfo": "true",
        "charset": "utf-8",
        "Timestamp": timestamp,
    }
    if access_token is not None:
        headers[NACOS_ACCESS_TOKEN_HEADER] = access_token
    return headers


def _verify_publish_response(
    response_type: str, response: dict[str, object]
) -> None:
    error_code = response.get("errorCode")
    if (
        type(error_code) is int
        and error_code == _NACOS_RESOURCE_CONFLICT_CODE
    ) or (
        response_type == "ConfigPublishResponse"
        and response.get("resultCode") == _NACOS_CAS_CONFLICT_STATUS
        and error_code == _NACOS_CAS_CONFLICT_STATUS
        and response.get("message") == _NACOS_CAS_CONFLICT_MESSAGE
    ):
        raise NacosRuleSourceConflict
    if (
        response_type != "ConfigPublishResponse"
        or type(response.get("resultCode")) is not int
        or response.get("resultCode") != 200
        or type(error_code) is not int
        or error_code != 0
    ):
        raise NacosRuleSourceOutcomeUnknown


def _md5(value: bytes) -> str:
    return hashlib.md5(value, usedforsecurity=False).hexdigest()


__all__ = [
    "NacosRuleSourceConflict",
    "NacosRuleSourceOutcomeUnknown",
    "NacosRuleSourceUnavailable",
    "NacosRuleSourceWrite",
    "NacosRuleSourceWriteReceipt",
    "NacosRuleSourceWriteRejected",
    "NacosRuleSourceWriter",
]
