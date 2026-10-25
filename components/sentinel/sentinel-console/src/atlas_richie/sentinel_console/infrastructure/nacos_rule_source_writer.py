"""Nacos 3.x gRPC compare-and-set with exact Admin API read-back."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
import hashlib
import io
import json
import re
from time import time_ns
from uuid import uuid4
import zipfile

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
_NACOS_IMPORT_PATH = "/v3/admin/cs/config/import"
_NACOS_IMPORT_POLICY_ABORT = "ABORT"
_NACOS_IMPORT_ARCHIVE_NAME = "sentinel-rule-config.zip"
_NACOS_IMPORT_METADATA_NAME = ".metadata.yml"
_NACOS_IMPORT_CONFIG_TYPE = "json"
_NACOS_IMPORT_SUCCESS_COUNT = 1
_NACOS_IMPORT_NO_ITEMS = 0
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
    """One exact Nacos config mutation with update-CAS or create-only semantics.

    A provider MD5 selects gRPC compare-and-set for an existing config. ``None``
    selects the Admin import API's one-item ``ABORT`` policy, which creates only
    when the exact namespace/group/dataId is absent.
    """

    connection: SourceConnectionInput
    target: NacosRulePublicationTarget
    expected_md5: str | None
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
        if self.expected_md5 is not None and (
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
        grpc_tls_enabled: bool = False,
        clock_ns: Callable[[], int] = time_ns,
        request_id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._target_policy = target_policy
        self._reader = reader
        self._http_client = http_client or PinnedAioHttpJsonClient()
        self._grpc_client = grpc_client or NacosGrpcTransport()
        if type(grpc_tls_enabled) is not bool:
            raise TypeError("Nacos gRPC TLS setting must be boolean")
        self._grpc_tls_enabled = grpc_tls_enabled
        self._clock_ns = clock_ns
        self._request_id_factory = request_id_factory

    async def write(
        self, command: NacosRuleSourceWrite
    ) -> NacosRuleSourceWriteReceipt:
        """Write once and require exact provider read-back before returning."""
        try:
            http_target = await self._target_policy.resolve(command.connection)
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

        if command.expected_md5 is None:
            return await self._create_if_absent(command, http_target, access_token)

        try:
            pinned_grpc_target = self._target_policy.with_port(
                command.connection,
                http_target,
                http_target.port + _NACOS_GRPC_PORT_OFFSET,
            )
        except (SourceTargetRejected, OSError, TimeoutError) as error:
            raise NacosRuleSourceUnavailable from error
        # HTTP and gRPC are independent Nacos transports. An HTTPS Admin API
        # endpoint does not imply that the adjacent gRPC port is also TLS.
        grpc_target = PinnedSourceTarget(
            pinned_grpc_target.hostname,
            pinned_grpc_target.port,
            pinned_grpc_target.addresses,
            secure=self._grpc_tls_enabled,
        )

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

    async def _create_if_absent(
        self,
        command: NacosRuleSourceWrite,
        http_target: PinnedSourceTarget,
        access_token: str | None,
    ) -> NacosRuleSourceWriteReceipt:
        """Use one-item Admin import ABORT, then verify exact bytes by fresh read."""
        archive = _single_config_archive(command.target, command.value)
        form = aiohttp.FormData()
        form.add_field("namespaceId", command.target.namespace)
        form.add_field("policy", _NACOS_IMPORT_POLICY_ABORT)
        form.add_field(
            "file",
            archive,
            filename=_NACOS_IMPORT_ARCHIVE_NAME,
            content_type="application/zip",
        )
        headers = (
            {NACOS_ACCESS_TOKEN_HEADER: access_token}
            if access_token is not None
            else {}
        )
        try:
            status, response_body, _response_headers = (
                await self._http_client.request_raw(
                    target=http_target,
                    endpoint=command.connection.endpoint,
                    method="POST",
                    path=_NACOS_IMPORT_PATH,
                    params={},
                    headers=headers,
                    form=form,
                )
            )
        except (aiohttp.ClientError, TimeoutError, OSError):
            # The import may have committed before the transport lost its response.
            raise NacosRuleSourceOutcomeUnknown from None

        if status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            raise NacosRuleSourceWriteRejected
        if not HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES:
            if status < HTTPStatus.BAD_REQUEST:
                raise NacosRuleSourceOutcomeUnknown
            raise NacosRuleSourceWriteRejected
        try:
            response = json.loads(response_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise NacosRuleSourceOutcomeUnknown from None
        if not isinstance(response, dict) or not _is_nacos_success_code(
            response.get("code")
        ):
            raise NacosRuleSourceOutcomeUnknown
        result = response.get("data")
        if not isinstance(result, dict):
            raise NacosRuleSourceOutcomeUnknown
        if _is_single_item_duplicate(result, command.target):
            raise NacosRuleSourceConflict
        if not _is_single_item_import_success(result):
            raise NacosRuleSourceOutcomeUnknown

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


def _single_config_archive(
    target: NacosRulePublicationTarget, value: bytes
) -> bytes:
    """Serialize the exact one-item format accepted by the Nacos 3 import API."""
    if any(
        not item
        or item.strip() != item
        or item in {".", ".."}
        or "/" in item
        or "\\" in item
        or any(ord(character) < 32 or ord(character) == 127 for character in item)
        for item in (target.group, target.data_id)
    ):
        raise NacosRuleSourceWriteRejected
    metadata = (
        "metadata:\n"
        f"  - group: {json.dumps(target.group, ensure_ascii=True)}\n"
        f"    dataId: {json.dumps(target.data_id, ensure_ascii=True)}\n"
        f"    type: {json.dumps(_NACOS_IMPORT_CONFIG_TYPE)}\n"
    ).encode()
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(
        archive_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr(_NACOS_IMPORT_METADATA_NAME, metadata)
        archive.writestr(f"{target.group}/{target.data_id}", value)
    return archive_buffer.getvalue()


def _is_nacos_success_code(value: object) -> bool:
    return (type(value) is int and value == 0) or (
        isinstance(value, str) and value == "0"
    )


def _is_single_item_duplicate(
    result: dict[str, object], target: NacosRulePublicationTarget
) -> bool:
    failures = result.get("failData")
    return (
        result.get("succCount") == _NACOS_IMPORT_NO_ITEMS
        and type(result.get("succCount")) is int
        and result.get("skipCount") == _NACOS_IMPORT_NO_ITEMS
        and type(result.get("skipCount")) is int
        and isinstance(failures, list)
        and failures == [{"dataId": target.data_id, "group": target.group}]
    )


def _is_single_item_import_success(result: dict[str, object]) -> bool:
    return (
        result.get("succCount") == _NACOS_IMPORT_SUCCESS_COUNT
        and type(result.get("succCount")) is int
        and result.get("skipCount") == _NACOS_IMPORT_NO_ITEMS
        and type(result.get("skipCount")) is int
        and result.get("unrecognizedCount", _NACOS_IMPORT_NO_ITEMS)
        == _NACOS_IMPORT_NO_ITEMS
        and type(
            result.get("unrecognizedCount", _NACOS_IMPORT_NO_ITEMS)
        )
        is int
        and "failData" not in result
    )


__all__ = [
    "NacosRuleSourceConflict",
    "NacosRuleSourceOutcomeUnknown",
    "NacosRuleSourceUnavailable",
    "NacosRuleSourceWrite",
    "NacosRuleSourceWriteReceipt",
    "NacosRuleSourceWriteRejected",
    "NacosRuleSourceWriter",
]
