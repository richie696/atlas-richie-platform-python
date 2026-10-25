"""Pure/session-use-case tests; no ASGI or database dependency is needed."""

from __future__ import annotations

import hashlib
import unittest

from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.read_session import ReadSession
from atlas_richie.sentinel_console.domain.session import (
    AccountRole,
    ActiveAccountSession,
    SessionCapability,
    SessionIdentity,
)


_TOKEN = "synthetic-session-token-for-console-read-0001"


class _Reader:
    def __init__(self, result: ActiveAccountSession | None = None) -> None:
        self.result = result
        self.digests: list[str] = []

    async def read_active_session(
        self, session_digest: str
    ) -> ActiveAccountSession | None:
        self.digests.append(session_digest)
        return self.result


class ReadSessionTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_and_malformed_tokens_are_anonymous(self) -> None:
        reader = _Reader()
        use_case = ReadSession(reader)

        self.assertIsNone(await use_case.execute(None))
        self.assertIsNone(await use_case.execute("short-token"))
        self.assertIsNone(await use_case.execute("x" * 257))
        self.assertIsNone(await use_case.execute("bad token with spaces " + "x" * 32))
        self.assertEqual(reader.digests, [])

    async def test_opaque_token_is_hashed_before_storage_boundary(self) -> None:
        reader = _Reader(
            ActiveAccountSession("account-1", "Admin", AccountRole.ADMIN, "epoch-1")
        )
        identity = await ReadSession(reader).execute(_TOKEN)

        self.assertIsNotNone(identity)
        self.assertEqual(
            reader.digests, [hashlib.sha256(_TOKEN.encode("ascii")).hexdigest()]
        )
        self.assertNotIn(_TOKEN, reader.digests[0])

    async def test_role_owns_finite_session_capabilities(self) -> None:
        admin = SessionIdentity.from_active_session(
            ActiveAccountSession("account-1", "Admin", "admin", "epoch-1")
        )
        viewer = SessionIdentity.from_active_session(
            ActiveAccountSession("account-2", "Viewer", "view", "epoch-2")
        )

        self.assertEqual(
            admin.capabilities,
            (SessionCapability.METRICS_VIEW, SessionCapability.RULES_WRITE),
        )
        self.assertEqual(viewer.capabilities, (SessionCapability.METRICS_VIEW,))

    async def test_unknown_persisted_role_fails_closed(self) -> None:
        reader = _Reader(
            ActiveAccountSession("account-1", "Unknown", "owner", "epoch-1")
        )
        with self.assertRaises(SessionAuthorityUnavailable):
            await ReadSession(reader).execute(_TOKEN)
