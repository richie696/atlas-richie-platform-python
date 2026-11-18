"""HTML 适配器：块级切分、去脚本、标题、内联图片、超时与路由。"""

from __future__ import annotations

import base64
from datetime import timedelta

import pytest

from atlas_richie.document_parser import (
    BytesSource,
    Failed,
    Finished,
    Format,
    FormatNotSupportedException,
    ImageStreaming,
    ParserContext,
    ParserRouter,
    Streaming,
    UrlSource,
)
from atlas_richie.document_parser_html import BLOCK_TAGS, HtmlParser

pytestmark = pytest.mark.unit

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n fake").decode()


def _source(html: str, name: str = "page.html") -> BytesSource:
    return BytesSource(html.encode("utf-8"), name=name)


def _events(html: str, context=None, **kwargs):
    return list(HtmlParser(**kwargs).parse(_source(html), context))


def _texts(events):
    return [e.segment.text for e in events if isinstance(e, Streaming)]


class TestBlockSegmentation:
    def test_each_block_is_a_segment(self) -> None:
        events = _events("<html><body><p>one</p><p>two</p><h1>title</h1></body></html>")
        assert _texts(events) == ["one", "two", "title"]

    def test_nested_blocks_do_not_duplicate_text(self) -> None:
        events = _events("<div><p>inner</p></div>")
        assert _texts(events) == ["inner"], "只取最内层块，父子不得重复"

    def test_deeply_nested_blocks(self) -> None:
        events = _events("<div><div><p>deep</p></div></div>")
        assert _texts(events) == ["deep"]

    def test_table_cells_are_segments(self) -> None:
        events = _events("<table><tr><td>a</td><th>b</th></tr></table>")
        assert _texts(events) == ["a", "b"]

    def test_list_items_are_segments(self) -> None:
        events = _events("<ul><li>x</li><li>y</li></ul>")
        assert _texts(events) == ["x", "y"]

    def test_inline_tags_are_flattened_into_the_block(self) -> None:
        events = _events("<p>Hello <b>bold</b> and <i>italic</i></p>")
        assert _texts(events) == ["Hello bold and italic"]

    def test_empty_blocks_are_skipped(self) -> None:
        events = _events("<p></p><p>  </p><p>real</p>")
        assert _texts(events) == ["real"]

    def test_all_java_block_tags_are_covered(self) -> None:
        assert {"p", "div", "td", "th", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                "pre", "blockquote"} == set(BLOCK_TAGS)

    def test_preformatted_text_kept(self) -> None:
        events = _events("<pre>code line</pre>")
        assert _texts(events) == ["code line"]


class TestSanitisation:
    def test_script_and_style_removed(self) -> None:
        events = _events(
            "<html><head><style>p{color:red}</style></head>"
            "<body><script>alert('x')</script><p>safe</p></body></html>"
        )
        assert _texts(events) == ["safe"]

    def test_noscript_and_template_removed(self) -> None:
        events = _events("<noscript><p>no</p></noscript><template><p>t</p></template><p>yes</p>")
        assert _texts(events) == ["yes"]

    def test_title_extracted(self) -> None:
        events = _events("<html><head><title>My Page</title></head><body><p>x</p></body></html>")
        finished = next(e for e in events if isinstance(e, Finished))
        assert finished.summary.title == "My Page"

    def test_no_title_is_none(self) -> None:
        events = _events("<p>x</p>")
        assert next(e for e in events if isinstance(e, Finished)).summary.title is None


class TestMetadata:
    def test_section_path_and_tag(self) -> None:
        events = _events("<p>a</p><h2>b</h2>")
        segments = [e.segment for e in events if isinstance(e, Streaming)]
        assert segments[0].section_path == "/page.html/Block[1]"
        assert segments[0].metadata["tag"] == "p"
        assert segments[1].metadata["tag"] == "h2"
        assert segments[0].metadata["format"] == "text/html"

    def test_finished_counts(self) -> None:
        events = _events("<p>a</p><p>b</p>")
        finished = next(e for e in events if isinstance(e, Finished))
        assert finished.segment_count == 2
        assert finished.image_count == 0

    def test_max_segment_length_splits(self) -> None:
        events = _events("<p>" + "x" * 50 + "</p>", ParserContext(max_segment_length=10))
        texts = _texts(events)
        assert len(texts) == 5
        assert all(len(t) == 10 for t in texts)


