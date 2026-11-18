"""Document parser tests: detection, policy, streaming text path, routing."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from atlas_richie.document_parser import (
    BytesSource,
    CidrBlock,
    Failed,
    Finished,
    Format,
    FormatNotSupportedException,
    ParserContext,
    ParserRouter,
    Streaming,
    StreamSource,
    TextFastPathParser,
    UrlFetchPolicy,
    UrlSource,
    detect_format,
    from_extension,
    sniff,
    supports,
    to_format,
)

pytestmark = pytest.mark.unit


def _ooxml(member: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, "x")
    return buffer.getvalue()


def _odf(mime: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", mime)
    return buffer.getvalue()


class TestSniff:
    @pytest.mark.parametrize(
        ("head", "mime"),
        [
            (b"%PDF-1.7\n", "application/pdf"),
            (b"{\\rtf1\\ansi", "application/rtf"),
            (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest", "application/x-ole-storage"),
            (b"<!DOCTYPE html><html>", "text/html"),
            (b"<html><body>", "text/html"),
            (b"<?xml version='1.0'?>", "application/xml"),
            (b"plain text", "text/plain"),
            (b"\xef\xbb\xbfplain text", "text/plain"),
            (b"binary\x00data", "application/octet-stream"),
            (b"", "application/octet-stream"),
        ],
    )
    def test_magic_bytes(self, head: bytes, mime: str) -> None:
        assert sniff(head) == mime

    def test_docx_container(self) -> None:
        assert to_format(sniff(_ooxml("word/document.xml"))) is Format.DOCX

    def test_xlsx_container(self) -> None:
        assert to_format(sniff(_ooxml("xl/workbook.xml"))) is Format.XLSX

    def test_pptx_container(self) -> None:
        assert to_format(sniff(_ooxml("ppt/presentation.xml"))) is Format.PPTX

    @pytest.mark.parametrize(
        ("mime", "expected"),
        [
            ("application/vnd.oasis.opendocument.text", Format.ODT),
            ("application/vnd.oasis.opendocument.spreadsheet", Format.ODS),
            ("application/vnd.oasis.opendocument.presentation", Format.ODP),
        ],
    )
    def test_odf_containers(self, mime: str, expected: Format) -> None:
        assert to_format(sniff(_odf(mime))) is expected

    def test_unknown_zip_is_not_misdetected_as_office(self) -> None:
        assert to_format(sniff(_ooxml("random.txt"))) is Format.UNKNOWN


class TestMimeAndExtensionMapping:
    @pytest.mark.parametrize(
        ("mime", "expected"),
        [
            ("application/pdf", Format.PDF),
            ("application/msword", Format.DOC),
            ("application/vnd.ms-excel", Format.XLS),
            ("application/vnd.ms-powerpoint", Format.PPT),
            ("text/rtf", Format.RTF),
            ("application/rtf", Format.RTF),
            ("text/markdown", Format.MD),
            ("text/x-markdown", Format.MD),
            ("text/html", Format.HTML),
            ("text/xml", Format.XML),
            ("application/xml", Format.XML),
            ("text/plain; charset=utf-8", Format.TXT),
            ("application/unknown", Format.UNKNOWN),
            (None, Format.UNKNOWN),
        ],
    )
    def test_to_format(self, mime, expected: Format) -> None:
        assert to_format(mime) is expected

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("report.PDF", Format.PDF), ("a.docx", Format.DOCX), ("a.doc", Format.DOC),
            ("a.xlsx", Format.XLSX), ("a.xls", Format.XLS), ("a.pptx", Format.PPTX),
            ("a.ppt", Format.PPT), ("a.odt", Format.ODT), ("a.ods", Format.ODS),
            ("a.odp", Format.ODP), ("a.rtf", Format.RTF), ("a.txt", Format.TXT),
            ("a.md", Format.MD), ("a.markdown", Format.MD), ("a.html", Format.HTML),
            ("a.htm", Format.HTML), ("a.xml", Format.XML), ("a.bin", Format.UNKNOWN),
            (None, Format.UNKNOWN),
        ],
    )
    def test_from_extension(self, name, expected: Format) -> None:
        assert from_extension(name) is expected

    def test_content_wins_over_extension(self) -> None:
        assert detect_format(b"%PDF-1.4", "lies.txt") is Format.PDF

    @pytest.mark.parametrize(
        ("head", "name", "expected"),
        [
            (b"<html><body>hi</body></html>", "notes.txt", Format.TXT),
            (b"<?xml version='1.0'?>", "notes.txt", Format.TXT),
            (b"<div>partial markup</div>", "README.md", Format.MD),
            (b"# Title\n\n<div>x</div>", "README.md", Format.MD),
            (b"<html>x</html>", "page.html", Format.HTML),
            (b"<?xml version='1.0'?>", "data.xml", Format.XML),
            (b"plain text", "notes.md", Format.MD),
        ],
    )
    def test_explicit_text_name_overrides_weak_markup_sniff(
        self, head: bytes, name: str, expected: Format
    ) -> None:
        """Regression: any leading '<' sniffed as HTML/XML, so a .txt/.md file
        containing markup was routed to an unregistered parser and raised."""
        assert detect_format(head, name) is expected

    def test_binary_magic_still_wins_over_text_name(self) -> None:
        assert detect_format(b"%PDF-1.4", "notes.md") is Format.PDF
        assert detect_format(b"PK\x03\x04word/document.xml", "notes.txt") is Format.DOCX
        assert detect_format(b"{\\rtf1\\ansi", "notes.txt") is Format.RTF

    def test_router_parses_text_file_containing_markup(self) -> None:
        router = ParserRouter()
        events = list(router.parse(BytesSource(b"<html>hi</html>", name="notes.txt")))
        assert events, "TXT 快路径必须能处理含 markup 的 .txt 文件"

    def test_extension_fallback_when_content_inconclusive(self) -> None:
        assert detect_format(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "legacy.xls") is Format.XLS

    def test_unknown_when_both_inconclusive(self) -> None:
        assert detect_format(b"\x00\x01\x02", "mystery.bin") is Format.UNKNOWN


class TestUrlFetchPolicy:
    def test_defaults_deny_http_and_private_ips(self) -> None:
        policy = UrlFetchPolicy.defaults()
        assert policy.allow_http is False
        assert policy.allow_private_ip is False
        assert policy.max_bytes == 200 * 1024 * 1024
        assert policy.connect_timeout == 5.0
        assert policy.read_timeout == 60.0
        assert policy.permits("http", "93.184.216.34") is False
        assert policy.permits("https", "127.0.0.1") is False
        assert policy.permits("https", "10.0.0.1") is False
        assert policy.permits("https", "192.168.1.1") is False
        assert policy.permits("https", "169.254.1.1") is False
        assert policy.permits("https", "::1") is False
        assert policy.permits("https", "93.184.216.34") is True

    def test_non_http_schemes_denied(self) -> None:
        assert UrlFetchPolicy().permits("file", "/etc/passwd") is False
        assert UrlFetchPolicy().permits("ftp", "93.184.216.34") is False

    def test_allow_http_opt_in(self) -> None:
        assert UrlFetchPolicy(allow_http=True).permits("http", "93.184.216.34") is True

    def test_allow_private_ip_opt_in(self) -> None:
        assert UrlFetchPolicy(allow_private_ip=True).permits("https", "127.0.0.1") is True

    def test_non_positive_values_fall_back_to_defaults(self) -> None:
        policy = UrlFetchPolicy(max_bytes=0, connect_timeout=0, read_timeout=-1)
        assert policy.max_bytes == 200 * 1024 * 1024
        assert policy.connect_timeout == 5.0
        assert policy.read_timeout == 60.0

    def test_unparseable_host_is_unsafe(self) -> None:
        assert UrlFetchPolicy().is_private_address("not-an-ip") is True
        assert UrlFetchPolicy().permits("https", "not-an-ip") is False


class TestCidrBlock:
    def test_ipv4_membership(self) -> None:
        block = CidrBlock("10.0.0.0/8")
        assert block.contains("10.1.2.3") is True
        assert block.contains("11.0.0.1") is False

    def test_ipv6_membership(self) -> None:
        block = CidrBlock("2001:db8::/32")
        assert block.contains("2001:db8::1") is True
        assert block.contains("2001:db9::1") is False

    def test_address_family_never_cross_matches(self) -> None:
        assert CidrBlock("0.0.0.0/0").contains("::1") is False
        assert CidrBlock("::/0").contains("10.0.0.1") is False

    def test_host_bits_are_masked(self) -> None:
        assert CidrBlock("10.1.2.3/8").contains("10.9.9.9") is True

    def test_invalid_inputs(self) -> None:
        with pytest.raises(ValueError):
            CidrBlock("  ")
        with pytest.raises(ValueError):
            CidrBlock("not-a-cidr")
        assert CidrBlock("10.0.0.0/8").contains("garbage") is False

    def test_allowlist_overrides_private_denial_but_not_http(self) -> None:
        policy = UrlFetchPolicy(allowlist=(CidrBlock("10.0.0.0/8"),))
        assert policy.permits("https", "10.1.2.3") is True
        assert policy.permits("http", "10.1.2.3") is False, "allowlist must not enable plain HTTP"
        assert policy.permits("https", "192.168.1.1") is False, "private and outside the allowlist"


class TestTextFastPath:
    def test_supports_extensions(self) -> None:
        assert supports("a.txt") and supports("a.MD") and supports("a.markdown")
        assert not supports("a.pdf") and not supports(None)

    def test_paragraphs_split_on_blank_lines(self) -> None:
        source = BytesSource(b"first para\n\nsecond para\n\nthird", "doc.txt")
        events = list(TextFastPathParser().parse(source))
        segments = [e.segment.text for e in events if isinstance(e, Streaming)]
        assert segments == ["first para", "second para", "third"]

    def test_multi_line_paragraph_joined(self) -> None:
        source = BytesSource(b"line one\nline two\n\nnext", "doc.txt")
        segments = [e.segment.text for e in TextFastPathParser().parse(source) if isinstance(e, Streaming)]
        assert segments == ["line one\nline two", "next"]

    def test_section_paths_and_metadata(self) -> None:
        source = BytesSource(b"a\n\nb", "notes.md")
        segments = [e.segment for e in TextFastPathParser().parse(source) if isinstance(e, Streaming)]
        assert [s.section_path for s in segments] == ["/notes.md/Paragraph[1]", "/notes.md/Paragraph[2]"]
        assert segments[0].metadata == {"order": 0, "format": "text/plain"}

    def test_finished_event_counts_and_metadata(self) -> None:
        events = list(TextFastPathParser().parse(BytesSource(b"a\n\nb\n\nc", "d.txt")))
        finished = [e for e in events if isinstance(e, Finished)]
        assert len(finished) == 1
        assert finished[0].segment_count == 3
        assert finished[0].image_count == 0
        assert finished[0].summary.metadata == {"format": "text/plain", "encoding": "UTF-8"}

    def test_max_segment_length_forces_split(self) -> None:
        source = BytesSource(b"abcdefghij", "d.txt")
        context = ParserContext(max_segment_length=4)
        segments = [e.segment.text for e in TextFastPathParser().parse(source, context) if isinstance(e, Streaming)]
        assert segments == ["abcd", "efgh", "ij"]

    def test_blank_and_empty_input(self) -> None:
        for data in (b"", b"   \n\t\n  "):
            events = list(TextFastPathParser().parse(BytesSource(data, "d.txt")))
            assert [e for e in events if isinstance(e, Streaming)] == []
            assert isinstance(events[-1], Finished)
            assert events[-1].segment_count == 0

    def test_crlf_handled(self) -> None:
        source = BytesSource(b"a\r\n\r\nb\r\n", "d.txt")
        segments = [e.segment.text for e in TextFastPathParser().parse(source) if isinstance(e, Streaming)]
        assert segments == ["a", "b"]

    def test_utf8_content(self) -> None:
        source = BytesSource("第一段\n\n第二段".encode("utf-8"), "d.txt")
        segments = [e.segment.text for e in TextFastPathParser().parse(source) if isinstance(e, Streaming)]
        assert segments == ["第一段", "第二段"]

    def test_stream_source_position_is_not_consumed_by_caller_contract(self) -> None:
        stream = io.BytesIO(b"a\n\nb")
        events = list(TextFastPathParser().parse(StreamSource(stream, "s.txt")))
        assert [e.segment.text for e in events if isinstance(e, Streaming)] == ["a", "b"]

    def test_file_source(self, tmp_path: Path) -> None:
        path = tmp_path / "doc.txt"
        path.write_text("alpha\n\nbeta", encoding="utf-8")
        from atlas_richie.document_parser import FileSource

        events = list(TextFastPathParser().parse(FileSource(path)))
        assert [e.segment.text for e in events if isinstance(e, Streaming)] == ["alpha", "beta"]

    def test_missing_file_yields_failed_event(self, tmp_path: Path) -> None:
        from atlas_richie.document_parser import FileSource

        events = list(TextFastPathParser().parse(FileSource(tmp_path / "absent.txt")))
        assert len(events) == 1
        assert isinstance(events[0], Failed)

    def test_url_source_rejected(self) -> None:
        events = list(TextFastPathParser().parse(UrlSource("https://example.com/a.txt")))
        assert isinstance(events[0], Failed)
        assert "URL" in str(events[0].error)

    def test_invalid_context_rejected(self) -> None:
        with pytest.raises(ValueError):
            ParserContext(max_segment_length=0)

    def test_streaming_is_incremental(self) -> None:
        """The first segment must be available before the whole input is consumed."""
        parser = TextFastPathParser()
        iterator = parser.parse(BytesSource(b"first\n\nsecond\n\nthird", "d.txt"))
        first = next(iterator)
        assert isinstance(first, Streaming)
        assert first.segment.text == "first"


class TestRouter:
    def test_text_and_markdown_registered_by_default(self) -> None:
        router = ParserRouter()
        assert Format.TXT in router.registered_formats()
        assert Format.MD in router.registered_formats()

    def test_unregistered_format_raises_with_name(self) -> None:
        with pytest.raises(FormatNotSupportedException, match="PDF"):
            ParserRouter().route(Format.PDF)

    def test_unknown_format_message(self) -> None:
        with pytest.raises(FormatNotSupportedException, match="could not be detected"):
            ParserRouter().route(Format.UNKNOWN)

    def test_none_format_rejected(self) -> None:
        with pytest.raises(FormatNotSupportedException):
            ParserRouter().route(None)

    def test_register_adapter(self) -> None:
        from atlas_richie.document_parser import DocumentSummary

        class _Stub:
            def parse(self, source, context=None):
                yield Finished(DocumentSummary(), 0, 0)

        router = ParserRouter()
        router.register(Format.PDF, _Stub())
        assert Format.PDF in router.registered_formats()
        assert isinstance(router.route(Format.PDF), _Stub)

    def test_parse_bytes_routes_by_content(self) -> None:
        events = list(ParserRouter().parse(BytesSource(b"hello\n\nworld", "x.txt")))
        assert [e.segment.text for e in events if isinstance(e, Streaming)] == ["hello", "world"]

    def test_parse_file_detects_and_routes(self, tmp_path: Path) -> None:
        path = tmp_path / "notes.md"
        path.write_text("# Title\n\nbody", encoding="utf-8")
        events = list(ParserRouter().parse_file(path))
        assert [e.segment.text for e in events if isinstance(e, Streaming)] == ["# Title", "body"]

    def test_parse_stream_rewinds_after_sniffing(self) -> None:
        stream = io.BytesIO(b"alpha\n\nbeta")
        events = list(ParserRouter().parse(StreamSource(stream, "s.txt")))
        assert [e.segment.text for e in events if isinstance(e, Streaming)] == ["alpha", "beta"]

    def test_url_source_must_be_downloaded_first(self) -> None:
        with pytest.raises(FormatNotSupportedException, match="URL"):
            list(ParserRouter().parse(UrlSource("https://example.com/a.txt")))


class TestChunkingChain:
    def test_parse_then_chunk(self) -> None:
        """The two components compose into the RAG preprocessing chain."""
        from atlas_richie.chunking_core import ChunkingRule, DefaultChunkingService, Strategy

        text = "\n\n".join(f"Paragraph {i} with some content." for i in range(12))
        events = list(ParserRouter().parse(BytesSource(text.encode(), "doc.txt")))
        segments = [e.segment.text for e in events if isinstance(e, Streaming)]
        assert len(segments) == 12
        result = DefaultChunkingService().chunk(
            "\n\n".join(segments), ChunkingRule("r", "1", Strategy.PARAGRAPH, 60, 0)
        )
        assert result.chunks
        assert all(c.text for c in result.chunks)
