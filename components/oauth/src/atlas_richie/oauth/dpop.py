"""DPoP proof 契约、请求绑定与重放保护（RFC 9449）。
----
DPoP（Demonstrating Proof-of-Possession，RFC 9449）把 access
token 绑定到一对非对称密钥：access token 在 HTTP 出口必须配带
DPoP proof JWS，proof 包含 `htm`（method）/ `htu`（目标 URI，
RFC 9449 规范化形式）/ `iat` / `jti` / 密钥 thumbprint（`jkt`）
等 claim。资源服务器通过 `cnf.jkt` claim 把 access token 与
密钥绑定。

本模块划分三层：

1. **Adapter 协议**：`DpopProofValidator`（验签 + 解析）与
   `DpopProofFactory`（按请求签名）。JOSE 库无关，业务侧注入
   PyJWT / joserfc / authlib 中的任意一个。
2. **重放保护**：`DpopReplayStore` Protocol + 进程内
   `InMemoryDpopReplayStore` 实现。分布式部署需要外部
   adapter（如 Redis SETNX + 过期）。
3. **业务校验器**：`DpopProofVerifier` 串联请求绑定（`htm` /
   `htu`）/ 密钥绑定（`jkt`）/ token 绑定（`ath`）/ 时间窗
   （`iat`）/ nonce / 重放五道检查，全部失败抛
   `OAuthTokenValidationError`。

**原子性**：`_replay_store.reserve(...)` 必须保证"check +
write"原子 —— 分布式场景下靠 Redis SETNX，进程内靠 RLock +
`dict.__setitem__` 单步写入。

English
--------
DPoP proof contracts, request binding, and replay protection
(RFC 9449).

DPoP (Demonstrating Proof-of-Possession, RFC 9449) binds an
access token to a key pair: the access token must travel with a
DPoP proof JWS containing `htm` (method) / `htu` (target URI in
RFC 9449 canonical form) / `iat` / `jti` / key thumbprint (`jkt`).
The resource server pins the access token to the key via the
`cnf.jkt` claim.

This module has three layers:

1. **Adapter protocols:** `DpopProofValidator` (verify signature
   + parse) and `DpopProofFactory` (sign per request). JOSE-
   library-agnostic; business code injects PyJWT / joserfc /
   authlib / ...
2. **Replay protection:** `DpopReplayStore` Protocol + a process-
   local `InMemoryDpopReplayStore` implementation. Distributed
   deployments need an external adapter (e.g. Redis SETNX +
   expiry).
3. **Business verifier:** `DpopProofVerifier` chains five checks
   — request binding (`htm` / `htu`) / key binding (`jkt`) /
   token binding (`ath`) / time window (`iat`) / nonce / replay
   — and raises `OAuthTokenValidationError` on any failure.

**Atomicity:** `_replay_store.reserve(...)` must make
"check + write" atomic — distributed deployments rely on Redis
SETNX; the process-local path relies on the `RLock` plus the
single-step `dict.__setitem__` write.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from .errors import OAuthTokenValidationError

_SHA_256 = hashlib.sha256
_DEFAULT_MAX_PROOF_AGE = timedelta(minutes=5)
_DEFAULT_FUTURE_SKEW = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class DpopProofClaims:
    """中文
    ----
    已通过签名校验的 DPoP claims；JOSE 适配器负责 JWT 解析。

    English
    --------
    Signature-validated DPoP claims; the JOSE adapter owns JWT
    parsing.
    """

    proof_id: str
    issued_at: datetime
    method: str
    target_uri: str
    key_thumbprint: str
    access_token_hash: str | None = None
    nonce: str | None = None

    def __post_init__(self) -> None:
        if not all((self.proof_id, self.method, self.target_uri, self.key_thumbprint)):
            raise ValueError("DPoP claims require jti, htm, htu, and key thumbprint")
        issued_at = self.issued_at if self.issued_at.tzinfo else self.issued_at.replace(tzinfo=UTC)
        object.__setattr__(self, "issued_at", issued_at.astimezone(UTC))
        object.__setattr__(self, "method", self.method.upper())
        object.__setattr__(self, "target_uri", canonical_dpop_uri(self.target_uri))


class DpopProofValidator(Protocol):
    """中文
    ----
    适配器端口：校验紧凑 DPoP JWS，不向上层暴露任何 JOSE 内部
    值。

    English
    --------
    Adapter port that verifies a compact DPoP JWS and exposes no
    JOSE values.
    """

    def validate(self, proof: str) -> DpopProofClaims: ...


class DpopProofFactory(Protocol):
    """中文
    ----
    适配器端口：为每个出站 HTTP 请求签一个独立 proof。

    English
    --------
    Adapter port that signs a distinct proof for each outbound
    HTTP request.
    """

    def create(self, *, method: str, target_uri: str, access_token: str | None = None, nonce: str | None = None) -> str: ...


class DpopReplayStore(Protocol):
    """中文
    ----
    原子地把一个 proof 身份保留到过期；返回 `False` 即重放。

    English
    --------
    Atomically reserve a proof identity until it expires; false
    means replay.
    """

    def reserve(self, key_thumbprint: str, proof_id: str, expires_at: datetime) -> bool: ...


class InMemoryDpopReplayStore:
    """中文
    ----
    进程内重放保护；分布式部署需自行注入外部 adapter。

    English
    --------
    Process-local replay protection; distributed deployments
    supply an adapter.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], datetime] = {}
        self._lock = RLock()

    def reserve(self, key_thumbprint: str, proof_id: str, expires_at: datetime) -> bool:
        now = datetime.now(UTC)
        key = (key_thumbprint, proof_id)
        with self._lock:
            self._entries = {entry: expiry for entry, expiry in self._entries.items() if expiry > now}
            if key in self._entries:
                return False
            self._entries[key] = expires_at
            return True


