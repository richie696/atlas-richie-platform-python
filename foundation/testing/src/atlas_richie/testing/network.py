"""Service reachability probes for integration-test gates.

Pure standard library. Extracted because the same TCP probe was duplicated across
the cache-redis, statemachine-redis and redis-streammq test suites; the root
conftest's rule is that a helper belongs here once 2+ packages need it.
"""

from __future__ import annotations

import socket


def host_port_of(url: str, default_port: int) -> tuple[str, int] | None:
    """Extract (host, port) from a service URL or a bare `host:port`.

    Accepts `scheme://[user:password@]host[:port][/path]` and `host:port`,
    including bracketed IPv6 literals such as `redis://[::1]:6379/0`.
    Returns None when the URL cannot be parsed.
    """
    if not url:
        return None
    rest = url.split("://", 1)[1] if "://" in url else url
    if "@" in rest:
        rest = rest.rsplit("@", 1)[1]
    rest = rest.split("/", 1)[0]
    if not rest:
        return None
    if rest.startswith("["):
        closing = rest.find("]")
        if closing < 0:
            return None
        host = rest[1:closing]
        remainder = rest[closing + 1 :]
        if not remainder:
            return (host, default_port) if host else None
        if not remainder.startswith(":"):
            return None
        port_text = remainder[1:]
    else:
        colons = rest.count(":")
        if colons > 1:
            # Unbracketed IPv6 is ambiguous with host:port; refuse rather than
            # silently probing a bogus host/port pair.
            return None
        if colons == 0:
            host, port_text = rest, ""
        else:
            host, _, port_text = rest.partition(":")
    if not host:
        return None
    if not port_text:
        return host, default_port
    try:
        return host, int(port_text)
    except ValueError:
        return None


def tcp_reachable(url: str, *, default_port: int = 6379, timeout: float = 1.0) -> bool:
    """Whether a TCP connection to the URL's host:port succeeds.

    A cheap gate, not a protocol health check: it says the port is open, not that
    the service is authenticated or usable. Callers needing protocol-level checks
    (Vault's `/v1/sys/health`, LocalStack's health endpoint) should keep their own.
    """
    parsed = host_port_of(url, default_port)
    if parsed is None:
        return False
    host, port = parsed
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


__all__ = ["host_port_of", "tcp_reachable"]
