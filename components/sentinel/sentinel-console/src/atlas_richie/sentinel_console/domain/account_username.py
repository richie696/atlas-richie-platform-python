"""Validated account login name and its privacy-preserving lookup identity."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field


_MAX_USERNAME_UTF16_UNITS = 200
_ECMASCRIPT_TRIM_CHARACTERS = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


def _trim_username(value: str) -> str:
    """Match ECMAScript ``String.prototype.trim`` without locale dependence."""
    return value.strip(_ECMASCRIPT_TRIM_CHARACTERS)


def _validated_display_username(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("username must be a string")
    try:
        utf16_units = len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError as error:
        raise ValueError("username contains an unpaired surrogate") from error
    if utf16_units > _MAX_USERNAME_UTF16_UNITS:
        raise ValueError("username exceeds 200 UTF-16 code units")
    display_value = _trim_username(value)
    if not display_value:
        raise ValueError("username must not be blank")
    return display_value


def canonicalize_username(value: str) -> str:
    """Validate and return the NFKC/lowercase lookup form used across entrypoints."""
    return _canonicalize_display_username(_validated_display_username(value))


def _canonicalize_display_username(value: str) -> str:
    return unicodedata.normalize("NFKC", value).lower()


@dataclass(frozen=True, slots=True)
class AccountUsername:
    """A display username plus its stable-width canonical lookup digest.

    The display spelling is preserved after trimming. The canonical text is never
    persisted; ``lookup_key`` is SHA-256 hex for the database unique constraint.
    """

    value: str
    lookup_key: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        display_value = _validated_display_username(self.value)
        canonical_value = _canonicalize_display_username(display_value)
        digest = hashlib.sha256(canonical_value.encode("utf-8")).hexdigest()
        object.__setattr__(self, "value", display_value)
        object.__setattr__(self, "lookup_key", digest)
