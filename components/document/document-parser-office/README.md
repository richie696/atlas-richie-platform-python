# atlas-richie-document-parser-office

OOXML 解析适配器：`DocxParser`（python-docx）与 `XlsxParser`（openpyxl）。

依赖 `document-parser` + `python-docx` + `openpyxl`。重驱动隔离在本包。

## 覆盖范围

| 格式 | 支持 | 说明 |
|---|---|---|
| DOCX | ✓ | 段落 + 表格行，标题取 core properties |
| XLSX | ✓ | 逐 sheet 逐行，`read_only` + `data_only` 流式读取 |
| DOC / XLS / PPT（旧二进制） | ✗ | 显式 `FormatNotSupportedException` |
| PPTX / ODT / ODS / ODP | ✗ | 显式 `FormatNotSupportedException` |

Java 侧靠 Tika + POI 覆盖旧二进制格式；Python 无等价的单一依赖，故本包
只交付 OOXML，其余格式**显式拒绝**而不是静默返回空文本。需要旧格式时请
先转换，或后续单独引入适配器。

## 用法

```python
from atlas_richie.document_parser import Format, ParserRouter
from atlas_richie.document_parser_office import DocxParser, XlsxParser

router = ParserRouter({Format.DOCX: DocxParser(), Format.XLSX: XlsxParser()})
```

两者都支持 `context.max_segment_length`、`context.timeout` 与可选 `listener`；
异常统一以 `Failed` 事件结束。XLSX 的空行与全空单元格行会被跳过。
