"""Serialisation helpers for cache-redis (JSON + bytes).

Java's RedisStringManager uses `JsonUtils.getInstance().deserialize(...)`
for arbitrary objects. Python equivalent: use `json.dumps`/`json.loads`
for non-trivial types, return bytes as-is, return str as-is.

The decision is made on `set` (encode side) based on the runtime type
of the value, and on `get` (decode side) based on the requested
target `clazz` (`type[T]`).
"""

from __future__ import annotations

import json
from typing import Any

from .errors import SerializationError


# Primitives we keep as-is (no JSON wrapping). This mirrors Java's
# handling of "string" values which are stored as plain Redis strings.
_PRIMITIVE_TYPES = (str, bytes, bytearray, int, float, bool)


def encode_value(value: Any) -> bytes | str:
    """Encode `value` for Redis SET.

    - bytes / bytearray / str: pass through (caller's choice).
    - int / float / bool: pass through as their `str(...)` form
      (compact, human-readable, round-trippable via `decode_value(..., str)`).
    - anything else: JSON-serialise with `ensure_ascii=False` for
      non-ASCII payloads.

    Returns bytes (when input is bytes) or str (otherwise). The Redis
    client's `decode_responses` setting controls the wire form; the
    returned value here is the *logical* representation.
    """
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SerializationError(
            f"Cannot encode value of type {type(value).__name__}: {exc}"
        ) from exc


def decode_value(raw: Any, clazz: type) -> Any:
    """Decode a Redis GET result into the requested `clazz`.

    Behaviour matrix:
    - raw is None → return None
    - clazz is bytes / bytearray → return raw bytes (force encode)
    - clazz is str → return raw as str (decode utf-8 if needed)
    - clazz is int → parse str as int
    - clazz is float → parse str as float
    - clazz is bool → "1" → True, else False (loose truthiness)
    - anything else → JSON-load raw

    Raises `SerializationError` on type mismatch.
    """
    if raw is None:
        return None

    # Force bytes when caller asked for bytes/bytearray.
    if clazz in (bytes, bytearray):
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw) if clazz is bytes else bytearray(raw)
        if isinstance(raw, str):
            return raw.encode("utf-8") if clazz is bytes else bytearray(
                raw, "utf-8"
            )
        raise SerializationError(
            f"Expected bytes-like, got {type(raw).__name__}"
        )

    # Coerce raw into str for all other target types.
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw_str = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SerializationError(
                f"Raw bytes are not valid utf-8: {exc}"
            ) from exc
    elif isinstance(raw, str):
        raw_str = raw
    else:
        raise SerializationError(
            f"Unexpected raw type {type(raw).__name__}; expected bytes or str"
        )

    if clazz is str:
        return raw_str
    if clazz is bool:
        return raw_str == "1" or raw_str.lower() == "true"
    if clazz is int:
        try:
            return int(raw_str)
        except ValueError as exc:
            raise SerializationError(
                f"Cannot parse {raw_str!r} as int: {exc}"
            ) from exc
    if clazz is float:
        try:
            return float(raw_str)
        except ValueError as exc:
            raise SerializationError(
                f"Cannot parse {raw_str!r} as float: {exc}"
            ) from exc
    # Fall through: JSON-deserialise into the target class.
    try:
        loaded = json.loads(raw_str)
    except json.JSONDecodeError:
        # Fallback: pass the raw string to the constructor.
        try:
            return clazz(raw_str)
        except Exception as exc:
            raise SerializationError(
                f"Cannot decode raw {raw_str!r} into {clazz.__name__}: {exc}"
            ) from exc
    try:
        return clazz(loaded) if loaded is not None else None
    except Exception as exc:
        raise SerializationError(
            f"Cannot wrap {loaded!r} into {clazz.__name__}: {exc}"
        ) from exc


__all__ = ["encode_value", "decode_value"]
