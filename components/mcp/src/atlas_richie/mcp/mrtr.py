"""多轮工具结果（MRTR）的完整性保护状态。

中文
----
MRTR（Multi-Round Tool Result）是把"上下文信息"在多轮调用间**无状态**
传递的协议：用 HMAC-SHA256 签名的 `base64url(payload).base64url(sig)`
形式，`McpServer` 在返回 `InputRequired` 时附上 `requestState`，客户端
回传时由 `MrtStateBinding.resume` 校验并提取 `continuation_state`。

主要组件：

- `MrtRequestState`：服务端持有的、与 `MrtStateBinding` 资源绑定的
  不可变事实（resource / principal_fingerprint / tenant_id / scopes /
  registry_revision / expires_at / continuation_state）。
- `MrtRequestStateCodec`：HMAC 签名 / 校验；`signing_secret` 至少 32 字节；
  默认 TTL 5 分钟。
- `MrtStateBinding`：把签名状态与当前 `ToolContext` + 注册表 revision
  绑定；`issue` / `resume` 入口。
- `PrincipalFingerprint`：应用持有的非秘密稳定身份指纹。
- `MrtRequestStateError`：状态格式错误 / 过期 / 完整性校验失败。

**HMAC 保护完整性，不加密负载字段** —— 调用方**不应**把秘密 / 敏感
continuation 数据放进 token。

English
--------
Integrity-protected state for multi-round tool results (MRTR).

MRTR (Multi-Round Tool Result) is the protocol for passing
"continuation state" **statelessly** between rounds: an HMAC-SHA256
signed `base64url(payload).base64url(sig)` string. The server attaches
the `requestState` to its `InputRequired` response; the client echoes
it back and `MrtStateBinding.resume` validates it and extracts the
`continuation_state`.

Components:

- `MrtRequestState`: the immutable server-side facts (resource,
  principal_fingerprint, tenant_id, scopes, registry_revision,
  expires_at, continuation_state) bound to a binding's resource.
- `MrtRequestStateCodec`: HMAC sign / verify; `signing_secret` must be
  at least 32 bytes; default TTL 5 minutes.
- `MrtStateBinding`: binds signed state to the current `ToolContext` +
  registry revision; `issue` / `resume` entry points.
- `PrincipalFingerprint`: an application-owned, non-secret, stable
  identity fingerprint.
- `MrtRequestStateError`: malformed / expired / integrity-failed
  state.

**HMAC protects integrity, not confidentiality** — callers must **not**
place secrets or sensitive continuation data in the token.

Mirrors `cn.richie696.component.mcp.protocol.mrtr.McpRequestState` +
`McpRequestStateCodec` (Java — same wire format, slightly different
JSON envelope).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .models import ToolContext


_STATE_VERSION = 1
_MINIMUM_SECRET_BYTES = 32
_DEFAULT_STATE_TTL = timedelta(minutes=5)
_HMAC_DIGEST = hashlib.sha256
_TOKEN_SEPARATOR = "."


class MrtRequestStateError(ValueError):
    """中文
    ----
    多轮状态值格式错误、过期或完整性校验失败。

    English
    --------
    A multi-round state value is malformed, expired, or fails
    integrity verification.
    """


@dataclass(frozen=True, slots=True)
class MrtRequestState:
    """中文
    ----
    服务端持有、与 `MrtStateBinding` 资源绑定的事实集合；构造时 `resource` /
    `principal_fingerprint` / `registry_revision` 必填校验；naive datetime
    会被强制视为 UTC。

    English
    --------
    The server-owned facts bound to an integrity-protected multi-round
    request state. `resource` / `principal_fingerprint` /
    `registry_revision` are required at construction; naive datetimes
    are coerced to UTC.
    """

    resource: str
    principal_fingerprint: str
    tenant_id: str | None
    scopes: frozenset[str]
    registry_revision: int
    expires_at: datetime
    continuation_state: str | None = None

    def __post_init__(self) -> None:
        if not self.resource or not self.principal_fingerprint or self.registry_revision < 0:
            raise ValueError("MRTR state requires resource, principal fingerprint, and a non-negative revision")
        if any(not scope for scope in self.scopes):
            raise ValueError("MRTR scopes must be non-blank")
        if self.continuation_state is not None and not isinstance(self.continuation_state, str):
            raise ValueError("MRTR continuation state must be a string when present")
        expiry = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=UTC)
        object.__setattr__(self, "expires_at", expiry.astimezone(UTC))


class MrtRequestStateCodec:
    """中文
    ----
    签名 / 校验无状态 MRTR token —— `core` 不持有 session。

    **HMAC 保护完整性，不加密负载**；调用方**不应**把秘密 / 敏感
    continuation 数据放进 token。

    Args:
        signing_secret: HMAC 密钥，至少 32 字节。
        ttl: token 默认过期时间（默认 5 分钟），必须为正。

    English
    --------
    Signs and verifies stateless MRTR state without storing sessions
    in the MCP core.

    **HMAC protects integrity, not confidentiality** — callers must
    **not** place secrets or sensitive continuation data in the
    token.

    Args:
        signing_secret: HMAC secret; at least 32 bytes.
        ttl: default token TTL (default 5 minutes); must be positive.
    """

    def __init__(self, signing_secret: bytes, *, ttl: timedelta = _DEFAULT_STATE_TTL) -> None:
        if not isinstance(signing_secret, bytes) or len(signing_secret) < _MINIMUM_SECRET_BYTES:
            raise ValueError(f"MRTR signing_secret must contain at least {_MINIMUM_SECRET_BYTES} bytes")
        if ttl <= timedelta():
            raise ValueError("MRTR ttl must be positive")
        self._signing_secret = signing_secret
        self._ttl = ttl

    def issue(
        self,
        *,
        resource: str,
        principal_fingerprint: str,
        tenant_id: str | None,
        scopes: frozenset[str],
        registry_revision: int,
        continuation_state: str | None = None,
        now: datetime | None = None,
    ) -> str:
        """中文
        ----
        颁发一个签名 token：构造状态 → 编码 JSON 负载 → HMAC-SHA256 →
        `base64url(payload).base64url(sig)`。

        Args:
            resource: 绑定的资源标识（通常与 `MrtStateBinding.resource` 一致）。
            principal_fingerprint: 应用持有的非秘密稳定身份指纹。
            tenant_id: 租户 ID（可空）。
            scopes: 当前 principal 已授权的 scope 集合。
            registry_revision: 当前注册表 revision，写入 token，resume 时必须匹配。
            continuation_state: 不透明的 continuation 数据。
            now: 测试可注入的"当前时间"。

        Returns:
            `base64url(payload).base64url(signature)` 形式的 token 字符串。

        English
        --------
        Issue a signed token: build state → encode JSON payload →
        HMAC-SHA256 → `base64url(payload).base64url(sig)`.

        Args:
            resource: the bound resource identifier (typically matching
                `MrtStateBinding.resource`).
            principal_fingerprint: application-owned, non-secret, stable
                identity fingerprint.
            tenant_id: tenant ID (nullable).
            scopes: the principal's currently granted scopes.
            registry_revision: current registry revision; embedded in
                the token and required to match on `resume`.
            continuation_state: opaque continuation data.
            now: optional injected "now" for testing.

        Returns:
            the `base64url(payload).base64url(signature)` token string.
        """
        issued_at = _utc_now(now)
        state = MrtRequestState(
            resource=resource,
            principal_fingerprint=principal_fingerprint,
            tenant_id=tenant_id,
            scopes=frozenset(scopes),
            registry_revision=registry_revision,
            expires_at=issued_at + self._ttl,
            continuation_state=continuation_state,
        )
        payload = _encode_payload(state)
        signature = hmac.new(self._signing_secret, payload, _HMAC_DIGEST).digest()
        return f"{_base64url(payload)}{_TOKEN_SEPARATOR}{_base64url(signature)}"

    def verify(self, token: str, *, now: datetime | None = None) -> MrtRequestState:
        """中文
        ----
        校验 token 的格式、HMAC 签名和过期时间，并解码为 `MrtRequestState`。

        Args:
            token: 客户端回传的 `requestState`。
            now: 测试可注入的"当前时间"。

        Returns:
            解码后的 `MrtRequestState`。

        Raises:
            MrtRequestStateError: token 非字符串 / 格式错误 / base64url 解码失败
                / 签名不匹配 / 已过期。

        English
        --------
        Validate the token's format, HMAC signature, and expiry, then
        decode it as `MrtRequestState`.

        Args:
            token: the client-echoed `requestState`.
            now: optional injected "now" for testing.

        Returns:
            the decoded `MrtRequestState`.

        Raises:
            MrtRequestStateError: the token is not a string, is
                malformed, fails base64url decode, fails HMAC
                verification, or is expired.
        """
        if not isinstance(token, str):
            raise MrtRequestStateError("MRTR request state must be a string")
        encoded_payload, separator, encoded_signature = token.partition(_TOKEN_SEPARATOR)
        if not separator or not encoded_payload or not encoded_signature:
            raise MrtRequestStateError("MRTR request state is malformed")
        try:
            payload = _base64url_decode(encoded_payload)
            signature = _base64url_decode(encoded_signature)
        except ValueError as error:
            raise MrtRequestStateError("MRTR request state is malformed") from error
        expected = hmac.new(self._signing_secret, payload, _HMAC_DIGEST).digest()
        if not hmac.compare_digest(signature, expected):
            raise MrtRequestStateError("MRTR request state integrity verification failed")
        state = _decode_payload(payload)
        if state.expires_at <= _utc_now(now):
            raise MrtRequestStateError("MRTR request state has expired")
        return state


class PrincipalFingerprint(Protocol):
    """中文
    ----
    应用持有的非秘密稳定身份指纹，用于把 `ToolContext` 映射到 MRTR token
    中嵌入的指纹字段。

    English
    --------
    Application-owned, non-secret, stable identity fingerprint used
    to map a `ToolContext` to the fingerprint embedded in the MRTR
    token.
    """

    def __call__(self, context: "ToolContext") -> str: ...


class MrtStateBinding:
    """中文
    ----
    把签名 MRTR 状态绑定到当前 `ToolContext` + 注册表快照：

    - `issue(context, ...)`：根据当前 context / registry_revision 颁发 token。
    - `resume(token, context, ...)`：校验 token 的 resource / principal /
      tenant / scopes / registry_revision 与当前 context 一致，返回
      `continuation_state`（不透明，由调用方解读）。

    Args:
        codec: 共享的 `MrtRequestStateCodec`。
        resource: 绑定的资源标识（不可空白），写入并校验。
        principal_fingerprint: 应用持有的非秘密稳定身份指纹。

    English
    --------
    Binds signed MRTR state to the current `ToolContext` and registry
    snapshot.

    - `issue(context, ...)`: issue a token from the current context /
      registry_revision.
    - `resume(token, context, ...)`: verify the token's resource /
      principal / tenant / scopes / registry_revision all match the
      current context; return the opaque `continuation_state`.

    Args:
        codec: shared `MrtRequestStateCodec`.
        resource: bound resource identifier (must be non-blank);
            written into and checked against tokens.
        principal_fingerprint: application-owned, non-secret, stable
            identity fingerprint.
    """

    def __init__(self, codec: MrtRequestStateCodec, *, resource: str, principal_fingerprint: PrincipalFingerprint) -> None:
        if not resource.strip():
            raise ValueError("MRTR resource is required")
        self._codec = codec
        self._resource = resource
        self._principal_fingerprint = principal_fingerprint

    def issue(self, context: "ToolContext", *, registry_revision: int, continuation_state: str | None) -> str:
        """中文
        ----
        为当前 context / registry_revision 颁发签名 token。

        Args:
            context: 当前调用的 `ToolContext`。
            registry_revision: 当前注册表 revision。
            continuation_state: 不透明的 continuation 数据。

        Returns:
            `MrtRequestStateCodec.issue` 返回的 token 字符串。

        English
        --------
        Issue a signed token for the current context / registry
        revision.

        Args:
            context: the current `ToolContext`.
            registry_revision: the current registry revision.
            continuation_state: opaque continuation data.

        Returns:
            the token string returned by `MrtRequestStateCodec.issue`.
        """
        return self._codec.issue(
            resource=self._resource,
            principal_fingerprint=self._fingerprint(context),
            tenant_id=context.tenant_id,
            scopes=context.granted_scopes,
            registry_revision=registry_revision,
            continuation_state=continuation_state,
        )

    def resume(self, token: str, context: "ToolContext", *, registry_revision: int) -> str | None:
        """中文
        ----
        校验 token 的 `resource` / `principal_fingerprint` / `tenant_id` /
        `scopes` / `registry_revision` 与当前 context 一致；返回解出的
        `continuation_state`（可为 `None`）。

        Args:
            token: 客户端回传的 `requestState`。
            context: 当前调用的 `ToolContext`。
            registry_revision: 当前注册表 revision。

        Returns:
            token 中嵌入的 `continuation_state`（可能为 `None`）。

        Raises:
            MrtRequestStateError: 任一字段不匹配，或 token 自身格式 /
                签名 / 过期失败。

        English
        --------
        Verify the token's `resource` / `principal_fingerprint` /
        `tenant_id` / `scopes` / `registry_revision` all match the
        current context; return the decoded `continuation_state`
        (possibly `None`).

        Args:
            token: the client-echoed `requestState`.
            context: the current `ToolContext`.
            registry_revision: the current registry revision.

        Returns:
            the `continuation_state` embedded in the token (may be
            `None`).

        Raises:
            MrtRequestStateError: any field mismatches, or the token
                itself is malformed / fails HMAC / is expired.
        """
        state = self._codec.verify(token)
        if state.resource != self._resource:
            raise MrtRequestStateError("MRTR request state resource does not match")
        if not hmac.compare_digest(state.principal_fingerprint, self._fingerprint(context)):
            raise MrtRequestStateError("MRTR request state principal does not match")
        if state.tenant_id != context.tenant_id:
            raise MrtRequestStateError("MRTR request state tenant does not match")
        if state.scopes != context.granted_scopes:
            raise MrtRequestStateError("MRTR request state scopes do not match")
        if state.registry_revision != registry_revision:
            raise MrtRequestStateError("MRTR request state registry revision is stale")
        return state.continuation_state

    def _fingerprint(self, context: "ToolContext") -> str:
        value = self._principal_fingerprint(context)
        if not isinstance(value, str) or not value:
            raise ValueError("MRTR principal fingerprint must be a non-empty string")
        return value


def _encode_payload(state: MrtRequestState) -> bytes:
    payload = {
        "v": _STATE_VERSION,
        "resource": state.resource,
        "principal": state.principal_fingerprint,
        "tenant": state.tenant_id,
        "scopes": sorted(state.scopes),
        "revision": state.registry_revision,
        "expiresAt": int(state.expires_at.timestamp()),
        "continuationState": state.continuation_state,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decode_payload(payload: bytes) -> MrtRequestState:
    try:
        value: Any = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MrtRequestStateError("MRTR request state payload is invalid") from error
    if not isinstance(value, dict) or value.get("v") != _STATE_VERSION:
        raise MrtRequestStateError("MRTR request state version is unsupported")
    scopes = value.get("scopes")
    expires_at = value.get("expiresAt")
    if (
        not isinstance(value.get("resource"), str)
        or not isinstance(value.get("principal"), str)
        or value.get("tenant") is not None and not isinstance(value.get("tenant"), str)
        or not isinstance(scopes, list)
        or any(not isinstance(scope, str) or not scope for scope in scopes)
        or isinstance(value.get("revision"), bool)
        or not isinstance(value.get("revision"), int)
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or value.get("continuationState") is not None and not isinstance(value.get("continuationState"), str)
    ):
        raise MrtRequestStateError("MRTR request state payload has an invalid shape")
    return MrtRequestState(
        resource=value["resource"],
        principal_fingerprint=value["principal"],
        tenant_id=value["tenant"],
        scopes=frozenset(scopes),
        registry_revision=value["revision"],
        expires_at=datetime.fromtimestamp(expires_at, UTC),
        continuation_state=value.get("continuationState"),
    )


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except Exception as error:
        raise ValueError("invalid base64url") from error


def _utc_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    return current if current.tzinfo else current.replace(tzinfo=UTC)
