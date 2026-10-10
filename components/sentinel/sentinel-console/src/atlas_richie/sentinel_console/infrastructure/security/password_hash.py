"""Argon2id password hashing with bounded, explicit parameters."""

from __future__ import annotations

from secrets import token_urlsafe

from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class PasswordHashService:
    """Create and verify one-way password hashes; raw values are never retained."""

    def __init__(self) -> None:
        self._hasher = Argon2PasswordHasher(
            time_cost=2,
            memory_cost=19_456,
            parallelism=1,
            hash_len=32,
            salt_len=16,
        )
        self._dummy_hash = self._hasher.hash(token_urlsafe(32))

    def hash_password(self, password: str) -> str:
        """Return an encoded Argon2id hash for a validated password."""
        if not isinstance(password, str) or not password:
            raise ValueError("password must be a non-empty string")
        return self._hasher.hash(password)

    def verify_password(self, encoded_hash: str, candidate: str) -> bool:
        """Verify a candidate without exposing hash-parser details to callers."""
        if not isinstance(encoded_hash, str) or not isinstance(candidate, str):
            return False
        try:
            return self._hasher.verify(encoded_hash, candidate)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False

    def verify_account_password(self, encoded_hash: str | None, candidate: str) -> bool:
        """Verify an account hash and use the dummy hash for malformed records."""
        if not isinstance(encoded_hash, str) or not isinstance(candidate, str):
            self.verify_unknown_account(candidate if isinstance(candidate, str) else "")
            return False
        try:
            return self._hasher.verify(encoded_hash, candidate)
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError):
            self.verify_unknown_account(candidate)
            return False

    def verify_unknown_account(self, candidate: str) -> None:
        """Spend one Argon2 verification for unknown or malformed account hashes."""
        self.verify_password(self._dummy_hash, candidate)
