"""RFC 7636 PKCE S256 generation and validation."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe

from .errors import OAuthConfigurationError


@dataclass(frozen=True, slots=True)
class PkcePair:
    """A verifier and its only accepted (`S256`) challenge."""

    verifier: str
    challenge: str
    method: str = "S256"

    @classmethod
    def generate(cls) -> "PkcePair":
        verifier = token_urlsafe(32)
        return cls(verifier=verifier, challenge=PkceS256.challenge(verifier))


class PkceS256:
    """Stateless PKCE helper that refuses the obsolete plain method."""

    @staticmethod
    def challenge(verifier: str) -> str:
        if not verifier or not verifier.isascii() or not 43 <= len(verifier) <= 128:
            raise OAuthConfigurationError("PKCE verifier must be 43-128 ASCII characters")
        return urlsafe_b64encode(sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")

    @staticmethod
    def verify(*, verifier: str, expected_challenge: str, method: str = "S256") -> bool:
        if method != "S256" or not expected_challenge:
            return False
        return compare_digest(PkceS256.challenge(verifier), expected_challenge)
