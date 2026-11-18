"""URL 下载器：SSRF 逐跳校验、重定向、大小上限，以及真实 HTTP 端到端。"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from atlas_richie.document_parser import CidrBlock, UrlFetchPolicy
from atlas_richie.document_fetcher import (
    DEFAULT_MAX_REDIRECTS,
    DocumentFetcher,
    UrlFetchError,
    UrlPolicyError,
)

pytestmark = pytest.mark.unit


class _Response:
    def __init__(self, status=200, body=b"", headers=None, chunks=None) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self._chunks = chunks

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308)

    def iter_bytes(self, chunk_size=None):
        if self._chunks is not None:
            yield from self._chunks
            return
        for start in range(0, len(self._body), chunk_size or 65536):
            yield self._body[start : start + (chunk_size or 65536)]

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class _Client:
    """Records requests and replays scripted responses per URL."""

    def __init__(self, script: dict[str, _Response], **kwargs) -> None:
        self.script = script
        self.kwargs = kwargs
        self.requests: list[str] = []
        self.closed = False

    def stream(self, method, url):
        self.requests.append(url)
        return self.script[url]

    def close(self) -> None:
        self.closed = True


def _fetcher(script, *, policy=None, resolver=None, **kwargs):
    clients: list[_Client] = []

    def factory(**kw):
        client = _Client(script, **kw)
        clients.append(client)
        return client

    fetcher = DocumentFetcher(
        policy, resolver=resolver or (lambda host: ["93.184.216.34"]),
        client_factory=factory, **kwargs
    )
    return fetcher, clients


class TestPolicyEnforcement:
    def test_public_https_allowed(self) -> None:
        url = "https://example.com/a.pdf"
        fetcher, _ = _fetcher({url: _Response(body=b"ok")})
        assert fetcher.fetch(url).data == b"ok"

    def test_plain_http_denied_by_default(self) -> None:
        fetcher, _ = _fetcher({})
        with pytest.raises(UrlPolicyError, match="plain HTTP"):
            fetcher.fetch("http://example.com/a.pdf")

    def test_private_ip_denied_by_default(self) -> None:
        fetcher, _ = _fetcher({}, resolver=lambda h: ["127.0.0.1"])
        with pytest.raises(UrlPolicyError, match="disallowed address"):
            fetcher.fetch("https://example.com/a.pdf")

    @pytest.mark.parametrize(
        "address",
        ["10.0.0.1", "192.168.1.1", "169.254.169.254", "::1", "fe80::1", "0.0.0.0"],
    )
    def test_non_global_addresses_denied(self, address) -> None:
        fetcher, _ = _fetcher({}, resolver=lambda h: [address])
        with pytest.raises(UrlPolicyError):
            fetcher.fetch("https://example.com/a.pdf")

    def test_every_resolved_address_must_pass(self) -> None:
        fetcher, _ = _fetcher({}, resolver=lambda h: ["93.184.216.34", "127.0.0.1"])
        with pytest.raises(UrlPolicyError, match="127.0.0.1"):
            fetcher.fetch("https://example.com/a.pdf")

    def test_allowlist_overrides_private_denial(self) -> None:
        url = "https://internal.example/a.pdf"
        policy = UrlFetchPolicy(allowlist=(CidrBlock("10.0.0.0/8"),))
        fetcher, _ = _fetcher({url: _Response(body=b"ok")}, policy=policy,
                              resolver=lambda h: ["10.1.2.3"])
        assert fetcher.fetch(url).data == b"ok"

    def test_allowlist_cannot_override_http_denial(self) -> None:
        policy = UrlFetchPolicy(allowlist=(CidrBlock("10.0.0.0/8"),))
        fetcher, _ = _fetcher({}, policy=policy, resolver=lambda h: ["10.1.2.3"])
        with pytest.raises(UrlPolicyError, match="plain HTTP"):
            fetcher.fetch("http://internal.example/a.pdf")

    def test_allow_private_ip_flag(self) -> None:
        url = "https://example.com/a"
        fetcher, _ = _fetcher({url: _Response(body=b"ok")},
                              policy=UrlFetchPolicy(allow_private_ip=True),
                              resolver=lambda h: ["127.0.0.1"])
        assert fetcher.fetch(url).data == b"ok"

    @pytest.mark.parametrize("url", ["ftp://example.com/a", "file:///etc/passwd", "gopher://x/"])
    def test_non_http_schemes_denied(self, url) -> None:
        fetcher, _ = _fetcher({})
        with pytest.raises(UrlPolicyError, match="scheme"):
            fetcher.fetch(url)

    def test_missing_host_denied(self) -> None:
        fetcher, _ = _fetcher({})
        with pytest.raises(UrlPolicyError):
            fetcher.fetch("https:///path-only")

    def test_dns_failure_is_fetch_error(self) -> None:
        def boom(host):
            raise UrlFetchError("dns down")

        fetcher, _ = _fetcher({}, resolver=boom)
        with pytest.raises(UrlFetchError):
            fetcher.fetch("https://example.com/a")

    def test_empty_dns_result_is_fetch_error(self) -> None:
        fetcher, _ = _fetcher({}, resolver=lambda h: [])
        with pytest.raises(UrlFetchError, match="no addresses"):
            fetcher.fetch("https://example.com/a")


class TestRedirects:
    def test_redirect_is_followed_and_revalidated(self) -> None:
        first = "https://example.com/a"
        second = "https://cdn.example.com/b"
        script = {
            first: _Response(302, headers={"location": second}),
            second: _Response(body=b"final"),
        }
        fetcher, clients = _fetcher(script)
        result = fetcher.fetch(first)
        assert result.data == b"final"
        assert result.url == second
        assert clients[0].requests == [first, second]

    def test_redirect_to_private_ip_is_blocked(self) -> None:
        """核心 SSRF 场景：公网 URL 302 到元数据服务必须被拦。"""
        first = "https://example.com/a"
        target = "https://metadata.internal/latest"
        script = {first: _Response(302, headers={"location": target})}

        def resolver(host):
            return ["169.254.169.254"] if host == "metadata.internal" else ["93.184.216.34"]

        fetcher, clients = _fetcher(script, resolver=resolver)
        with pytest.raises(UrlPolicyError, match="169.254.169.254"):
            fetcher.fetch(first)
        assert clients[0].requests == [first], "不得真的请求内网目标"

    def test_redirect_downgrade_to_http_is_blocked(self) -> None:
        first = "https://example.com/a"
        script = {first: _Response(302, headers={"location": "http://example.com/b"})}
        fetcher, _ = _fetcher(script)
        with pytest.raises(UrlPolicyError, match="plain HTTP"):
            fetcher.fetch(first)

    def test_relative_location_is_resolved(self) -> None:
        first = "https://example.com/dir/a"
        second = "https://example.com/dir/b"
        script = {
            first: _Response(302, headers={"location": "b"}),
            second: _Response(body=b"rel"),
        }
        fetcher, _ = _fetcher(script)
        assert fetcher.fetch(first).data == b"rel"

    def test_redirect_without_location_is_error(self) -> None:
        url = "https://example.com/a"
        fetcher, _ = _fetcher({url: _Response(302)})
        with pytest.raises(UrlFetchError, match="Location"):
            fetcher.fetch(url)

    def test_redirect_loop_hits_limit(self) -> None:
        url = "https://example.com/a"
        fetcher, _ = _fetcher({url: _Response(302, headers={"location": url})}, max_redirects=3)
        with pytest.raises(UrlFetchError, match="too many redirects"):
            fetcher.fetch(url)

    def test_zero_redirects_allows_direct_fetch(self) -> None:
        url = "https://example.com/a"
        fetcher, _ = _fetcher({url: _Response(body=b"ok")}, max_redirects=0)
        assert fetcher.fetch(url).data == b"ok"

    def test_negative_redirects_rejected(self) -> None:
        with pytest.raises(ValueError):
            DocumentFetcher(max_redirects=-1)

    def test_default_limit(self) -> None:
        assert DEFAULT_MAX_REDIRECTS == 5


class TestSizeAndStatus:
    def test_size_cap_aborts_download(self) -> None:
        url = "https://example.com/big"
        response = _Response(chunks=[b"x" * 100, b"y" * 100])
        fetcher, _ = _fetcher({url: response}, policy=UrlFetchPolicy(max_bytes=150))
        with pytest.raises(UrlFetchError, match="max_bytes"):
            fetcher.fetch(url)

    def test_exact_cap_allowed(self) -> None:
        url = "https://example.com/ok"
        fetcher, _ = _fetcher({url: _Response(body=b"x" * 100)},
                              policy=UrlFetchPolicy(max_bytes=100))
        assert fetcher.fetch(url).size == 100

    @pytest.mark.parametrize("status", [400, 403, 404, 500])
    def test_error_status_raises(self, status) -> None:
        url = "https://example.com/a"
        fetcher, _ = _fetcher({url: _Response(status)})
        with pytest.raises(UrlFetchError, match=f"HTTP {status}"):
            fetcher.fetch(url)

    def test_content_type_and_status_reported(self) -> None:
        url = "https://example.com/a.pdf"
        response = _Response(body=b"pdf", headers={"content-type": "application/pdf"})
        fetcher, _ = _fetcher({url: response})
        result = fetcher.fetch(url)
        assert result.content_type == "application/pdf"
        assert result.status_code == 200

    def test_client_is_closed(self) -> None:
        url = "https://example.com/a"
        fetcher, clients = _fetcher({url: _Response(body=b"ok")})
        fetcher.fetch(url)
        assert clients[0].closed is True

    def test_client_closed_even_on_policy_error(self) -> None:
        fetcher, clients = _fetcher({}, resolver=lambda h: ["127.0.0.1"])
        with pytest.raises(UrlPolicyError):
            fetcher.fetch("https://example.com/a")
        assert clients[0].closed is True

    def test_automatic_redirects_disabled_on_client(self) -> None:
        url = "https://example.com/a"
        fetcher, clients = _fetcher({url: _Response(body=b"ok")})
        fetcher.fetch(url)
        assert clients[0].kwargs["follow_redirects"] is False

    def test_timeouts_come_from_policy(self) -> None:
        url = "https://example.com/a"
        policy = UrlFetchPolicy(connect_timeout=2.0, read_timeout=9.0)
        fetcher, clients = _fetcher({url: _Response(body=b"ok")}, policy=policy)
        fetcher.fetch(url)
        timeout = clients[0].kwargs["timeout"]
        assert timeout.connect == 2.0
        assert timeout.read == 9.0


class TestFetchSource:
    def test_source_name_derived_from_final_url(self) -> None:
        url = "https://example.com/files/report.pdf"
        fetcher, _ = _fetcher({url: _Response(body=b"pdf")})
        source = fetcher.fetch_source(url)
        assert source.name == "report.pdf"
        assert source.data == b"pdf"

    def test_source_falls_back_when_path_empty(self) -> None:
        url = "https://example.com"
        fetcher, _ = _fetcher({url: _Response(body=b"x")})
        assert fetcher.fetch_source(url).name == "download"


@pytest.mark.integration
class TestAgainstRealHttpServer:
    """真实本地 HTTP 服务：验证策略放行后确实能下载并重定向。"""

    @pytest.fixture
    def server(self):
        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/file.pdf")
                    self.end_headers()
                    return
                if self.path == "/big":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.end_headers()
                    self.wfile.write(b"x" * 5000)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.end_headers()
                self.wfile.write(b"%PDF-1.4 real bytes")

            def log_message(self, *args) -> None:
                pass

        httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_port}"
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(5)

    def test_download_with_permissive_policy(self, server) -> None:
        policy = UrlFetchPolicy(allow_http=True, allow_private_ip=True)
        result = DocumentFetcher(policy).fetch(f"{server}/file.pdf")
        assert result.data == b"%PDF-1.4 real bytes"
        assert result.content_type == "application/pdf"

    def test_default_policy_blocks_loopback(self, server) -> None:
        with pytest.raises(UrlPolicyError):
            DocumentFetcher().fetch(f"{server}/file.pdf")

    def test_redirect_followed_end_to_end(self, server) -> None:
        policy = UrlFetchPolicy(allow_http=True, allow_private_ip=True)
        result = DocumentFetcher(policy).fetch(f"{server}/redirect")
        assert result.data == b"%PDF-1.4 real bytes"
        assert result.url.endswith("/file.pdf")

    def test_size_cap_end_to_end(self, server) -> None:
        policy = UrlFetchPolicy(allow_http=True, allow_private_ip=True, max_bytes=1000)
        with pytest.raises(UrlFetchError, match="max_bytes"):
            DocumentFetcher(policy).fetch(f"{server}/big")

    def test_fetch_source_feeds_the_parser_router(self, server) -> None:
        """下载 → 路由 → 解析全链路（PDF 适配器需已安装）。"""
        pytest.importorskip("atlas_richie.document_parser_pdf")
        from atlas_richie.document_parser import Format, ParserRouter
        from atlas_richie.document_parser_pdf import PdfParser

        from atlas_richie.document_parser import FormatNotSupportedException

        policy = UrlFetchPolicy(allow_http=True, allow_private_ip=True)
        source = DocumentFetcher(policy).fetch_source(f"{server}/file.pdf")
        assert source.name == "file.pdf"
        events = list(ParserRouter({Format.PDF: PdfParser()}).parse(source))
        assert events
        # 服务端返回的是占位字节而非合法 PDF：必须走到 PDF 解析器并以其错误
        # 结束，而不是被格式探测拒之门外——这才证明 fetch→detect→route 通了。
        assert not any(
            isinstance(getattr(e, "error", None), FormatNotSupportedException)
            for e in events
        ), "格式探测应识别为 PDF 并路由到适配器"