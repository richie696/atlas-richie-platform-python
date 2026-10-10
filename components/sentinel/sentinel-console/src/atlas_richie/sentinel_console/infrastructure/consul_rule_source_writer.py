"""Consul KV conditional rule writes with exact read-back verification."""

from __future__ import annotations

from dataclasses import dataclass
import json

from ..application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from ..domain.configuration_source import ConfigurationSourceProvider
from .registered_source_checker import (
    PinnedAioHttpJsonClient,
    PinnedSourceTarget,
    RegisteredSourceTargetPolicy,
    SourceTargetRejected,
)
from .consul_rule_source_support import (
    CONSUL_INDEX_PATTERN,
    CONSUL_TRANSPORT_ERRORS,
    MAX_CONSUL_INDEX,
    datacenter_params,
    decode_consul_exact_key_response,
    encode_consul_key,
    is_valid_consul_key,
)

_MAX_CONSUL_VALUE_BYTES = 512 * 1024
_DENIED_STATUSES = frozenset({401, 403})


class ConsulRuleSourceConflict(RuntimeError):
    """The Consul KV value no longer has the expected ModifyIndex."""


class ConsulRuleSourceWriteRejected(RuntimeError):
    """Consul explicitly rejected the write authorization."""


class ConsulRuleSourceOutcomeUnknown(RuntimeError):
    """A dispatched write or its exact read-back could not be confirmed."""


class ConsulRuleSourceUnavailable(RuntimeError):
    """The target failed deployment network policy before any write request."""


@dataclass(frozen=True, slots=True)
class ConsulRuleSourceWrite:
    """One exact Consul KV update request; `None` baseline means create-only."""

    connection: SourceConnectionInput
    key: str
    expected_modify_index: str | None
    value: bytes

    def __post_init__(self) -> None:
        if self.connection.provider is not ConfigurationSourceProvider.CONSUL:
            raise ValueError("Consul rule writes require a Consul connection")
        if self.connection.authentication_mode not in {
            SourceCheckAuthenticationMode.NONE,
            SourceCheckAuthenticationMode.DIRECT,
        }:
            raise ValueError("Consul rule writes require resolved credentials")
        if not is_valid_consul_key(self.key):
            raise ValueError("Consul rule key is invalid")
        if (
            not isinstance(self.value, bytes)
            or not self.value
            or len(self.value) > _MAX_CONSUL_VALUE_BYTES
        ):
            raise ValueError("Consul rule value exceeds the supported size")
        if self.expected_modify_index is not None:
            if (
                not isinstance(self.expected_modify_index, str)
                or CONSUL_INDEX_PATTERN.fullmatch(self.expected_modify_index) is None
            ):
                raise ValueError("Consul ModifyIndex must be an unsigned decimal string")
            index = int(self.expected_modify_index)
            if not 0 < index <= MAX_CONSUL_INDEX:
                raise ValueError("Consul ModifyIndex is out of range")


@dataclass(frozen=True, slots=True)
class ConsulRuleSourceWriteReceipt:
    """Provider revision observed after the exact candidate bytes were read back."""

    modify_index: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.modify_index, str)
            or CONSUL_INDEX_PATTERN.fullmatch(self.modify_index) is None
            or not 0 < int(self.modify_index) <= MAX_CONSUL_INDEX
        ):
            raise ValueError("Consul write receipt requires a valid ModifyIndex")


class ConsulRuleSourceWriter:
    """Apply one Consul CAS and independently verify the exact stored value."""

    def __init__(
        self,
        target_policy: RegisteredSourceTargetPolicy,
        http_client: PinnedAioHttpJsonClient | None = None,
    ) -> None:
        self._target_policy = target_policy
        self._http_client = http_client or PinnedAioHttpJsonClient()

    async def write(
        self, command: ConsulRuleSourceWrite
    ) -> ConsulRuleSourceWriteReceipt:
        """Write once using server CAS; never retries an uncertain result."""
        try:
            target = await self._target_policy.resolve(command.connection)
        except (SourceTargetRejected, OSError, TimeoutError) as error:
            raise ConsulRuleSourceUnavailable from error

        headers = {"Accept": "application/json", "Content-Type": "application/octet-stream"}
        if command.connection.acl_token is not None:
            headers["X-Consul-Token"] = command.connection.acl_token
        key_path = encode_consul_key(command.key)
        base_params = datacenter_params(command.connection.location)
        cas_index = command.expected_modify_index or "0"
        put_headers = {**headers}
        try:
            status, body, _response_headers = await self._request(
                target=target,
                connection=command.connection,
                method="PUT",
                path=f"/v1/kv/{key_path}",
                params={**base_params, "cas": cas_index},
                headers=put_headers,
                body=command.value,
            )
        except CONSUL_TRANSPORT_ERRORS as error:
            raise ConsulRuleSourceOutcomeUnknown from error

        if status in _DENIED_STATUSES:
            raise ConsulRuleSourceWriteRejected
        if status != 200:
            raise ConsulRuleSourceOutcomeUnknown
        try:
            accepted = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ConsulRuleSourceOutcomeUnknown from error
        if accepted is False:
            raise ConsulRuleSourceConflict
        if accepted is not True:
            raise ConsulRuleSourceOutcomeUnknown

        try:
            read_status, read_body, _read_headers = await self._request(
                target=target,
                connection=command.connection,
                method="GET",
                path=f"/v1/kv/{key_path}",
                params=base_params,
                headers={key: value for key, value in headers.items() if key != "Content-Type"},
            )
            return _verified_receipt(read_status, read_body, command)
        except CONSUL_TRANSPORT_ERRORS as error:
            raise ConsulRuleSourceOutcomeUnknown from error

    async def _request(
        self,
        *,
        target: PinnedSourceTarget,
        connection: SourceConnectionInput,
        method: str,
        path: str,
        params: dict[str, str],
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        return await self._http_client.request_raw(
            target=target,
            endpoint=connection.endpoint,
            method=method,
            path=path,
            params=params,
            headers=headers,
            body=body,
        )


def _verified_receipt(
    status: int, body: bytes, command: ConsulRuleSourceWrite
) -> ConsulRuleSourceWriteReceipt:
    if status in _DENIED_STATUSES:
        raise ConsulRuleSourceOutcomeUnknown
    if status != 200:
        raise ConsulRuleSourceOutcomeUnknown
    try:
        actual_value, modify_index = decode_consul_exact_key_response(
            body, command.key
        )
    except ValueError:
        raise ConsulRuleSourceOutcomeUnknown
    if (
        modify_index <= int(command.expected_modify_index or "0")
        or actual_value != command.value
    ):
        raise ConsulRuleSourceOutcomeUnknown
    return ConsulRuleSourceWriteReceipt(str(modify_index))
