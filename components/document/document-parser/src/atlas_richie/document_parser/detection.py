"""Format detection: magic-byte sniffing, MIME mapping and extension fallback.

The Java side delegates sniffing to Tika's `MimeTypes`. This module reproduces the
same *decision order* — content first, extension as fallback — with pure
standard-library magic-byte checks, so the core carries no Tika-equivalent
dependency.

OOXML/ODF detection inside a ZIP container is a heuristic over the sniff buffer
(the container's member names), not a full ZIP parse: the buffer is only the first
8 KiB and may be truncated. Legacy OLE2 files cannot be distinguished into
DOC/XLS/PPT from magic bytes alone, so they map to UNKNOWN and the extension
fallback decides — the same outcome Tika reaches via deeper inspection.
"""

from __future__ import annotations

from .model import Format

SNIFF_BUFFER_SIZE = 8192

_MIME_TO_FORMAT = {
    "application/pdf": Format.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": Format.DOCX,
    "application/msword": Format.DOC,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": Format.XLSX,
    "application/vnd.ms-excel": Format.XLS,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": Format.PPTX,
    "application/vnd.ms-powerpoint": Format.PPT,
    "application/vnd.oasis.opendocument.text": Format.ODT,
    "application/vnd.oasis.opendocument.spreadsheet": Format.ODS,
    "application/vnd.oasis.opendocument.presentation": Format.ODP,
    "application/rtf": Format.RTF,
    "text/rtf": Format.RTF,
    "text/plain": Format.TXT,
    "text/markdown": Format.MD,
    "text/x-markdown": Format.MD,
    "text/html": Format.HTML,
    "text/xml": Format.XML,
    "application/xml": Format.XML,
}

_EXTENSION_TO_FORMAT = {
    ".pdf": Format.PDF,
    ".docx": Format.DOCX,
    ".doc": Format.DOC,
    ".xlsx": Format.XLSX,
    ".xls": Format.XLS,
    ".pptx": Format.PPTX,
    ".ppt": Format.PPT,
    ".odt": Format.ODT,
    ".ods": Format.ODS,
    ".odp": Format.ODP,
    ".rtf": Format.RTF,
    ".txt": Format.TXT,
    ".md": Format.MD,
    ".markdown": Format.MD,
    ".html": Format.HTML,
    ".htm": Format.HTML,
    ".xml": Format.XML,
}

_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def to_format(media_type: str | None) -> Format:
    if not media_type:
        return Format.UNKNOWN
    base = media_type.split(";", 1)[0].strip().lower()
    return _MIME_TO_FORMAT.get(base, Format.UNKNOWN)


def from_extension(name_hint: str | None) -> Format:
    if not name_hint:
        return Format.UNKNOWN
    lower = name_hint.lower()
    for extension, fmt in _EXTENSION_TO_FORMAT.items():
        if lower.endswith(extension):
            return fmt
    return Format.UNKNOWN


def sniff(head: bytes) -> str:
    """Return a MIME type for the leading bytes, or application/octet-stream."""
    if not head:
        return "application/octet-stream"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(_OLE2_MAGIC):
        return "application/x-ole-storage"
    if head.startswith(b"{\\rtf"):
        return "application/rtf"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        return _sniff_zip(head)
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    lowered = stripped[:512].lower()
    if lowered.startswith(b"<!doctype html") or lowered.startswith(b"<html"):
        return "text/html"
    if lowered.startswith(b"<?xml"):
        return "application/xml"
    if b"\x00" in head:
        return "application/octet-stream"
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    if stripped.startswith(b"<"):
        return "text/html"
    return "text/plain"


def _sniff_zip(head: bytes) -> str:
    if b"mimetype" in head:
        if b"opendocument.text" in head:
            return "application/vnd.oasis.opendocument.text"
        if b"opendocument.spreadsheet" in head:
            return "application/vnd.oasis.opendocument.spreadsheet"
        if b"opendocument.presentation" in head:
            return "application/vnd.oasis.opendocument.presentation"
    if b"word/" in head:
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if b"xl/" in head:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if b"ppt/" in head:
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    return "application/zip"


_TEXT_FAMILY = frozenset({Format.TXT, Format.MD, Format.HTML, Format.XML})
_EXPLICIT_TEXT = frozenset({Format.TXT, Format.MD})


def detect_format(head: bytes, name_hint: str | None = None) -> Format:
    """Content sniffing first, extension fallback when content is inconclusive.

    Exception: HTML/XML sniffing is a weak heuristic (any leading `<` triggers
    it), so an explicit `.txt`/`.md` name overrides a text-family verdict —
    otherwise a text file that merely contains markup becomes unparseable.
    Binary magic (PDF/ZIP/OLE2/RTF) is strong evidence and always wins.
    """
    fmt = to_format(sniff(head))
    named = from_extension(name_hint)
    if fmt is Format.UNKNOWN:
        return named
    if fmt in _TEXT_FAMILY and named in _EXPLICIT_TEXT:
        return named
    return fmt


__all__ = [
    "SNIFF_BUFFER_SIZE",
    "detect_format",
    "from_extension",
    "sniff",
    "to_format",
]
