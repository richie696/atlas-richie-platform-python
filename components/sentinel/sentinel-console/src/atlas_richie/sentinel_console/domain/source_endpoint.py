"""Canonical URL syntax rules for registered configuration sources."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from .wire_strings import is_bounded_wire_text

MAX_SOURCE_ENDPOINT_UNITS = 2048
_DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def is_safe_source_endpoint(value: object) -> bool:
    """Accept bounded HTTP(S) URLs without credentials, query, or fragment."""
    if (
        not isinstance(value, str)
        or not is_bounded_wire_text(value, MAX_SOURCE_ENDPOINT_UNITS)
        or not value
        or value != value.strip()
        or any(character.isspace() or character == "\ufeff" for character in value)
        or "\\" in value
        or "?" in value
        or "#" in value
    ):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    return _is_supported_hostname(parsed.hostname, parsed.netloc)


def _is_supported_hostname(hostname: str, authority: str) -> bool:
    if authority.startswith("["):
        if "%" in hostname:
            return False
        try:
            ipaddress.IPv6Address(hostname)
        except ValueError:
            return False
        return True
    if any(character in hostname for character in "%[]:"):
        return False

    candidate = hostname[:-1] if hostname.endswith(".") else hostname
    if not candidate:
        return False
    if _ends_in_url_ipv4_number(candidate):
        try:
            address = ipaddress.IPv4Address(candidate)
        except ValueError:
            return False
        return str(address) == hostname

    try:
        ascii_hostname = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return False
    labels = ascii_hostname.split(".")
    return len(ascii_hostname) <= 253 and all(
        _DNS_LABEL_PATTERN.fullmatch(label) is not None for label in labels
    )


def _ends_in_url_ipv4_number(hostname: str) -> bool:
    last = hostname.rsplit(".", maxsplit=1)[-1]
    return last.isascii() and (
        last.isdecimal() or re.fullmatch(r"0x[0-9a-f]*", last, re.IGNORECASE) is not None
    )
