"""Application use case for the browser's current authenticated identity."""

from __future__ import annotations

import hashlib
import re

from ..domain.session import SessionIdentity
from .errors import SessionAuthorityUnavailable
from .session_ports import CurrentSessionReader

_OPAQUE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


class ReadSession:
    """Resolve a browser cookie without exposing it beyond the HTTP boundary."""

    def __init__(self, session_reader: CurrentSessionReader) -> None:
        self._session_reader = session_reader

    async def execute(self, opaque_token: str | None) -> SessionIdentity | None:
        """Return anonymous for invalid sessions; fail closed on store errors."""
        if (
            opaque_token is None
            or _OPAQUE_TOKEN_PATTERN.fullmatch(opaque_token) is None
        ):
            return None

        session_digest = hashlib.sha256(opaque_token.encode("ascii")).hexdigest()
        active_session = await self._session_reader.read_active_session(session_digest)
        if active_session is None:
            return None

        try:
            return SessionIdentity.from_active_session(active_session)
        except ValueError:
            raise SessionAuthorityUnavailable(
                "session authority returned an invalid account role"
            ) from None
