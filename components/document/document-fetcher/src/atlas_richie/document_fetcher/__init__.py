"""执行 UrlFetchPolicy 的 URL 下载器。

core 此前只有 SSRF 规则而没有执行者，本包补上。关键设计是**逐跳校验**：
关闭 httpx 自动重定向、自己跟随，每一跳重新解析 DNS 并对所有解析地址执行
`policy.permits`。否则一个公网 URL 可以 302 到 169.254.169.254 绕过检查。

已知限制：DNS 校验与建连之间存在 rebinding 窗口（校验用的解析结果与 httpx
实际建连时的解析可能不同）。彻底消除需把连接钉在校验过的 IP 上，本包未做。
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Callable, Sequence
from urllib.parse import urljoin, urlsplit

import httpx

from atlas_richie.document_parser import (
    BytesSource,
    DocumentParseException,
    UrlFetchPolicy,
)
from atlas_richie.httpx_env import no_proxy_ipv6_guard

DEFAULT_MAX_REDIRECTS = 5
_CHUNK = 65_536


class UrlFetchError(DocumentParseException):
    """下载失败（网络、状态码、大小超限、重定向过多）。"""


class UrlPolicyError(UrlFetchError):
    """URL 被 SSRF 策略拒绝。"""


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    data: bytes
    content_type: str | None
    status_code: int

    @property
    def size(self) -> int:
        return len(self.data)


def _default_resolver(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as error:
        raise UrlFetchError(f"DNS resolution failed for {host!r}: {error}") from error
    return sorted({info[4][0] for info in infos})


class DocumentFetcher:
    def __init__(
        self,
        policy: UrlFetchPolicy | None = None,
        *,
        resolver: Callable[[str], Sequence[str]] | None = None,
        client_factory: Callable[..., httpx.Client] | None = None,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
    ) -> None:
        if max_redirects < 0:
            raise ValueError("max_redirects must be >= 0")
        self._policy = policy if policy is not None else UrlFetchPolicy.defaults()
        self._resolver = resolver or _default_resolver
        self._client_factory = client_factory or httpx.Client
        self._max_redirects = int(max_redirects)

    @property
    def policy(self) -> UrlFetchPolicy:
        return self._policy

    def fetch(self, url: str) -> FetchResult:
        with no_proxy_ipv6_guard():
            return self._fetch(url)

    def fetch_source(self, url: str) -> BytesSource:
        result = self.fetch(url)
        name = urlsplit(result.url).path.rsplit("/", 1)[-1] or "download"
        return BytesSource(result.data, name=name)

    def _fetch(self, url: str) -> FetchResult:
        client = self._client_factory(
            follow_redirects=False,
            timeout=httpx.Timeout(
                self._policy.read_timeout, connect=self._policy.connect_timeout
            ),
        )
        try:
            current = url
            for _ in range(self._max_redirects + 1):
                self._check(current)
                with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise UrlFetchError(
                                f"redirect without Location header from {current}"
                            )
                        current = urljoin(current, location)
                        continue
                    if response.status_code >= 400:
                        raise UrlFetchError(
                            f"HTTP {response.status_code} for {current}"
                        )
                    data = self._read_capped(response, current)
                    return FetchResult(
                        url=current,
                        data=data,
                        content_type=response.headers.get("content-type"),
                        status_code=response.status_code,
                    )
            raise UrlFetchError(
                f"too many redirects (limit {self._max_redirects}) from {url}"
            )
        except httpx.HTTPError as error:
            raise UrlFetchError(f"fetch failed for {url}: {error}") from error
        finally:
            client.close()

    def _check(self, url: str) -> None:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        host = parts.hostname
        if scheme not in ("http", "https"):
            raise UrlPolicyError(f"scheme not permitted: {scheme or '(none)'}")
        if not host:
            raise UrlPolicyError(f"URL has no host: {url}")
        if scheme == "http" and not self._policy.allow_http:
            raise UrlPolicyError(f"plain HTTP is not permitted: {url}")
        addresses = list(self._resolver(host))
        if not addresses:
            raise UrlFetchError(f"DNS returned no addresses for {host!r}")
        for address in addresses:
            if not self._policy.permits(scheme, address):
                raise UrlPolicyError(
                    f"host {host!r} resolves to a disallowed address {address}"
                )

    def _read_capped(self, response: httpx.Response, url: str) -> bytes:
        limit = self._policy.max_bytes
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes(_CHUNK):
            total += len(chunk)
            if total > limit:
                raise UrlFetchError(
                    f"download exceeds max_bytes {limit} for {url}"
                )
            chunks.append(chunk)
        return b"".join(chunks)


__all__ = [
    "DocumentFetcher",
    "FetchResult",
    "UrlFetchError",
    "UrlPolicyError",
    "DEFAULT_MAX_REDIRECTS",
]