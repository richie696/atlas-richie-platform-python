"""Application use case for revoking the current browser session."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from ..domain.session import SessionRevocationResult
from .errors import SessionAuthorityUnavailable
from .session_revocation_ports import CurrentSessionRevoker

_OPAQUE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


class RevokeCurrentSession:
    """Validate opaque browser credentials, hash them, then revoke by Port."""

    def __init__(self, session_revoker: CurrentSessionRevoker) -> None:
        self._session_revoker = session_revoker

    async def execute(
        self,
        opaque_session: str | None,
        csrf_token: str | None,
    ) -> SessionRevocationResult:
        """Revoke a session without passing raw cookie/header values to storage."""
        if (
            opaque_session is None
            or _OPAQUE_TOKEN_PATTERN.fullmatch(opaque_session) is None
        ):
            return SessionRevocationResult.UNAUTHENTICATED
        if csrf_token is None or _OPAQUE_TOKEN_PATTERN.fullmatch(csrf_token) is None:
            return SessionRevocationResult.CSRF_FAILED

        session_digest = hashlib.sha256(opaque_session.encode("ascii")).hexdigest()
        csrf_digest = hashlib.sha256(csrf_token.encode("ascii")).hexdigest()
        result = await self._session_revoker.revoke_active_session(
            session_digest,
            csrf_digest,
            datetime.now(UTC),
        )
        if not isinstance(result, SessionRevocationResult):
            raise SessionAuthorityUnavailable(
                "session revocation authority returned an invalid result"
            ) from None
        return result
