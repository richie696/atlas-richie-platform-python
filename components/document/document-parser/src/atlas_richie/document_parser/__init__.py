"""Document parsing: format detection, streaming events, fetch policy, routing.

Zero runtime dependencies. Heavy format parsers (PDF/Office) are registered by
adapter packages so the core stays light. Pairs with `atlas-richie-chunking-core`
to form the RAG preprocessing chain: parse into segments, then chunk.
"""

import importlib.metadata

from .detection import SNIFF_BUFFER_SIZE, detect_format, from_extension, sniff, to_format
from .model import (
    BytesSource,
    DocumentParseException,
    DocumentSegment,
    DocumentSummary,
    Failed,
    FileSource,
    Finished,
    Format,
    FormatNotSupportedException,
    ImageOnlyPdfException,
    ImageSegment,
    ImageStreaming,
    ParseEvent,
    ParserContext,
    ParserSource,
    Streaming,
    StreamSource,
    UrlSource,
)
from .listener import ListenerBus, ParseListener, dispatch_event
from .policy import CidrBlock, UrlFetchPolicy
from .router import DocumentParser, ParserRouter
from .text import TextFastPathParser, supports

__version__ = importlib.metadata.version("atlas-richie-document-parser")

__all__ = [
    "SNIFF_BUFFER_SIZE",
    "BytesSource",
    "CidrBlock",
    "DocumentParseException",
    "DocumentParser",
    "DocumentSegment",
    "DocumentSummary",
    "Failed",
    "FileSource",
    "Finished",
    "Format",
    "FormatNotSupportedException",
    "ImageOnlyPdfException",
    "ImageSegment",
    "ImageStreaming",
    "ParseEvent",
    "ParserContext",
    "ParserRouter",
    "ParserSource",
    "Streaming",
    "StreamSource",
    "TextFastPathParser",
    "UrlFetchPolicy",
    "ParseListener",
    "ListenerBus",
    "dispatch_event",
    "UrlSource",
    "__version__",
    "detect_format",
    "from_extension",
    "sniff",
    "supports",
    "to_format",
]
