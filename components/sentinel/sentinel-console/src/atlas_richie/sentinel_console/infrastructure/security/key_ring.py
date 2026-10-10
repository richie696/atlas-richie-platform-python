"""Strict parsing primitives for deployment-injected base64 key rings."""

from __future__ import annotations

import base64
import binascii
import re

KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def parse_base64_key_ring(
    encoded_ring: str,
    *,
    invalid_message: str,
    minimum_key_bytes: int = 0,
    short_key_message: str | None = None,
) -> dict[str, bytes]:
    """Parse unique key-id/base64 pairs without exposing key material."""
    if not isinstance(encoded_ring, str) or not encoded_ring:
        raise ValueError(invalid_message)
    keys: dict[str, bytes] = {}
    for entry in encoded_ring.split(";"):
        key_id, separator, encoded_key = entry.partition("=")
        if (
            not separator
            or KEY_ID_PATTERN.fullmatch(key_id) is None
            or not encoded_key
            or key_id in keys
        ):
            raise ValueError(invalid_message)
        try:
            key = base64.b64decode(encoded_key, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(invalid_message) from None
        if len(key) < minimum_key_bytes:
            raise ValueError(short_key_message or invalid_message)
        keys[key_id] = key
    return keys
