# atlas-richie-document-parser-html

HTML 解析适配器，实现 `document-parser` 的 `DocumentParser` 协议。

依赖 `document-parser` + `beautifulsoup4` + `lxml`。重驱动隔离在本包。

对位 Java `TikaDocumentParser` 的 HTML 部分（SAX 块级 handler）：

- 按**块级元素**产出文本段（`p / div / td / th / li / h1..h6 / pre / blockquote`），
  只取最内层块，避免父子块重复输出同一段文本；
- `script / style / noscript / template` 整体剔除；
- `<title>` 进入 `DocumentSummary.title`；
- `section_path` 为 `/{name}/Block[n]`，metadata 带 `tag` 与 `order`；
- `context.emit_images=True` 时抽取 **`data:` URI 内联图片**；远程 `src` 不发起
  网络请求（抓取是 `document-fetcher` 的职责），仅记录为跳过；
- `context.timeout` 在块间检查，`max_segment_length` 对长块再切分。

## 注册到路由

```python
from atlas_richie.document_parser import Format, ParserRouter
from atlas_richie.document_parser_html import HtmlParser

router = ParserRouter({Format.HTML: HtmlParser(), Format.XML: HtmlParser()})
```
