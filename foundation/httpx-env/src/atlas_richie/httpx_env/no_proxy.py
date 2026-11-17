"""NO_PROXY 兼容垫片。

English
--------
Compatibility shim for the NO_PROXY environment variable HTTPX reads when a
client is constructed. Kept in a zero-dependency leaf so that any component
building an HTTPX client can share the workaround without depending on the
`atlas-richie-http` facade.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Iterator
from contextlib import contextmanager

_NO_PROXY_ENV_KEYS = ("NO_PROXY", "no_proxy")


def _unbracket_ipv6_hosts(value: str) -> str:
    hosts: list[str] = []
    for entry in value.split(","):
        host = entry.strip()
        if host.startswith("[") and host.endswith("]"):
            try:
                ipaddress.IPv6Address(host[1:-1])
            except ipaddress.AddressValueError:
                pass
            else:
                host = host[1:-1]
        hosts.append(host)
    return ",".join(hosts)


@contextmanager
def no_proxy_ipv6_guard() -> Iterator[None]:
    """规避 httpx 0.28.1 对带方括号 IPv6 NO_PROXY 条目的解析崩溃。

    httpx 不把 `[::1]` 认作 IPv6，该条目落入域名通配分支生成 `all://*[::1]`，
    URL 解析抛 InvalidURL，任何 client 都构造不出来。方括号对主机分类是冗余的，
    去掉后 bypass 语义不变。变换幂等且语义保持，故并发构造看到归一化值也无影响。

    用法：包住 `httpx.Client(...)` / `httpx.AsyncClient(...)` 的构造调用。
    传入 `transport=` 的构造不读环境代理，无需本守卫。
    """
    saved: dict[str, str] = {}
    for key in _NO_PROXY_ENV_KEYS:
        value = os.environ.get(key)
        if value is None:
            continue
        normalized = _unbracket_ipv6_hosts(value)
        if normalized != value:
            saved[key] = value
            os.environ[key] = normalized
    try:
        yield
    finally:
        for key, value in saved.items():
            os.environ[key] = value