@dataclass(frozen=True, slots=True)
class DpopValidationPolicy:
    max_proof_age: timedelta = _DEFAULT_MAX_PROOF_AGE
    future_clock_skew: timedelta = _DEFAULT_FUTURE_SKEW

    def __post_init__(self) -> None:
        if self.max_proof_age <= timedelta() or self.future_clock_skew < timedelta():
            raise ValueError("DPoP proof age must be positive and future clock skew non-negative")


class DpopProofVerifier:
    """中文
    ----
    在适配器签名校验之上，叠加 RFC 请求/密钥/token/重放不变量。

    English
    --------
    Applies RFC request/key/token/replay invariants after adapter
    signature validation.
    """

    def __init__(self, validator: DpopProofValidator, replay_store: DpopReplayStore, *, policy: DpopValidationPolicy = DpopValidationPolicy()) -> None:
        self._validator = validator
        self._replay_store = replay_store
        self._policy = policy

    def verify(
        self,
        proof: str,
        *,
        method: str,
        target_uri: str,
        access_token: str,
        expected_key_thumbprint: str,
        nonce: str | None = None,
        now: datetime | None = None,
    ) -> DpopProofClaims:
        claims = self._validator.validate(proof)
        current = now or datetime.now(UTC)
        if claims.method != method.upper() or claims.target_uri != canonical_dpop_uri(target_uri):
            raise OAuthTokenValidationError("DPoP proof is not bound to this HTTP request")
        if claims.key_thumbprint != expected_key_thumbprint:
            raise OAuthTokenValidationError("DPoP proof key is not bound to the access token")
        if claims.access_token_hash != access_token_hash(access_token):
            raise OAuthTokenValidationError("DPoP proof access-token hash is invalid")
        if nonce is not None and claims.nonce != nonce:
            raise OAuthTokenValidationError("DPoP proof nonce is invalid")
        if claims.issued_at > current + self._policy.future_clock_skew or claims.issued_at + self._policy.max_proof_age < current:
            raise OAuthTokenValidationError("DPoP proof is outside the accepted time window")
        expires_at = claims.issued_at + self._policy.max_proof_age
        if not self._replay_store.reserve(claims.key_thumbprint, claims.proof_id, expires_at):
            raise OAuthTokenValidationError("DPoP proof replay detected")
        return claims


def canonical_dpop_uri(value: str) -> str:
    """中文
    ----
    返回 RFC 9449 规范的 scheme/host/port/path 形式的 target URI
    （去掉 query 与 fragment）。

    English
    --------
    Return RFC 9449's scheme/host/port/path target URI form without
    query/fragment.
    """

    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.hostname or parsed.username or parsed.password:
        raise OAuthTokenValidationError("DPoP target URI must be an absolute credential-free URI")
    hostname = parsed.hostname.lower()
    port = parsed.port
    default_port = {"http": 80, "https": 443}.get(parsed.scheme.lower())
    authority = hostname if port in (None, default_port) else f"{hostname}:{port}"
    return urlunsplit((parsed.scheme.lower(), authority, parsed.path or "/", "", ""))


def access_token_hash(access_token: str) -> str:
    if not access_token:
        raise OAuthTokenValidationError("access token is required")
    return base64.urlsafe_b64encode(_SHA_256(access_token.encode("utf-8")).digest()).decode("ascii").rstrip("=")
