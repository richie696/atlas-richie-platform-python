"""Read exact Consul KV revisions for safe publication reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from ..domain.configuration_source import ConfigurationSourceProvider
from .consul_rule_source_support import (
    CONSUL_INDEX_PATTERN,
    CONSUL_TRANSPORT_ERRORS,
    MAX_CONSUL_INDEX,
    datacenter_params,
    decode_consul_exact_key_response,
    encode_consul_key,
    is_valid_consul_key,
)
from .registered_source_checker import (
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
    SourceTargetRejected,
)


class ConsulRuleSourceReadRejected(RuntimeError):
    """Consul explicitly denied a read of the selected rule key."""


class ConsulRuleSourceReadUnavailable(RuntimeError):
    """A read could not establish trustworthy exact-key metadata."""


@dataclass(frozen=True, slots=True)
class ConsulRuleSourceSnapshot:
    """One exact observed KV state; rule bytes are excluded from repr."""

    key: str
    value: bytes | None = field(repr=False)
    modify_index: str | None

    def __post_init__(self) -> None:
        if not is_valid_consul_key(self.key):
            raise ValueError("Consul snapshot key is invalid")
        if (self.value is None) != (self.modify_index is None):
            raise ValueError("Consul snapshot value and revision must appear together")
        if self.value is not None and not isinstance(self.value, bytes):
            raise ValueError("Consul snapshot value must be bytes")
        if self.modify_index is not None and (
            not isinstance(self.modify_index, str)
            or CONSUL_INDEX_PATTERN.fullmatch(self.modify_index) is None
            or not 0 < int(self.modify_index) <= MAX_CONSUL_INDEX
        ):
            raise ValueError("Consul snapshot ModifyIndex is invalid")

    @property
    def exists(self) -> bool:
        """Whether Consul returned an exact key value."""
        return self.modify_index is not None


class ConsulRuleSourceReader:
    """Read one pinned, exact Consul KV key without changing provider state."""

    def __init__(
        self,
        target_policy: RegisteredSourceTargetPolicy,
        http_client: PinnedAioHttpJsonClient | None = None,
    ) -> None:
        self._target_policy = target_policy
        self._http_client = http_client or PinnedAioHttpJsonClient()

    async def read(
        self, connection: SourceConnectionInput, key: str
    ) -> ConsulRuleSourceSnapshot:
        """Return an absent or exact value/revision observation for one key."""
        if connection.provider is not ConfigurationSourceProvider.CONSUL:
            raise ValueError("Consul rule reads require a Consul connection")
        if connection.authentication_mode not in {
            SourceCheckAuthenticationMode.NONE,
            SourceCheckAuthenticationMode.DIRECT,
        }:
            raise ValueError("Consul rule reads require resolved credentials")
        if not is_valid_consul_key(key):
            raise ValueError("Consul rule key is invalid")
        try:
            target = await self._target_policy.resolve(connection)
        except (SourceTargetRejected, OSError, TimeoutError):
            raise ConsulRuleSourceReadUnavailable from None

        headers = {"Accept": "application/json"}
        if connection.acl_token is not None:
            headers["X-Consul-Token"] = connection.acl_token
        try:
            status, body, _response_headers = await self._http_client.request_raw(
                target=target,
                endpoint=connection.endpoint,
                method="GET",
                path=f"/v1/kv/{encode_consul_key(key)}",
                params={
                    **datacenter_params(connection.location),
                    "consistent": "true",
                },
                headers=headers,
            )
        except CONSUL_TRANSPORT_ERRORS:
            raise ConsulRuleSourceReadUnavailable from None
        if status in {401, 403}:
            raise ConsulRuleSourceReadRejected
        if status == 404:
            return ConsulRuleSourceSnapshot(key, None, None)
        if status != 200:
            raise ConsulRuleSourceReadUnavailable
        try:
            value, modify_index = decode_consul_exact_key_response(body, key)
            return ConsulRuleSourceSnapshot(key, value, str(modify_index))
        except ValueError:
            raise ConsulRuleSourceReadUnavailable from None


__all__ = [
    "ConsulRuleSourceReadRejected",
    "ConsulRuleSourceReadUnavailable",
    "ConsulRuleSourceReader",
    "ConsulRuleSourceSnapshot",
]
