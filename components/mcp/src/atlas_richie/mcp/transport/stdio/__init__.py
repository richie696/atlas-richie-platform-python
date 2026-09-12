"""换行定界 JSON 的 stdio 帧解析，stdout 严格保留给协议帧。

中文
----
三个核心函数：

- `decode_line(line)`：把一行 UTF-8 JSON 解码为对象；非换行结尾或解码失败
  抛 `ProtocolError(-32700, "Parse error", ...)`。
- `encode_line(payload)`：把对象编码为紧凑 JSON 加上换行。
- `serve_stdio(server, reader, writer)`：阻塞读 → `server.handle` → 写响应，
  直至 EOF。**永远不会向 stdout 写诊断信息**（任何异常 → 错误响应帧）。

设计动机：stdio 通道是协议独占流，进程日志必须走 stderr / 日志文件，
否则会污染对端的 framing。

English
--------
Newline-delimited JSON stdio framing with stdout reserved for protocol
frames.

Three core functions:

- `decode_line(line)`: decode one line of UTF-8 JSON; raise
  `ProtocolError(-32700, "Parse error", ...)` on missing trailing
  newline or decode failure.
- `encode_line(payload)`: encode an object as compact JSON with a
  trailing newline.
- `serve_stdio(server, reader, writer)`: read until EOF, dispatch each
  line to `server.handle`, write the response frame. **Never writes
  diagnostics to the protocol stdout** (any decode failure is reported
  as a JSON-RPC error frame).

Design motivation: the stdio channel is a protocol-exclusive stream;
process logs must go to stderr / a log file, or the peer's framing
gets corrupted.

Mirrors `cn.richie696.component.mcp.transport.stdio.McpStdioFrameCodec`
(Java — same newline-delimited framing, narrower Python surface).
"""

import asyncio
import json
from typing import BinaryIO

from atlas_richie.mcp.errors import ProtocolError
from atlas_richie.mcp.server import McpServer


def decode_line(line: bytes) -> object:
    """中文
    ----
    解码一行 UTF-8 JSON；非换行结尾或解码失败抛 `ProtocolError(-32700)`。

    Args:
        line: 包含一个 JSON 对象 + 末尾换行的字节串。

    Returns:
        反序列化后的 Python 对象。

    Raises:
        ProtocolError: 行不以换行结尾，或 UTF-8 / JSON 解码失败。

    English
    --------
    Decode exactly one UTF-8 JSON line; raise
    `ProtocolError(-32700, "Parse error", ...)` on missing trailing
    newline or decode failure.

    Args:
        line: a byte string containing one JSON object plus a trailing
            newline.

    Returns:
        the deserialised Python object.

    Raises:
        ProtocolError: if the line is not newline-terminated or
            UTF-8 / JSON decoding fails.
    """

    if not line.endswith(b"\n"):
        raise ProtocolError(-32700, "Parse error", {"reason": "newline_required"})
    try:
        return json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(-32700, "Parse error", {"reason": str(error)}) from error


def encode_line(payload: object) -> bytes:
    """中文
    ----
    把对象编码为紧凑 JSON 后追加换行（一个完整的协议帧）。

    Args:
        payload: 任意可 JSON 序列化的对象。

    Returns:
        UTF-8 字节串，以换行结尾。

    English
    --------
    Encode one JSON value as a compact newline-delimited protocol
    frame.

    Args:
        payload: any JSON-serialisable object.

    Returns:
        a UTF-8 byte string ending with a newline.
    """

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


async def serve_stdio(server: McpServer, reader: BinaryIO, writer: BinaryIO) -> None:
    """中文
    ----
    阻塞 stdio 循环：读一行 → `server.handle` → 写响应，直至 EOF。

    永不向 stdout 写诊断信息 —— 解析失败转写为 `id=null` 的 JSON-RPC 错误帧；
    其余 `ProtocolError` 由 `server.handle` 转为标准 error 响应。

    Args:
        server: 已配置的 `McpServer`。
        reader: 协议帧输入流（通常是 `sys.stdin.buffer`）。
        writer: 协议帧输出流（通常是 `sys.stdout.buffer`）。

    English
    --------
    Serve until EOF, never writing diagnostics to the protocol stdout
    stream.

    Args:
        server: a configured `McpServer`.
        reader: the protocol frame input stream (typically
            `sys.stdin.buffer`).
        writer: the protocol frame output stream (typically
            `sys.stdout.buffer`).
    """

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
