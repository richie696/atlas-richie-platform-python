import unittest
from datetime import UTC, datetime, timedelta

from atlas_richie.mcp import MrtRequestStateCodec, MrtRequestStateError


class MrtRequestStateCodecTests(unittest.TestCase):
    def test_state_is_integrity_protected_and_bound_to_context(self) -> None:
        now = datetime(2026, 9, 10, tzinfo=UTC)
        codec = MrtRequestStateCodec(b"a" * 32, ttl=timedelta(minutes=1))
        token = codec.issue(
            resource="https://inventory.example/mcp",
            principal_fingerprint="principal-sha256",
            tenant_id="tenant-a",
            scopes=frozenset({"inventory.read"}),
            registry_revision=7,
            now=now,
        )

        verified = codec.verify(token, now=now)

        self.assertEqual("https://inventory.example/mcp", verified.resource)
        self.assertEqual("principal-sha256", verified.principal_fingerprint)
        self.assertEqual("tenant-a", verified.tenant_id)
        self.assertEqual(frozenset({"inventory.read"}), verified.scopes)
        self.assertEqual(7, verified.registry_revision)

    def test_continuation_state_is_preserved_inside_the_integrity_protected_token(self) -> None:
        now = datetime(2026, 9, 10, tzinfo=UTC)
        codec = MrtRequestStateCodec(b"c" * 32, ttl=timedelta(minutes=1))

        token = codec.issue(
            resource="https://inventory.example/mcp",
            principal_fingerprint="principal-sha256",
            tenant_id="tenant-a",
            scopes=frozenset({"inventory.read"}),
            registry_revision=7,
            continuation_state="application-owned-state",
            now=now,
        )

        self.assertEqual("application-owned-state", codec.verify(token, now=now).continuation_state)

    def test_tampering_and_expiry_fail_closed(self) -> None:
        now = datetime(2026, 9, 10, tzinfo=UTC)
        codec = MrtRequestStateCodec(b"b" * 32, ttl=timedelta(seconds=1))
        token = codec.issue(
            resource="https://inventory.example/mcp",
            principal_fingerprint="principal-sha256",
            tenant_id=None,
            scopes=frozenset(),
            registry_revision=0,
            now=now,
        )

        with self.assertRaises(MrtRequestStateError):
            codec.verify(f"{token}x", now=now)
        with self.assertRaises(MrtRequestStateError):
            codec.verify(token, now=now + timedelta(seconds=2))


if __name__ == "__main__":
    unittest.main()
