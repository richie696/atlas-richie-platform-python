"""Deployment-owned one-time bootstrap grants on a protected local POSIX file."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
from secrets import token_urlsafe
from typing import Any, Callable
from urllib.parse import urlsplit

from ...application.authorize_bootstrap import (
    BootstrapAuthorizationAuthority,
    BootstrapAuthorizationDecision,
    BootstrapAuthorizationStatus,
    BootstrapOperatorGrant,
    is_valid_bootstrap_operator_code,
)
from ...application.bootstrap_ports import (
    BootstrapOperatorSessionVerifier,
    SetupWindowReader,
)
from ...application.errors import BootstrapAuthorityUnavailable
from .local_atomic_file_store import (
    LocalAtomicFileConflict,
    LocalAtomicFileStore,
    LocalAtomicFileStoreError,
)
from .bootstrap_initialization_lock import LocalBootstrapInitializationLock

_AUTHORITY_PATH_ENV = "SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH"
_OPERATOR_CODE_ENV = "SENTINEL_CONSOLE_BOOTSTRAP_OPERATOR_CODE"
_FINGERPRINT_KEY_ENV = "SENTINEL_CONSOLE_BOOTSTRAP_FINGERPRINT_KEY"
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITY_SCHEMA_VERSION = 1
_MAX_AUTHORITY_FILE_BYTES = 32_768
_MAX_TRACKED_CLIENTS = 128
_MAX_ACTIVE_GRANTS = 1
_DEFAULT_GRANT_TTL_SECONDS = 300
_DEFAULT_FAILURE_WINDOW_SECONDS = 300
_DEFAULT_FAILURE_LIMIT = 5
_DEFAULT_BLOCK_SECONDS = 300
_DIGEST_PURPOSES = frozenset({"operator-code", "client-address", "operator-grant"})
_BIND_HOST_ENV = "SENTINEL_CONSOLE_BIND_HOST"
_BROWSER_ORIGINS_ENV = "SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS"
_TRUSTED_PROXY_CIDRS_ENV = "SENTINEL_CONSOLE_TRUSTED_PROXY_CIDRS"


def loopback_bootstrap_without_code_allowed(
    values: Mapping[str, str],
) -> bool:
    """Require loopback bind/origins and no proxy trust before removing the code gate."""
    host = values.get(_BIND_HOST_ENV, "127.0.0.1")
    try:
        if not ipaddress.ip_address(host).is_loopback:
            return False
    except (ValueError, TypeError):
        return False
    if values.get(_TRUSTED_PROXY_CIDRS_ENV, "").strip():
        return False
    raw_origins = values.get(_BROWSER_ORIGINS_ENV, "")
    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    if not origins:
        return False
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            hostname = parsed.hostname
            if parsed.scheme not in {"http", "https"} or hostname is None:
                return False
            if hostname.lower() != "localhost":
                if not ipaddress.ip_address(hostname).is_loopback:
                    return False
        except (ValueError, TypeError):
            return False
    return True


class BootstrapAuthorizationConfigurationError(ValueError):
    """Deployment bootstrap authorization inputs are missing or invalid."""


@dataclass(frozen=True, slots=True)
class BootstrapAuthorizationConfiguration:
    """Write-only operator code and its independent HMAC key material."""

    state_path: Path
    operator_code: str = field(repr=False)
    fingerprint_key: bytes = field(repr=False)
    allow_loopback_without_code: bool = False
    grant_ttl_seconds: int = _DEFAULT_GRANT_TTL_SECONDS
    failure_window_seconds: int = _DEFAULT_FAILURE_WINDOW_SECONDS
    failure_limit: int = _DEFAULT_FAILURE_LIMIT
    block_seconds: int = _DEFAULT_BLOCK_SECONDS

    def __post_init__(self) -> None:
        if (
            not isinstance(self.state_path, Path)
            or not self.state_path.is_absolute()
            or self.state_path.name in {"", ".", ".."}
        ):
            raise BootstrapAuthorizationConfigurationError(
                "bootstrap authority path must be absolute"
            )
        if (
            not isinstance(self.operator_code, str)
            or not is_valid_bootstrap_operator_code(self.operator_code)
        ):
            raise BootstrapAuthorizationConfigurationError(
                "deployment bootstrap operator code is invalid"
            )
        if (
            not isinstance(self.fingerprint_key, bytes)
            or len(self.fingerprint_key) < 32
        ):
            raise BootstrapAuthorizationConfigurationError(
                "bootstrap authority fingerprint key is invalid"
            )
        if (
            type(self.grant_ttl_seconds) is not int
            or not 1 <= self.grant_ttl_seconds <= 900
            or type(self.failure_window_seconds) is not int
            or not 1 <= self.failure_window_seconds <= 3_600
            or type(self.failure_limit) is not int
            or not 1 <= self.failure_limit <= 20
            or type(self.block_seconds) is not int
            or not 1 <= self.block_seconds <= 86_400
        ):
            raise BootstrapAuthorizationConfigurationError(
                "bootstrap authorization limits are invalid"
            )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        allow_loopback_without_code: bool = False,
    ) -> BootstrapAuthorizationConfiguration:
        """Read required secrets without echoing values through errors."""
        values = os.environ if environment is None else environment
        try:
            path_text = values[_AUTHORITY_PATH_ENV]
            operator_code = values.get(_OPERATOR_CODE_ENV)
            key_text = values[_FINGERPRINT_KEY_ENV]
            if not isinstance(path_text, str) or not path_text:
                raise ValueError("path")
            if not isinstance(key_text, str):
                raise ValueError("key")
            key_bytes = base64.b64decode(key_text, validate=True)
            if operator_code is None and allow_loopback_without_code:
                # Stable across worker restarts, never exposed to the browser, and
                # used only to preserve the existing durable grant fingerprint format.
                operator_code = hmac.new(
                    key_bytes,
                    b"sentinel-bootstrap-local-operator-code:v1",
                    hashlib.sha256,
                ).hexdigest()
            return cls(
                state_path=Path(path_text),
                operator_code=operator_code,
                fingerprint_key=key_bytes,
                allow_loopback_without_code=allow_loopback_without_code,
            )
        except (KeyError, TypeError, ValueError):
            raise BootstrapAuthorizationConfigurationError(
                "bootstrap authorization deployment configuration is "
                "incomplete or invalid"
            ) from None

    def create_authority(
        self,
        setup_window_reader: SetupWindowReader,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> LocalBootstrapAuthorizationAuthority:
        """Create the adapter sharing durable local rate-limit and grant state."""
        lock_path = self.state_path.with_name(
            f".{self.state_path.name}.authority-workflow"
        )
        return LocalBootstrapAuthorizationAuthority(
            state_path=self.state_path,
            workflow_lock=LocalBootstrapInitializationLock(lock_path),
            setup_window_reader=setup_window_reader,
            operator_code=self.operator_code,
            fingerprint_key=self.fingerprint_key,
            grant_ttl_seconds=self.grant_ttl_seconds,
            failure_window_seconds=self.failure_window_seconds,
            failure_limit=self.failure_limit,
            block_seconds=self.block_seconds,
            allow_loopback_without_code=self.allow_loopback_without_code,
            clock=clock,
        )


@dataclass(frozen=True, slots=True)
class _ClientAttemptState:
    fingerprint: str
    window_started_at: int
    failures: int
    blocked_until: int


@dataclass(frozen=True, slots=True)
class _GrantState:
    fingerprint: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class _AuthorityState:
    code_fingerprint: str
    code_consumed: bool
    clients: tuple[_ClientAttemptState, ...] = ()
    grants: tuple[_GrantState, ...] = ()


class LocalBootstrapAuthorizationAuthority(
    BootstrapAuthorizationAuthority,
    BootstrapOperatorSessionVerifier,
):
    """Validate one deployment code and persist expiring grants under file lock.

    The raw code and opaque grants never enter the state file. This adapter
    promises the host's local POSIX ``flock``/atomic-replace behavior only.
    Setup closure controls new grants and initialization; an existing unexpired
    grant remains verifiable for the constrained original-operation receipt
    recovery contract.
    """

    def __init__(
        self,
        *,
        state_path: Path,
        workflow_lock: LocalBootstrapInitializationLock,
        setup_window_reader: SetupWindowReader,
        operator_code: str,
        fingerprint_key: bytes,
        grant_ttl_seconds: int = _DEFAULT_GRANT_TTL_SECONDS,
        failure_window_seconds: int = _DEFAULT_FAILURE_WINDOW_SECONDS,
        failure_limit: int = _DEFAULT_FAILURE_LIMIT,
        block_seconds: int = _DEFAULT_BLOCK_SECONDS,
        allow_loopback_without_code: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._files = LocalAtomicFileStore(
            state_path, maximum_bytes=_MAX_AUTHORITY_FILE_BYTES
        )
        self._workflow_lock = workflow_lock
        self._setup_window_reader = setup_window_reader
        self._operator_code = operator_code
        self._fingerprint_key = bytes(fingerprint_key)
        self._grant_ttl_seconds = grant_ttl_seconds
        self._failure_window_seconds = failure_window_seconds
        self._failure_limit = failure_limit
        self._block_seconds = block_seconds
        self._allow_loopback_without_code = allow_loopback_without_code
        self._clock = clock or (lambda: datetime.now(UTC))

    async def exchange(
        self, operator_code: str, client_address: str
    ) -> BootstrapAuthorizationDecision:
        """Issue one short-lived grant after durable rate-limit checks."""
        if not isinstance(operator_code, str) or not isinstance(client_address, str):
            raise BootstrapAuthorityUnavailable(
                "bootstrap authorization authority is unavailable"
            ) from None
        async with self._workflow_lock.acquire():
            if not await self._setup_is_open():
                return BootstrapAuthorizationDecision(
                    BootstrapAuthorizationStatus.SETUP_CLOSED
                )
            raw = await self._read_state()
            now = self._now_seconds()
            code_fingerprint = self._fingerprint("operator-code", self._operator_code)
            state = self._state_for_current_code(raw, code_fingerprint, now)
            if state.code_consumed:
                return BootstrapAuthorizationDecision(
                    BootstrapAuthorizationStatus.REJECTED
                )

            client_fingerprint = self._fingerprint("client-address", client_address)
            clients = {entry.fingerprint: entry for entry in state.clients}
            attempt = clients.get(client_fingerprint)
            if attempt is not None and attempt.blocked_until > now:
                return _rate_limited(attempt.blocked_until, now)
            if (
                attempt is None
                or now - attempt.window_started_at >= self._failure_window_seconds
            ):
                attempt = _ClientAttemptState(
                    client_fingerprint, now, 0, 0
                )

            code_matches = is_valid_bootstrap_operator_code(operator_code) and (
                hmac.compare_digest(
                    operator_code.encode("ascii"),
                    self._operator_code.encode("ascii"),
                )
            )
            if not code_matches:
                updated = _ClientAttemptState(
                    client_fingerprint,
                    attempt.window_started_at,
                    attempt.failures + 1,
                    now + self._block_seconds
                    if attempt.failures + 1 >= self._failure_limit
                    else 0,
                )
                clients[client_fingerprint] = updated
                clients = self._prune_clients(clients, now)
                state = _AuthorityState(
                    code_fingerprint, False, tuple(clients.values()), state.grants
                )
                await self._write_state(raw, state)
                if updated.blocked_until > now:
                    return _rate_limited(updated.blocked_until, now)
                return BootstrapAuthorizationDecision(
                    BootstrapAuthorizationStatus.REJECTED
                )

            if attempt.failures:
                clients[client_fingerprint] = _ClientAttemptState(
                    client_fingerprint, now, 0, 0
                )
            if (
                client_fingerprint not in clients
                and len(clients) >= _MAX_TRACKED_CLIENTS
            ):
                return BootstrapAuthorizationDecision(
                    BootstrapAuthorizationStatus.RATE_LIMITED,
                    retry_after_ms=self._failure_window_seconds * 1000,
                )
            opaque_session = token_urlsafe(32)
            grant_state = _GrantState(
                self._fingerprint("operator-grant", opaque_session),
                now + self._grant_ttl_seconds,
            )
            clients = self._prune_clients(clients, now)
            granted_state = _AuthorityState(
                code_fingerprint,
                True,
                tuple(clients.values()),
                (grant_state,),
            )
            await self._write_state(raw, granted_state)
            return BootstrapAuthorizationDecision(
                BootstrapAuthorizationStatus.GRANTED,
                grant=BootstrapOperatorGrant(
                    opaque_session=opaque_session,
                    expires_in_seconds=self._grant_ttl_seconds,
                ),
            )

    async def authorize_local(
        self, client_address: str
    ) -> BootstrapAuthorizationDecision:
        """Issue a repeatable, short-lived grant only to a loopback peer."""
        try:
            loopback = ipaddress.ip_address(client_address).is_loopback
        except (ValueError, TypeError):
            loopback = False
        if not self._allow_loopback_without_code or not loopback:
            return BootstrapAuthorizationDecision(
                BootstrapAuthorizationStatus.REJECTED
            )
        async with self._workflow_lock.acquire():
            if not await self._setup_is_open():
                return BootstrapAuthorizationDecision(
                    BootstrapAuthorizationStatus.SETUP_CLOSED
                )
            raw = await self._read_state()
            now = self._now_seconds()
            code_fingerprint = self._fingerprint("operator-code", self._operator_code)
            state = self._state_for_current_code(raw, code_fingerprint, now)
            opaque_session = token_urlsafe(32)
            grant_state = _GrantState(
                self._fingerprint("operator-grant", opaque_session),
                now + self._grant_ttl_seconds,
            )
            await self._write_state(
                raw,
                _AuthorityState(
                    code_fingerprint,
                    True,
                    state.clients,
                    (grant_state,),
                ),
            )
            return BootstrapAuthorizationDecision(
                BootstrapAuthorizationStatus.GRANTED,
                grant=BootstrapOperatorGrant(
                    opaque_session=opaque_session,
                    expires_in_seconds=self._grant_ttl_seconds,
                ),
            )

    async def is_current_operator(self, opaque_session: str | None) -> bool:
        """Verify a grant without reopening setup or exposing stored state."""
        if not isinstance(opaque_session, str) or not opaque_session:
            return False
        async with self._workflow_lock.acquire():
            raw = await self._read_state()
            if raw is None:
                return False
            now = self._now_seconds()
            expected_code_fingerprint = self._fingerprint(
                "operator-code", self._operator_code
            )
            state = self._state_for_current_code(
                raw, expected_code_fingerprint, now
            )
            fingerprint = self._fingerprint("operator-grant", opaque_session)
            return any(
                grant.expires_at > now
                and hmac.compare_digest(grant.fingerprint, fingerprint)
                for grant in state.grants
            )

    async def _setup_is_open(self) -> bool:
        try:
            is_open = await self._setup_window_reader.is_setup_window_open()
        except BootstrapAuthorityUnavailable:
            raise
        except Exception:
            raise BootstrapAuthorityUnavailable(
                "bootstrap authorization authority is unavailable"
            ) from None
        if type(is_open) is not bool:
            raise BootstrapAuthorityUnavailable(
                "bootstrap authorization authority is unavailable"
            ) from None
        return is_open

    async def _read_state(self) -> bytes | None:
        try:
            raw = await self._files.read()
            if raw is None:
                return None
            self._decode_state(raw)
            return raw
        except LocalAtomicFileStoreError:
            raise BootstrapAuthorityUnavailable(
                "bootstrap authorization authority is unavailable"
            ) from None

    async def _write_state(self, raw: bytes | None, state: _AuthorityState) -> None:
        try:
            await self._files.compare_and_swap(raw, self._encode_state(state))
        except (LocalAtomicFileConflict, LocalAtomicFileStoreError):
            raise BootstrapAuthorityUnavailable(
                "bootstrap authorization authority is unavailable"
            ) from None

    def _state_for_current_code(
        self, raw: bytes | None, code_fingerprint: str, now: int
    ) -> _AuthorityState:
        if raw is None:
            return _AuthorityState(code_fingerprint, False)
        state = self._decode_state(raw)
        if not hmac.compare_digest(state.code_fingerprint, code_fingerprint):
            return _AuthorityState(code_fingerprint, False)
        return _AuthorityState(
            state.code_fingerprint,
            state.code_consumed,
            tuple(
                client
                for client in state.clients
                if now - client.window_started_at < self._failure_window_seconds
                or client.blocked_until > now
            ),
            tuple(grant for grant in state.grants if grant.expires_at > now),
        )

    def _prune_clients(
        self, clients: dict[str, _ClientAttemptState], now: int
    ) -> dict[str, _ClientAttemptState]:
        pruned = {
            key: value
            for key, value in clients.items()
            if now - value.window_started_at < self._failure_window_seconds
            or value.blocked_until > now
        }
        if len(pruned) > _MAX_TRACKED_CLIENTS:
            raise BootstrapAuthorityUnavailable(
                "bootstrap authorization authority is unavailable"
            ) from None
        return pruned

    def _fingerprint(self, purpose: str, value: str) -> str:
        if purpose not in _DIGEST_PURPOSES:
            raise ValueError("unsupported bootstrap fingerprint purpose")
        message = f"sentinel-bootstrap-v1\0{purpose}\0{value}".encode("utf-8")
        return hmac.new(self._fingerprint_key, message, hashlib.sha256).hexdigest()

    def _now_seconds(self) -> int:
        current = self._clock()
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise BootstrapAuthorityUnavailable(
                "bootstrap authorization authority is unavailable"
            ) from None
        return int(current.astimezone(UTC).timestamp())

    @staticmethod
    def _encode_state(state: _AuthorityState) -> bytes:
        document = {
            "schema_version": _AUTHORITY_SCHEMA_VERSION,
            "code_fingerprint": state.code_fingerprint,
            "code_consumed": state.code_consumed,
            "clients": [
                {
                    "fingerprint": attempt.fingerprint,
                    "window_started_at": attempt.window_started_at,
                    "failures": attempt.failures,
                    "blocked_until": attempt.blocked_until,
                }
                for attempt in state.clients
            ],
            "grants": [
                {
                    "fingerprint": grant.fingerprint,
                    "expires_at": grant.expires_at,
                }
                for grant in state.grants
            ],
        }
        return json.dumps(
            document, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")

    def _decode_state(self, raw: bytes) -> _AuthorityState:
        try:
            document = json.loads(
                raw.decode("utf-8"), object_pairs_hook=_unique_object
            )
            if not isinstance(document, dict) or set(document) != {
                "schema_version",
                "code_fingerprint",
                "code_consumed",
                "clients",
                "grants",
            }:
                raise ValueError("schema")
            if (
                type(document["schema_version"]) is not int
                or document["schema_version"] != _AUTHORITY_SCHEMA_VERSION
                or not isinstance(document["code_consumed"], bool)
                or not isinstance(document["clients"], list)
                or not isinstance(document["grants"], list)
                or not isinstance(document["code_fingerprint"], str)
                or _FINGERPRINT_PATTERN.fullmatch(document["code_fingerprint"])
                is None
                or len(document["clients"]) > _MAX_TRACKED_CLIENTS
                or len(document["grants"]) > _MAX_ACTIVE_GRANTS
            ):
                raise ValueError("schema")
            clients = tuple(
                _decode_client(item) for item in document["clients"]
            )
            grants = tuple(_decode_grant(item) for item in document["grants"])
            if (
                len({item.fingerprint for item in clients}) != len(clients)
                or (grants and not document["code_consumed"])
            ):
                raise ValueError("duplicate client")
            return _AuthorityState(
                document["code_fingerprint"],
                document["code_consumed"],
                clients,
                grants,
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError):
            raise BootstrapAuthorityUnavailable(
                "bootstrap authorization authority is unavailable"
            ) from None


def _decode_client(value: object) -> _ClientAttemptState:
    if not isinstance(value, dict) or set(value) != {
        "fingerprint",
        "window_started_at",
        "failures",
        "blocked_until",
    }:
        raise ValueError("client")
    fingerprint = value["fingerprint"]
    started = value["window_started_at"]
    failures = value["failures"]
    blocked_until = value["blocked_until"]
    if (
        not isinstance(fingerprint, str)
        or _FINGERPRINT_PATTERN.fullmatch(fingerprint) is None
        or type(started) is not int
        or started < 0
        or type(failures) is not int
        or not 0 <= failures <= 20
        or type(blocked_until) is not int
        or blocked_until < 0
    ):
        raise ValueError("client")
    return _ClientAttemptState(fingerprint, started, failures, blocked_until)


def _decode_grant(value: object) -> _GrantState:
    if not isinstance(value, dict) or set(value) != {"fingerprint", "expires_at"}:
        raise ValueError("grant")
    fingerprint = value["fingerprint"]
    expires_at = value["expires_at"]
    if (
        not isinstance(fingerprint, str)
        or _FINGERPRINT_PATTERN.fullmatch(fingerprint) is None
        or type(expires_at) is not int
        or expires_at < 0
    ):
        raise ValueError("grant")
    return _GrantState(fingerprint, expires_at)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _rate_limited(
    blocked_until: int, now: int
) -> BootstrapAuthorizationDecision:
    retry_after_ms = max(1, (blocked_until - now) * 1000)
    return BootstrapAuthorizationDecision(
        BootstrapAuthorizationStatus.RATE_LIMITED,
        retry_after_ms=min(retry_after_ms, 300_000),
    )


__all__ = [
    "BootstrapAuthorizationConfiguration",
    "BootstrapAuthorizationConfigurationError",
    "LocalBootstrapAuthorizationAuthority",
]
