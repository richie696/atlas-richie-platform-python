# atlas-richie-document-fetcher

把 URL 下载成 bytes/stream，并**真正执行** `document-parser` 的 `UrlFetchPolicy`。

此前 core 只有 SSRF 规则而没有执行者：`ParserRouter` 遇到 `UrlSource` 直接抛
「先下载再解析」。本包补上那个执行者。

依赖 `document-parser` + `httpx-env` + `httpx`。

## 安全设计

- **逐跳校验**：关闭 httpx 自动重定向，自己跟随；每一跳都重新解析 DNS 并对
  **所有**解析出的地址执行 `policy.permits`。否则一个公网 URL 可以 302 到
  `169.254.169.254` 绕过检查。
- **默认拒绝**：plain HTTP 与私网/环回/链路本地/保留地址默认拒绝（同 Java）；
  allowlist 是显式 opt-in，可覆盖私网拒绝但**不能**覆盖 HTTP 拒绝。
- **流式大小上限**：边下边计数，超过 `max_bytes` 立即中断，不先吞满内存。
- **超时**：connect / read 分别取自 policy。
- 复用 `httpx-env` 的 `no_proxy_ipv6_guard`，规避 httpx 对 NO_PROXY 中
  带方括号 IPv6 的解析 bug。

## 已知限制

DNS 校验与建连之间存在 rebinding 窗口：校验用的解析结果与 httpx 实际建连
时的解析可能不同。要彻底消除需把连接钉在校验过的 IP 上（自定义 transport），
本包未做，调用方若面对不可信 URL 应在网络层再加一道出站隔离。

## 用法

```python
from atlas_richie.document_fetcher import DocumentFetcher
from atlas_richie.document_parser import ParserRouter, Format
from atlas_richie.document_parser_pdf import PdfParser

fetcher = DocumentFetcher()
source = fetcher.fetch_source("https://example.com/report.pdf")
events = ParserRouter({Format.PDF: PdfParser()}).parse(source)
```
