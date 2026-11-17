"""Character classification helpers matching the Java implementation.

Java's `Character.isWhitespace` excludes non-breaking spaces, while Python's
`str.isspace()` includes them. HTML-derived text routinely contains U+00A0, so
using `isspace()` here would move chunk boundaries relative to the Java side.
These helpers keep the two implementations aligned.
"""

from __future__ import annotations

import unicodedata

_JAVA_WHITESPACE_CONTROL = frozenset("\t\n\x0b\f\r\x1c\x1d\x1e\x1f")
_NON_BREAKING = frozenset("\u00a0\u2007\u202f")
_PUNCTUATION_CATEGORIES = frozenset({"Pc", "Pd", "Ps", "Pe", "Pi", "Pf", "Po"})

# CJK ideograph blocks assigned to the HAN Unicode script.
_HAN_RANGES = (
    (0x2E80, 0x2E99),
    (0x2E9B, 0x2EF3),
    (0x2F00, 0x2FD5),
    (0x3005, 0x3005),
    (0x3007, 0x3007),
    (0x3021, 0x3029),
    (0x3038, 0x303B),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFA6D),
    (0xFA70, 0xFAD9),
    (0x16FE2, 0x16FE3),
    (0x16FF0, 0x16FF1),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B739),
    (0x2B740, 0x2B81D),
    (0x2B820, 0x2CEA1),
    (0x2CEB0, 0x2EBE0),
    (0x2EBF0, 0x2EE5D),
    (0x2F800, 0x2FA1D),
    (0x30000, 0x3134A),
)


def is_whitespace(character: str) -> bool:
    """Java `Character.isWhitespace` semantics (non-breaking spaces excluded)."""
    if character in _JAVA_WHITESPACE_CONTROL:
        return True
    if character in _NON_BREAKING:
        return False
    return unicodedata.category(character) in {"Zs", "Zl", "Zp"}


def is_blank(text: str) -> bool:
    """Java `String.isBlank()` semantics: empty or all `Character.isWhitespace`.

    Deliberately not `str.strip()`, which also strips non-breaking spaces and
    would reject a chunk consisting solely of U+00A0 that Java accepts.
    """
    return all(is_whitespace(character) for character in text)


def is_han(character: str) -> bool:
    """Whether the character belongs to the HAN Unicode script."""
    code = ord(character)
    return any(low <= code <= high for low, high in _HAN_RANGES)


def is_punctuation(character: str) -> bool:
    """Java `Character.getType` punctuation categories, via Unicode general category."""
    return unicodedata.category(character) in _PUNCTUATION_CATEGORIES


__all__ = ["is_blank", "is_han", "is_punctuation", "is_whitespace"]
