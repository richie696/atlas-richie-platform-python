"""Number bounds required for lossless JSON interchange with JavaScript clients."""

from __future__ import annotations

import math

MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991


def is_safe_json_number(value: object) -> bool:
    """Accept finite JSON numbers within the interoperable JavaScript range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return (
            math.isfinite(value)
            and -MAX_SAFE_JSON_INTEGER <= value <= MAX_SAFE_JSON_INTEGER
        )
    except OverflowError:
        return False


def is_safe_json_integer(value: object) -> bool:
    """Accept exact integer values representable by JavaScript without rounding."""
    return (
        type(value) is int
        and -MAX_SAFE_JSON_INTEGER <= value <= MAX_SAFE_JSON_INTEGER
    )
