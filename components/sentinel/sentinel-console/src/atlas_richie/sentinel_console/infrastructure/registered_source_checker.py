"""SSRF-bounded, read-only connectivity probes for Nacos and Consul."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import ipaddress
import json
import math
import re
import socket
import ssl
from typing import TypeAlias
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit

import aiohttp
import idna

from ..application.check_registered_source import (
    RegisteredSourceCheckResult,
    RegisteredSourceChecker,
    SourceCheckAuthenticationMode,
    SourceCheckCapability,
    SourceCheckFailureReason,
    SourceConnectionInput,
)
from ..domain.configuration_source import ConfigurationSourceProvider
from .nacos_source_support import (
    NACOS_ACCESS_TOKEN_HEADER,
    NACOS_HTTP_DENIED_STATUSES,
    NACOS_HTTP_OK_STATUS,
    NacosAccessTokenRejected,
    NacosAccessTokenUnavailable,
    is_nacos_success_code,
    is_safe_header_value,
    resolve_nacos_access_token,
)

IPAddress: TypeAlias = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork: TypeAlias = ipaddress.IPv4Network | ipaddress.IPv6Network
AddressInfo: TypeAlias = tuple[int, int, int, str, tuple[object, ...]]
AddressResolver: TypeAlias = Callable[
    [str, int], Awaitable[Sequence[AddressInfo]]
]
JsonRequest: TypeAlias = Callable[
    ..., Awaitable[tuple[int, dict[str, object], dict[str, str]]]
]

_REQUEST_TIMEOUT_SECONDS = 3.0
_DEFAULT_MAX_RESPONSE_BYTES = 65_536
_MAX_ALLOWED_RESPONSE_BYTES = 2 * 1024 * 1024
_RESULT_TTL = timedelta(seconds=60)
_MAX_DNS_ADDRESSES = 8
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class SourceTargetRejected(ValueError):
    """The configured source endpoint is outside deployment network policy."""


@dataclass(frozen=True, slots=True)
class RegisteredSourceTargetRule:
    """One provider, DNS name, port and resolved-network deployment grant."""

    provider: ConfigurationSourceProvider
    hostname: str
    networks: tuple[IPNetwork, ...]
    ports: frozenset[int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "hostname", _normalize_hostname(self.hostname))
        object.__setattr__(self, "networks", tuple(self.networks))
        object.__setattr__(self, "ports", frozenset(self.ports))
        if not self.hostname or not self.networks or not self.ports:
            raise ValueError("source target rule must grant a host, network and port")
        if any(network.prefixlen == 0 for network in self.networks):
            raise ValueError("source target rules cannot grant all addresses")
        if any(
            type(port) is not int or not 1 <= port <= 65535
            for port in self.ports
        ):
            raise ValueError("source target rule contains an invalid port")

    @classmethod
    def create(
        cls,
        provider: ConfigurationSourceProvider,
        hostname: str,
        networks: Sequence[str],
        ports: frozenset[int],
    ) -> RegisteredSourceTargetRule:
        """Parse deployment-owned host, CIDR and port grants strictly."""
        try:
            parsed_networks = tuple(
                ipaddress.ip_network(network, strict=True) for network in networks
            )
        except ValueError as error:
            raise ValueError(
                "source target network configuration is invalid"
            ) from error
        return cls(provider, hostname, parsed_networks, ports)


@dataclass(frozen=True, slots=True)
class PinnedSourceTarget:
    """Validated destination addresses used for the duration of one check."""

    hostname: str
    port: int
    addresses: tuple[IPAddress, ...]
    secure: bool = False


class RegisteredSourceTargetPolicy:
    """Require an explicit host/port grant and pin all allowlisted DNS answers."""

    def __init__(
        self,
        rules: Sequence[RegisteredSourceTargetRule],
        resolver: AddressResolver | None = None,
    ) -> None:
        self._rules = tuple(rules)
        self._resolver = resolver
        if not self._rules:
            raise ValueError("registered-source target rules are required")

    async def resolve(self, command: SourceConnectionInput) -> PinnedSourceTarget:
        """Validate endpoint identity, resolve once, and reject mixed DNS answers."""
        try:
            parsed = urlsplit(command.endpoint)
            port = (
                parsed.port
                if parsed.port is not None
                else (443 if parsed.scheme.lower() == "https" else 80)
            )
            hostname = _normalize_hostname(parsed.hostname or "")
        except (UnicodeError, ValueError) as error:
            raise SourceTargetRejected from error
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "\\" in unquote(parsed.path)
            or any(
                segment in {".", ".."}
                for segment in unquote(parsed.path).split("/")
            )
            or not self._matching_rules(command.provider, hostname, port)
            or (
                command.authentication_mode is not SourceCheckAuthenticationMode.NONE
                and parsed.scheme.lower() != "https"
            )
        ):
            raise SourceTargetRejected

        matching_rules = self._matching_rules(command.provider, hostname, port)
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            addresses = await self._resolve_hostname(hostname, port)
        else:
            addresses = (literal,)
        if not addresses or any(
            address.is_link_local
            or address.is_unspecified
            or address.is_multicast
            or not any(
                address in network
                for rule in matching_rules
                for network in rule.networks
            )
            for address in addresses
        ):
            raise SourceTargetRejected
        return PinnedSourceTarget(
            hostname,
            port,
            addresses,
            secure=parsed.scheme.lower() == "https",
        )

    def with_port(
        self,
        command: SourceConnectionInput,
        target: PinnedSourceTarget,
        port: int,
    ) -> PinnedSourceTarget:
        """Reuse resolved IPs for another explicitly allowlisted service port."""
        if type(port) is not int or not 1 <= port <= 65535:
            raise SourceTargetRejected
        if not self._matching_rules(command.provider, target.hostname, port):
            raise SourceTargetRejected
        return PinnedSourceTarget(
            target.hostname, port, target.addresses, secure=target.secure
        )

    def _matching_rules(
        self,
        provider: ConfigurationSourceProvider,
        hostname: str,
        port: int,
    ) -> tuple[RegisteredSourceTargetRule, ...]:
        return tuple(
            rule
            for rule in self._rules
            if rule.provider is provider
            and rule.hostname == hostname
            and port in rule.ports
        )

    async def _resolve_hostname(
        self, hostname: str, port: int
    ) -> tuple[IPAddress, ...]:
        resolver = self._resolver or _system_resolver
        try:
            async with asyncio.timeout(2.0):
                records = await resolver(hostname, port)
        except (OSError, asyncio.TimeoutError) as error:
            raise SourceTargetRejected from error
        addresses: list[IPAddress] = []
        for family, _kind, _protocol, _canonical, sockaddr in records:
            if family not in {socket.AF_INET, socket.AF_INET6} or not sockaddr:
                continue
            try:
                address = ipaddress.ip_address(str(sockaddr[0]))
            except ValueError:
                continue
            if address not in addresses:
                addresses.append(address)
                if len(addresses) > _MAX_DNS_ADDRESSES:
                    raise SourceTargetRejected
        return tuple(addresses)


class PinnedAioHttpJsonClient:
    """Pinned HTTP transport for JSON probes and bounded raw provider payloads."""

    def __init__(
        self,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        ssl_context: ssl.SSLContext | None = None,
        request_timeout_seconds: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if (
            type(max_response_bytes) is not int
            or not 1 <= max_response_bytes <= _MAX_ALLOWED_RESPONSE_BYTES
        ):
            raise ValueError("source response bound is invalid")
        if (
            isinstance(request_timeout_seconds, bool)
            or not isinstance(request_timeout_seconds, (int, float))
            or not math.isfinite(request_timeout_seconds)
            or not 0 < request_timeout_seconds <= 60
        ):
            raise ValueError("source request timeout is invalid")
        self._max_response_bytes = max_response_bytes
        self._request_timeout_seconds = float(request_timeout_seconds)
        if ssl_context is not None:
            if not isinstance(ssl_context, ssl.SSLContext):
                raise TypeError("source TLS context must be an SSLContext")
            if (
                ssl_context.verify_mode != ssl.CERT_REQUIRED
                or not ssl_context.check_hostname
            ):
                raise ValueError("source TLS context must verify peer identity")
        self._ssl_context = ssl_context

    async def request(
        self,
        *,
        target: PinnedSourceTarget,
        endpoint: str,
        method: str,
        path: str,
        params: dict[str, str],
        headers: dict[str, str],
        form: dict[str, str] | aiohttp.FormData | None = None,
    ) -> tuple[int, dict[str, object], dict[str, str]]:
        status, body, response_headers = await self.request_raw(
            target=target,
            endpoint=endpoint,
            method=method,
            path=path,
            params=params,
            headers=headers,
            form=form,
        )
        if status in {301, 302, 303, 307, 308} or not body:
            return status, {}, response_headers
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload: dict[str, object] = {}
        else:
            payload = decoded if isinstance(decoded, dict) else {}
        return status, payload, response_headers

    async def request_raw(
        self,
        *,
        target: PinnedSourceTarget,
        endpoint: str,
        method: str,
        path: str,
        params: dict[str, str],
        headers: dict[str, str],
        form: dict[str, str] | aiohttp.FormData | None = None,
        body: bytes | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        """Request bounded raw bytes through the same pinned, no-redirect transport."""
        if form is not None and body is not None:
            raise ValueError("HTTP form and raw body are mutually exclusive")
        resolver = _PinnedAioHttpResolver(target)
        base = urlsplit(endpoint)
        base_path = base.path.rstrip("/")
        request_path = f"{base_path}/{path.lstrip('/')}"
        request_url = urlunsplit(
            (base.scheme, base.netloc, request_path, urlencode(params), "")
        )
        timeout = aiohttp.ClientTimeout(total=self._request_timeout_seconds)
        connector = aiohttp.TCPConnector(
            resolver=resolver,
            use_dns_cache=False,
            limit=1,
            force_close=True,
            ssl=(
                self._ssl_context if self._ssl_context is not None else True
            ) if base.scheme == "https" else None,
        )
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            trust_env=False,
            auto_decompress=False,
        )
        if not hasattr(session, "_retry_connection"):
            await session.close()
            raise RuntimeError(
                "aiohttp transport cannot guarantee single-attempt requests"
            )
        # aiohttp retries idempotent methods after a lost connection. A Consul
        # CAS uses PUT but is not safe to repeat after an ambiguous commit. There
        # is no public aiohttp switch for this behavior, so guard the supported
        # internal control here; fail closed if an upgrade removes it.
        session._retry_connection = False
        async with (
            session,
            session.request(
                method,
                request_url,
                headers=headers,
                data=form if body is None else body,
                allow_redirects=False,
            ) as response,
        ):
            response_body = await _read_bounded(
                response.content, self._max_response_bytes
            )
            return response.status, response_body, dict(response.headers)


class NacosRegisteredSourceChecker:
    """Verify Nacos authentication and namespace config-read permission, read-only."""

    def __init__(
        self, policy: RegisteredSourceTargetPolicy, request: JsonRequest
    ) -> None:
        self._policy = policy
        self._request = request

    async def check(
        self, command: SourceConnectionInput, actor_id: str
    ) -> RegisteredSourceCheckResult:
        del actor_id  # Identity is reserved for server-side audit by the caller.
        if command.provider is not ConfigurationSourceProvider.NACOS:
            return _failed(SourceCheckFailureReason.UNSUPPORTED)
        try:
            target = await self._policy.resolve(command)
            access_token = await resolve_nacos_access_token(
                command, target, self._request
            )
            params = {
                "namespaceId": command.location or "public",
                "pageNo": "1",
                "pageSize": "1",
            }
            headers = (
                {NACOS_ACCESS_TOKEN_HEADER: access_token} if access_token else {}
            )
            status, payload, _headers = await self._request(
                target=target,
                endpoint=command.endpoint,
                method="GET",
                path="/v3/admin/cs/config/list",
                params=params,
                headers=headers,
            )
            if status in NACOS_HTTP_DENIED_STATUSES:
                return _failed(SourceCheckFailureReason.AUTHENTICATION)
            if status != NACOS_HTTP_OK_STATUS or not is_nacos_success_code(
                payload.get("code")
            ):
                return _failed(SourceCheckFailureReason.CONNECTION)
            return _success((SourceCheckCapability.READ,))
        except NacosAccessTokenRejected:
            return _failed(SourceCheckFailureReason.AUTHENTICATION)
        except NacosAccessTokenUnavailable:
            return _failed(SourceCheckFailureReason.CONNECTION)
        except SourceTargetRejected:
            return _failed(SourceCheckFailureReason.UNSUPPORTED)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return _failed(SourceCheckFailureReason.CONNECTION)


class ConsulRegisteredSourceChecker:
    """Verify Consul KV key-list read and blocking-query support without writes."""

    def __init__(
        self, policy: RegisteredSourceTargetPolicy, request: JsonRequest
    ) -> None:
        self._policy = policy
        self._request = request

    async def check(
        self, command: SourceConnectionInput, actor_id: str
    ) -> RegisteredSourceCheckResult:
        del actor_id
        if command.provider is not ConfigurationSourceProvider.CONSUL:
            return _failed(SourceCheckFailureReason.UNSUPPORTED)
        try:
            if (
                command.authentication_mode is SourceCheckAuthenticationMode.DIRECT
                and command.acl_token is not None
                and not is_safe_header_value(command.acl_token)
            ):
                return _failed(SourceCheckFailureReason.UNSUPPORTED)
            target = await self._policy.resolve(command)
            headers = (
                {"X-Consul-Token": command.acl_token}
                if command.authentication_mode is SourceCheckAuthenticationMode.DIRECT
                else {}
            )
            if (
                command.authentication_mode
                is SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE
            ):
                return _failed(SourceCheckFailureReason.UNSUPPORTED)
            status, _payload, response_headers = await self._request(
                target=target,
                endpoint=command.endpoint,
                method="GET",
                path="/v1/kv/",
                params={
                    "keys": "true",
                    "dc": command.location,
                    "index": "1",
                    "wait": "1ms",
                },
                headers=headers,
            )
            if status in {401, 403}:
                return _failed(SourceCheckFailureReason.AUTHENTICATION)
            if status not in {200, 404}:
                return _failed(SourceCheckFailureReason.CONNECTION)
            capabilities = [SourceCheckCapability.READ]
            if "X-Consul-Index" in response_headers:
                capabilities.append(SourceCheckCapability.WATCH)
            return _success(tuple(capabilities))
        except SourceTargetRejected:
            return _failed(SourceCheckFailureReason.UNSUPPORTED)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return _failed(SourceCheckFailureReason.CONNECTION)


class ProviderRegisteredSourceChecker(RegisteredSourceChecker):
    """Route the stable checker Port to the provider-specific HTTP adapters."""

    def __init__(
        self,
        nacos: NacosRegisteredSourceChecker,
        consul: ConsulRegisteredSourceChecker,
    ) -> None:
        self._adapters = {
            ConfigurationSourceProvider.NACOS: nacos,
            ConfigurationSourceProvider.CONSUL: consul,
        }

    async def check(
        self, command: SourceConnectionInput, actor_id: str
    ) -> RegisteredSourceCheckResult:
        adapter = self._adapters.get(command.provider)
        if adapter is None:
            return _failed(SourceCheckFailureReason.UNSUPPORTED)
        return await adapter.check(command, actor_id)


class _PinnedAioHttpResolver(aiohttp.abc.AbstractResolver):
    """Answer one host lookup only with the IP set already checked by policy."""

    def __init__(self, target: PinnedSourceTarget) -> None:
        self._target = target

    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_INET
    ) -> list[dict[str, object]]:
        if host != self._target.hostname or port != self._target.port:
            raise OSError("pinned source target mismatch")
        return [
            {
                "hostname": host,
                "host": address.compressed,
                "port": port,
                "family": socket.AF_INET6 if address.version == 6 else socket.AF_INET,
                "proto": socket.IPPROTO_TCP,
                "flags": socket.AI_NUMERICHOST,
            }
            for address in self._target.addresses
            if family in {
                socket.AF_UNSPEC,
                socket.AF_INET6 if address.version == 6 else socket.AF_INET,
            }
        ]

    async def close(self) -> None:
        return None


async def _system_resolver(hostname: str, port: int) -> Sequence[AddressInfo]:
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(
        hostname,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )


async def _read_bounded(
    stream: aiohttp.StreamReader, maximum_bytes: int
) -> bytes:
    body = bytearray()
    async for chunk in stream.iter_chunked(8192):
        body.extend(chunk)
        if len(body) > maximum_bytes:
            raise aiohttp.ClientPayloadError("source check response exceeded limit")
    return bytes(body)


def _success(
    capabilities: tuple[SourceCheckCapability, ...],
) -> RegisteredSourceCheckResult:
    checked_at = datetime.now(UTC)
    return RegisteredSourceCheckResult(
        checked_at, checked_at + _RESULT_TTL, capabilities
    )


def _failed(reason: SourceCheckFailureReason) -> RegisteredSourceCheckResult:
    checked_at = datetime.now(UTC)
    return RegisteredSourceCheckResult(
        checked_at, checked_at + _RESULT_TTL, reason=reason
    )


def _normalize_hostname(hostname: str) -> str:
    if not isinstance(hostname, str) or not hostname or hostname != hostname.strip():
        raise ValueError("source target hostname is invalid")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        candidate = hostname[:-1] if hostname.endswith(".") else hostname
        try:
            normalized = idna.encode(
                candidate, uts46=True, transitional=False
            ).decode("ascii").lower()
        except UnicodeError as error:
            raise ValueError("source target hostname is invalid") from error
        if (
            not normalized
            or len(normalized) > 253
            or any(not _DNS_LABEL.fullmatch(label) for label in normalized.split("."))
        ):
            raise ValueError("source target hostname is invalid")
        return normalized
    return address.compressed
