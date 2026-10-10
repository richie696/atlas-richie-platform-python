"""Strict normalization for explicitly configured browser origins."""

from __future__ import annotations

from urllib.parse import urlsplit


def normalize_browser_origin(value: str) -> str:
    """Normalize an HTTP(S) origin and reject URL components beyond an origin."""
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("browser origins must be valid HTTP(S) origins") from exc

    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("browser origins must contain only scheme and authority")

    host = hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    default_port = 80 if scheme == "http" else 443
    authority = host if port is None or port == default_port else f"{host}:{port}"
    return f"{scheme}://{authority}"
