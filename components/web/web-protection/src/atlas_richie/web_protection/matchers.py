"""Pure request predicates: bot User-Agent globs and IP/CIDR blacklists.

Ported from `cn.richie696.component.web.core.protection` (Java):
`BotUserAgentMatcher` and `IpBlacklistEntry`, both framework-free there.
"""

from __future__ import annotations

import ipaddress
import re


def glob_to_regex(glob: str) -> str:
    """Translate a `*` / `?` glob to a regex, preserving the Java `/*` convention.

    A trailing `/` immediately before `*` is dropped, because `*` already means
    "zero or more of anything" — so `/path/*` behaves as `/path` + anything.
    A trailing `/` before `?` IS literal.
    """
    if glob == "":
        return ".*"
    parts: list[str] = []
    i = 0
    while i < len(glob):
        char = glob[i]
        if char in "*?":
            parts.append(".*" if char == "*" else ".")
            i += 1
            continue
        start = i
        while i < len(glob) and glob[i] not in "*?":
            i += 1
        literal = glob[start:i]
        if i < len(glob) and glob[i] == "*" and literal.endswith("/"):
            literal = literal[:-1]
        if literal:
            parts.append(re.escape(literal))
    return "".join(parts)


class BotUserAgentMatcher:
    """Case-insensitive full-string glob match against a User-Agent."""

    def __init__(self, glob_pattern: str) -> None:
        if glob_pattern is None:
            raise ValueError("globPattern must not be null")
        self._pattern = glob_pattern
        self._regex = re.compile(glob_to_regex(glob_pattern), re.IGNORECASE)

    @property
    def pattern(self) -> str:
        return self._pattern

    def matches(self, user_agent: str | None) -> bool:
        if user_agent is None:
            return False
        return self._regex.fullmatch(user_agent) is not None


class IpBlacklistEntry:
    """One IP or CIDR entry, matching either address family independently.

    Hardening deviation from Java: `InetAddress.getByName` will resolve hostnames
    via DNS, which turns a blacklist lookup into an outbound name query. This port
    accepts IP literals only, so a hostname simply never matches.
    """

    def __init__(self, source: str) -> None:
        if source is None:
            raise ValueError("source must not be null")
        self._source = source
        ip_part, slash, prefix_part = source.partition("/")
        try:
            address = ipaddress.ip_address(ip_part.strip())
        except ValueError as error:
            raise ValueError(f"Invalid IP address: {source}") from error
        if slash:
            try:
                prefix = int(prefix_part)
            except ValueError as error:
                raise ValueError(f"Invalid CIDR prefix: {source}") from error
            if prefix < 0:
                raise ValueError(f"CIDR prefix must be non-negative: {source}")
            maximum = 32 if address.version == 4 else 128
            if prefix > maximum:
                raise ValueError(
                    f"CIDR prefix /{prefix} out of range for IPv{address.version}"
                )
            self._network = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
        else:
            self._network = ipaddress.ip_network(address)

    @property
    def source(self) -> str:
        return self._source

    def matches_address(self, candidate: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return candidate.version == self._network.version and candidate in self._network

    def matches(self, candidate: str | None) -> bool:
        """Accepts a comma-separated chain (X-Forwarded-For) and uses the first hop."""
        if candidate is None or not candidate.strip():
            return False
        first = candidate.split(",", 1)[0].strip()
        try:
            address = ipaddress.ip_address(first)
        except ValueError:
            return False
        return self.matches_address(address)


__all__ = ["BotUserAgentMatcher", "IpBlacklistEntry", "glob_to_regex"]
