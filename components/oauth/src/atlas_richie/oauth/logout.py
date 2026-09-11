"""RP-Initiated Logout 1.0 end-session 请求构造。
----
OpenID Connect RP-Initiated Logout 1.0 §2.1 的端会话 URL 构造器。
Builder 累积可选参数，终端的 `build()` 返回一个 `LogoutRequest`
不可变值对象，其 `url()` 方法生成带正确 percent-encoding 的 end-session URL。

**为什么是 Builder 而不是 dataclass 直传**：post_logout_redirect_uri /
state / ui_locales 之间是累加式关系（每个 setter 都返回一份"克隆 +
新参数"的实例），业务代码在交互式场景下逐步构造；用 dataclass
直接传参会让调用方承担"每次都要把所有字段重新组合"的负担。Builder
返回"新副本"的不可变语义也避免了共享可变状态。

**URL 编码策略**：合并 end_session_endpoint 已有 query 与新加的
四个参数，统一用 `urllib.parse.urlencode` 做 percent-encoding，
保留 `keep_blank_values`，避免 IdP 行为差异。

English
--------
RP-Initiated Logout 1.0 end-session request construction.

Implements the end-session URL builder from OpenID Connect
RP-Initiated Logout 1.0 §2.1. The builder accumulates optional
parameters; the terminal `build()` returns a frozen `LogoutRequest`
value object whose `url()` method produces the final end-session URL
with correct percent-encoding.

**Why a Builder, not a plain dataclass:** `post_logout_redirect_uri`,
`state`, and `ui_locales` are additive (each setter returns a
"clone + new parameter" copy), which fits the interactive
authorization-code flow where the RP builds the request step by
step. A plain dataclass would force the caller to re-assemble all
fields on every change. The builder's "new copy per setter"
immutability also prevents shared mutable state.

**URL encoding strategy:** the existing query on
`end_session_endpoint` is merged with the four appended parameters and
percent-encoded via `urllib.parse.urlencode` with
`keep_blank_values=True`, so the IdP sees a single canonical query
string regardless of the endpoint's prior contents.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .errors import OAuthConfigurationError


@dataclass(frozen=True, slots=True)
class LogoutRequest:
    """中文
    ----
    已构造的 RP-Initiated Logout 1.0 end-session 请求值对象。

    Attributes:
        end_session_endpoint: IdP 的 `end_session_endpoint` URL。
        id_token_hint: 作为 hint 转发给 IdP 的 ID Token；必填。
        post_logout_redirect_uri: 可选，登出完成后 IdP 把用户
            带回的 redirect 目标。
        state: 可选的不透明值，用于 CSRF 防御（RP-Initiated
            Logout 1.0 §2.1 建议回显）。
        ui_locales: 可选的 BCP47 语言标签，影响 IdP 端 UI。

    English
    --------
    A constructed RP-Initiated Logout 1.0 end-session request.

    Attributes:
        end_session_endpoint: The IdP's `end_session_endpoint` URL.
        id_token_hint: The ID Token to forward as a hint; required.
        post_logout_redirect_uri: Optional redirect target the IdP
            returns the user to after logout.
        state: Optional opaque value for CSRF defense (RP-Initiated
            Logout 1.0 §2.1 recommends echoing it back).
        ui_locales: Optional BCP47 language tag for the IdP's UI.
    """

    end_session_endpoint: str
    id_token_hint: str
    post_logout_redirect_uri: str | None = None
    state: str | None = None
    ui_locales: str | None = None

    def __post_init__(self) -> None:
        if not self.end_session_endpoint or not self.end_session_endpoint.strip():
            raise OAuthConfigurationError("end_session_endpoint is required")
        if not self.id_token_hint or not self.id_token_hint.strip():
            raise OAuthConfigurationError("id_token_hint is required")
        if self.post_logout_redirect_uri is not None and not self.post_logout_redirect_uri.strip():
            raise OAuthConfigurationError("post_logout_redirect_uri must be non-blank when present")
        if self.state is not None and not self.state.strip():
            raise OAuthConfigurationError("state must be non-blank when present")
        if self.ui_locales is not None and not self.ui_locales.strip():
            raise OAuthConfigurationError("ui_locales must be non-blank when present")

    def url(self) -> str:
        """中文
        ----
        返回合并已有 query、附上四个 RP 参数后的完整 end-session
        URL，参数做 percent-encoding。

        English
        --------
        Return the fully-encoded end-session URL.
        """
        parsed = urlsplit(self.end_session_endpoint)
        existing = parse_qsl(parsed.query, keep_blank_values=True)
        added: list[tuple[str, str]] = [("id_token_hint", self.id_token_hint)]
        if self.post_logout_redirect_uri is not None:
            added.append(("post_logout_redirect_uri", self.post_logout_redirect_uri))
        if self.state is not None:
            added.append(("state", self.state))
        if self.ui_locales is not None:
            added.append(("ui_locales", self.ui_locales))
        merged = existing + added
        encoded = urlencode(merged)
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, encoded, parsed.fragment)
        )


class _RpInitiatedLogoutBuilder:
    """中文
    ----
    内部可变 builder；每个 setter 返回新克隆实例，保持调用方无
    副作用。

    English
    --------
    Internal mutable builder; new instances are returned from each
    setter.
    """

    def __init__(self, end_session_endpoint: str) -> None:
        self._endpoint = end_session_endpoint
        self._id_token_hint: str | None = None
        self._post_logout_redirect_uri: str | None = None
        self._state: str | None = None
        self._ui_locales: str | None = None

    def _copy(self) -> "_RpInitiatedLogoutBuilder":
        clone = _RpInitiatedLogoutBuilder(self._endpoint)
        clone._id_token_hint = self._id_token_hint
        clone._post_logout_redirect_uri = self._post_logout_redirect_uri
        clone._state = self._state
        clone._ui_locales = self._ui_locales
        return clone

    def id_token_hint(self, value: str) -> "_RpInitiatedLogoutBuilder":
        next = self._copy()
        next._id_token_hint = value
        return next

    def post_logout_redirect_uri(self, value: str) -> "_RpInitiatedLogoutBuilder":
        next = self._copy()
        next._post_logout_redirect_uri = value
        return next

    def state(self, value: str) -> "_RpInitiatedLogoutBuilder":
        next = self._copy()
        next._state = value
        return next

    def ui_locales(self, value: str) -> "_RpInitiatedLogoutBuilder":
        next = self._copy()
        next._ui_locales = value
        return next

    def build(self) -> LogoutRequest:
        return LogoutRequest(
            end_session_endpoint=self._endpoint,
            id_token_hint=self._id_token_hint or "",
            post_logout_redirect_uri=self._post_logout_redirect_uri,
            state=self._state,
            ui_locales=self._ui_locales,
        )


class RpInitiatedLogout:
    """中文
    ----
    RP-Initiated Logout 1.0 end-session 请求的 builder 入口。

    English
    --------
    Builder entry point for RP-Initiated Logout 1.0 end-session
    requests.
    """

    @staticmethod
    def builder(end_session_endpoint: str) -> _RpInitiatedLogoutBuilder:
        if not end_session_endpoint or not end_session_endpoint.strip():
            raise OAuthConfigurationError("end_session_endpoint is required")
        return _RpInitiatedLogoutBuilder(end_session_endpoint)


__all__ = ["LogoutRequest", "RpInitiatedLogout"]
