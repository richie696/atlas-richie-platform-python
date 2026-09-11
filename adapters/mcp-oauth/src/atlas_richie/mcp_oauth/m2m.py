"""Explicit target-resource M2M authorization for MCP client exchanges."""

from __future__ import annotations

from dataclasses import dataclass

from atlas_richie.oauth import OAuthTokenManager, ResourceIndicator


@dataclass(frozen=True, slots=True)
class McpM2mTarget:
    """One peer's canonical resource and the least scopes this caller needs."""

    resource: ResourceIndicator
    required_scopes: frozenset[str] = frozenset()


class McpM2mAuthorization:
    """A target-scoped authorization provider consumable by the HTTP MCP adapter."""

    def __init__(self, token_manager: OAuthTokenManager, target: McpM2mTarget, *, require_dpop: bool = True) -> None:
        self._token_manager = token_manager
        self._target = target
        self._require_dpop = require_dpop

    def authorization_for(self) -> str:
        token = self._token_manager.token_for(self._target.resource, self._target.required_scopes)
        if self._require_dpop and token.token_type.casefold() != "dpop":
            raise ValueError("MCP M2M DPoP profile requires a DPoP access token")
        return token.authorization_header()
