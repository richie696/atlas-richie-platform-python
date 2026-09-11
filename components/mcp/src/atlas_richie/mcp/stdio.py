"""Newline-delimited JSON stdio framing with stdout reserved for protocol frames."""

import asyncio
import json
from typing import BinaryIO

from .errors import ProtocolError
from .server import McpServer


def decode_line(line: bytes) -> object:
    """Decode exactly one non-empty UTF-8 JSON line."""

    if not line.endswith(b"\n"):
        raise ProtocolError(-32700, "Parse error", {"reason": "newline_required"})
    try:
        return json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(-32700, "Parse error", {"reason": str(error)}) from error


def encode_line(payload: object) -> bytes:
    """Encode one JSON value as a compact newline-delimited protocol frame."""

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


async def serve_stdio(server: McpServer, reader: BinaryIO, writer: BinaryIO) -> None:
    """Serve until EOF, never writing diagnostics to the protocol stdout stream."""

    while line := await asyncio.to_thread(reader.readline):
        try:
            payload = decode_line(line)
        except ProtocolError as error:
            writer.write(encode_line({"jsonrpc": "2.0", "id": None, "error": error.as_json()}))
            writer.flush()
            continue
        response = await server.handle(payload)
        if response is not None:
            writer.write(encode_line(response))
            writer.flush()
