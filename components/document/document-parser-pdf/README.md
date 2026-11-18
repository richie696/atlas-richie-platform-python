# atlas-richie-document-parser-pdf

PDF 解析适配器，实现 `document-parser` 的 `DocumentParser` 协议。

依赖 `document-parser` + `pypdf[image]`（后者带入 Pillow，pypdf 的图片抽取必需）。
重驱动隔离在本包，core 仍零第三方依赖。

对位 Java `TikaDocumentParser` 的 PDF 部分：

- 逐页产出文本段，`section_path` 为 `/{name}/Page[n]`，metadata 带 `page`；
- `context.emit_images=True` 时抽取内嵌图片为 `ImageStreaming`，MIME 由返回
  名字的扩展名推断（pypdf 会重编码为 PNG）；超过 `max_embedded_image_bytes`
  （默认 20MB，同 Java）的图片跳过；单张图片抽取失败不影响整份文档；
- `context.timeout` 在页间检查，超时以 `Failed` 事件结束；
- `context.max_segment_length` 对长页文本再切分。

## 纯图 PDF

与 Java 一致，检测**默认关闭**：图片以事件发出，业务方自行走 OCR/VLM。
显式开启严格模式才 fail-fast：

```python
from atlas_richie.document_parser_pdf import PdfParser, ImageOnlyDetection

parser = PdfParser(image_only_detection=ImageOnlyDetection(enabled=True))
```

判定阈值同 Java：`(textChars < 200 and imageCount >= 5) or textChars < 50`。
触发时产出 `Failed(ImageOnlyPdfException(...))`，异常携带 image_count /
text_chars / page_count / name_hint 供诊断。

## 注册到路由

```python
from atlas_richie.document_parser import Format, ParserRouter
from atlas_richie.document_parser_pdf import PdfParser

router = ParserRouter({Format.PDF: PdfParser()})
```
