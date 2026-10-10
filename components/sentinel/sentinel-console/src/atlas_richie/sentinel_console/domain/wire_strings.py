"""Pure string rules shared by Console wire and domain boundaries."""

from __future__ import annotations

_WIRE_BLANK_CHARACTERS = frozenset(
    "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


def has_non_blank_wire_content(value: str) -> bool:
    """Apply the Console's cross-runtime blank-character policy."""
    return any(character not in _WIRE_BLANK_CHARACTERS for character in value)


def has_no_wire_boundary_blank(value: str) -> bool:
    """Reject strings whose first or last character is wire-blank."""
    return bool(value) and (
        value[0] not in _WIRE_BLANK_CHARACTERS
        and value[-1] not in _WIRE_BLANK_CHARACTERS
    )


def has_unicode_scalar_values(value: str) -> bool:
    """Reject Python strings containing UTF-16 surrogate code points."""
    return not any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def utf16_length(value: str) -> int:
    """Count UTF-16 code units without raising on malformed surrogate input."""
    return sum(2 if ord(character) > 0xFFFF else 1 for character in value)


def is_bounded_wire_text(value: object, maximum: int) -> bool:
    """Validate scalar-only bounded text using JavaScript UTF-16 units."""
    return (
        isinstance(value, str)
        and type(maximum) is int
        and maximum >= 0
        and has_unicode_scalar_values(value)
        and utf16_length(value) <= maximum
    )


def is_bounded_wire_identifier(value: object, maximum: int) -> bool:
    """Validate a nonblank, scalar-only identifier with a UTF-16 wire bound."""
    return (
        is_bounded_wire_text(value, maximum)
        and isinstance(value, str)
        and has_non_blank_wire_content(value)
    )
