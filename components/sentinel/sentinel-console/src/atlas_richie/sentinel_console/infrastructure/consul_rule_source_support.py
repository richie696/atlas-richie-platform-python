"""Shared Consul KV key and revision validation primitives."""

from __future__ import annotations

import aiohttp
import base64
import binascii
import json
import re
from urllib.parse import quote

MAX_CONSUL_KEY_UTF16_UNITS = 512
MAX_CONSUL_INDEX = (1 << 64) - 1
CONSUL_INDEX_PATTERN = re.compile(r"^[0-9]+$")
CONSUL_TRANSPORT_ERRORS = (aiohttp.ClientError, OSError, TimeoutError)


def is_valid_consul_key(key: str) -> bool:
    """Return whether a key is a safe, non-empty Consul KV path."""
    if (
        not isinstance(key, str)
        or not key
        or len(key.encode("utf-16-le")) // 2 > MAX_CONSUL_KEY_UTF16_UNITS
        or key.startswith("/")
        or key.endswith("/")
        or "\\" in key
        or "?" in key
        or "#" in key
    ):
        return False
    return all(segment not in {"", ".", ".."} for segment in key.split("/"))


def encode_consul_key(key: str) -> str:
    """Percent-encode each key segment while preserving Consul separators."""
    return "/".join(quote(segment, safe="") for segment in key.split("/"))


def datacenter_params(datacenter: str) -> dict[str, str]:
    """Return the optional Consul datacenter query parameter."""
    return {"dc": datacenter} if datacenter else {}


def decode_consul_exact_key_response(body: bytes, key: str) -> tuple[bytes, int]:
    """Decode one exact Consul KV response record into bytes and ModifyIndex.

    The caller owns HTTP status classification. This function accepts only the
    exact key's single record, and it deliberately exposes no parsed user data
    through an exception message.
    """
    if not is_valid_consul_key(key):
        raise ValueError("Consul KV key is invalid")
    try:
        records = json.loads(body)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Consul KV response is invalid") from None
    if not isinstance(records, list) or len(records) != 1:
        raise ValueError("Consul KV response is invalid")
    record = records[0]
    if not isinstance(record, dict) or record.get("Key") != key:
        raise ValueError("Consul KV response is invalid")
    encoded_value = record.get("Value")
    modify_index = record.get("ModifyIndex")
    if (
        not isinstance(encoded_value, str)
        or type(modify_index) is not int
        or not 0 < modify_index <= MAX_CONSUL_INDEX
    ):
        raise ValueError("Consul KV metadata is invalid")
    try:
        value = base64.b64decode(encoded_value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Consul KV value encoding is invalid") from None
    return value, modify_index
