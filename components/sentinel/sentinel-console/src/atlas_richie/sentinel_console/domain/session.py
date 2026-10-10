"""Immutable account-session facts exposed to Console use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class AccountRole(StrEnum):
    """Roles supported by the Sentinel Console account model."""

    ADMIN = "admin"
    VIEW = "view"


class SessionCapability(StrEnum):
    """Capabilities represented by the current-session protocol."""

    METRICS_VIEW = "metrics:view"
    RULES_WRITE = "rules:write"


class SessionRevocationResult(StrEnum):
    """Finite outcomes for revoking one browser session."""

    REVOKED = "revoked"
    UNAUTHENTICATED = "unauthenticated"
    CSRF_FAILED = "csrf_failed"


@dataclass(frozen=True, slots=True)
class BrowserCsrfNonce:
    """Opaque anti-CSRF value; suppress it from repr and public session facts."""

    value: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ActiveAccountSession:
    """Minimal active session projection read from the identity authority."""

    account_id: str
    username: str
    role_id: str
    session_epoch: str


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    """Safe identity returned to the browser; never contains credentials."""

    account_id: str
    username: str
    role_id: AccountRole
    capabilities: tuple[SessionCapability, ...]
    session_epoch: str

    @classmethod
    def from_active_session(cls, session: ActiveAccountSession) -> SessionIdentity:
        """Derive the finite capability set from the persisted account role."""
        role = AccountRole(session.role_id)
        capabilities = (
            (SessionCapability.METRICS_VIEW, SessionCapability.RULES_WRITE)
            if role is AccountRole.ADMIN
            else (SessionCapability.METRICS_VIEW,)
        )
        return cls(
            account_id=session.account_id,
            username=session.username,
            role_id=role,
            capabilities=capabilities,
            session_epoch=session.session_epoch,
        )
