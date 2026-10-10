"""Shared observation resource bounds mirrored by the Console protocol."""

import math

MAX_OBSERVATION_POINTS = 1_000
MAX_OBSERVATION_WINDOW_MS = 7 * 24 * 60 * 60 * 1_000


def is_finite_json_number(value: object) -> bool:
    """Check JSON-compatible numeric finiteness without overflowing on Python ints."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False