class TestImages:
    def test_no_images_by_default(self) -> None:
        events = _events(f'<p>x</p><img src="data:image/png;base64,{PNG}">')
        assert not any(isinstance(e, ImageStreaming) for e in events)

    def test_data_uri_image_emitted(self) -> None:
        events = _events(
            f'<p>x</p><img src="data:image/png;base64,{PNG}" alt="pic">',
            ParserContext(emit_images=True),
        )
        images = [e for e in events if isinstance(e, ImageStreaming)]
        assert len(images) == 1
        assert images[0].image.mime_type == "image/png"
        assert images[0].image.data.startswith(b"\x89PNG")
        assert images[0].image.metadata["alt"] == "pic"

    def test_remote_src_is_not_fetched(self) -> None:
        events = _events(
            '<img src="https://example.com/a.png"><p>x</p>',
            ParserContext(emit_images=True),
        )
        assert not any(isinstance(e, ImageStreaming) for e in events)
        assert _texts(events) == ["x"]

    def test_oversized_image_skipped(self) -> None:
        events = _events(
            f'<img src="data:image/png;base64,{PNG}">',
            ParserContext(emit_images=True),
            max_embedded_image_bytes=1,
        )
        assert not any(isinstance(e, ImageStreaming) for e in events)

    def test_malformed_data_uri_skipped(self) -> None:
        events = _events('<img src="data:image/png;base64,!!!not-base64!!!">', ParserContext(emit_images=True))
        assert not any(isinstance(e, ImageStreaming) for e in events)

    def test_invalid_cap_rejected(self) -> None:
        with pytest.raises(ValueError):
            HtmlParser(max_embedded_image_bytes=0)


class TestFailureModes:
    def test_url_source_rejected(self) -> None:
        events = list(HtmlParser().parse(UrlSource("https://example.com")))
        assert isinstance(events[-1], Failed)
        assert isinstance(events[-1].error, FormatNotSupportedException)

    def test_timeout_becomes_failed(self) -> None:
        events = _events("<p>a</p><p>b</p>", ParserContext(timeout=timedelta(microseconds=1)))
        assert isinstance(events[-1], Failed)
        assert "timeout" in str(events[-1].error)

    def test_empty_document_still_finishes(self) -> None:
        events = _events("")
        assert isinstance(events[-1], Finished)
        assert events[-1].segment_count == 0


class TestListenerAndRouter:
    def test_listener_receives_events(self) -> None:
        calls: list[str] = []

        class _Rec:
            def on_streaming(self, *a) -> None: calls.append("s")
            def on_image(self, *a) -> None: calls.append("i")
            def on_finished(self, *a) -> None: calls.append("f")
            def on_error(self, *a) -> None: calls.append("e")

        _events("<p>a</p>", listener=_Rec())
        assert calls == ["s", "f"]

    def test_broken_listener_does_not_break_parsing(self) -> None:
        class _Broken:
            def on_streaming(self, *a) -> None: raise RuntimeError("down")
            def on_image(self, *a) -> None: raise RuntimeError("down")
            def on_finished(self, *a) -> None: raise RuntimeError("down")
            def on_error(self, *a) -> None: raise RuntimeError("down")

        assert _texts(_events("<p>a</p>", listener=_Broken())) == ["a"]

    def test_router_html_and_xml(self) -> None:
        router = ParserRouter({Format.HTML: HtmlParser(), Format.XML: HtmlParser()})
        assert _texts(list(router.parse(_source("<html><body><p>h</p></body></html>")))) == ["h"]
        xml = BytesSource(b"<?xml version='1.0'?><root><p>x</p></root>", name="d.xml")
        assert _texts(list(router.parse(xml))) == ["x"]

    def test_markup_in_txt_still_uses_text_fast_path(self) -> None:
        """与 A5 修复联动：.txt 含 markup 不应被路由到 HTML。"""
        router = ParserRouter({Format.HTML: HtmlParser()})
        events = list(router.parse(BytesSource(b"<html>hi</html>", name="notes.txt")))
        assert not any(isinstance(e, Failed) for e in events)


class TestXmlHandling:
    def test_xml_declaration_selects_xml_parser_without_warning(self) -> None:
        import warnings

        from bs4 import XMLParsedAsHTMLWarning

        with warnings.catch_warnings():
            warnings.simplefilter("error", XMLParsedAsHTMLWarning)
            events = list(
                HtmlParser().parse(
                    BytesSource(b"<?xml version='1.0'?><root><p>x</p></root>", name="d.xml")
                )
            )
        assert _texts(events) == ["x"]

    def test_explicit_features_override_is_respected(self) -> None:
        events = list(
            HtmlParser(features="html.parser").parse(_source("<p>a</p>"))
        )
        assert _texts(events) == ["a"]
