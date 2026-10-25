"""Loopback-only TCP fault proxy for isolated Nacos Runtime acceptance.

The proxy forwards only to the local Nacos HTTP and gRPC ports. Its control
server can pause/resume forwarding and closes established tunnels when paused,
so a test can exercise outage and recovery without stopping Nacos itself.
It must never be bound to a non-loopback interface.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

_LOOPBACK = "127.0.0.1"
_UPSTREAMS = {"http": ("127.0.0.1", 8848), "grpc": ("127.0.0.1", 9848)}


def _port(value: str) -> int:
    port = int(value)
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


@dataclass(slots=True)
class NacosFaultProxy:
    """Own loopback-only Nacos tunnels and a local pause/resume control port."""

    http_port: int = 18848
    grpc_port: int = 19848
    control_port: int = 18849
    _forwarding: bool = field(default=True, init=False, repr=False)
    _pairs: set[tuple[asyncio.StreamWriter, asyncio.StreamWriter]] = field(
        default_factory=set, init=False, repr=False
    )
    _servers: list[asyncio.AbstractServer] = field(
        default_factory=list, init=False, repr=False
    )

    async def start(self) -> None:
        """Bind the three servers to IPv4 loopback only."""
        ports = (self.http_port, self.grpc_port, self.control_port)
        if len(set(ports)) != len(ports):
            raise ValueError("proxy listener ports must be distinct")
        self._servers = [
            await asyncio.start_server(
                self._proxy_handler(*_UPSTREAMS["http"]), _LOOPBACK, self.http_port
            ),
            await asyncio.start_server(
                self._proxy_handler(*_UPSTREAMS["grpc"]), _LOOPBACK, self.grpc_port
            ),
            await asyncio.start_server(
                self._control_handler, _LOOPBACK, self.control_port
            ),
        ]

    def _proxy_handler(
        self, upstream_host: str, upstream_port: int
    ) -> Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]:
        async def handle(
            client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
        ) -> None:
            upstream_writer: asyncio.StreamWriter | None = None
            try:
                if not self._forwarding:
                    return
                upstream_reader, upstream_writer = await asyncio.open_connection(
                    upstream_host, upstream_port
                )
                pair = (client_writer, upstream_writer)
                self._pairs.add(pair)
                copy_tasks = {
                    asyncio.create_task(self._copy(client_reader, upstream_writer)),
                    asyncio.create_task(self._copy(upstream_reader, client_writer)),
                }
                _, pending = await asyncio.wait(
                    copy_tasks, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                self._pairs.discard(pair)
            except (ConnectionError, OSError, asyncio.CancelledError):
                pass
            finally:
                await self._close_writer(client_writer)
                if upstream_writer is not None:
                    await self._close_writer(upstream_writer)

        return handle

    @staticmethod
    async def _copy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while chunk := await reader.read(64 * 1024):
            writer.write(chunk)
            await writer.drain()

    async def _control_handler(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            peer = writer.get_extra_info("peername")
            if not peer or not ipaddress.ip_address(peer[0]).is_loopback:
                await self._respond(writer, 403, "loopback only")
                return
            request_line = await asyncio.wait_for(reader.readline(), timeout=2)
            method, path, *_ = (
                request_line.decode("ascii", "replace").strip().split(" ")
            )
            while header := await asyncio.wait_for(reader.readline(), timeout=2):
                if header in (b"\r\n", b"\n"):
                    break
            if method != "POST" or path not in ("/pause", "/resume"):
                await self._respond(writer, 404, "not found")
            elif path == "/pause":
                await self.pause()
                await self._respond(writer, 200, "paused")
            else:
                self._forwarding = True
                await self._respond(writer, 200, "forwarding")
        except (TimeoutError, UnicodeError, ValueError):
            await self._respond(writer, 400, "invalid request")
        finally:
            await self._close_writer(writer)

    async def pause(self) -> None:
        """Reject new tunnels and close every currently established tunnel."""
        self._forwarding = False
        writers = {writer for pair in self._pairs for writer in pair}
        for writer in writers:
            writer.close()
        if writers:
            await asyncio.gather(
                *(self._close_writer(writer) for writer in writers),
                return_exceptions=True,
            )
        self._pairs.clear()

    @staticmethod
    async def _respond(writer: asyncio.StreamWriter, status: int, message: str) -> None:
        body = f"{message}\n".encode("ascii")
        writer.write(
            f"HTTP/1.1 {status} {'OK' if status == 200 else 'Error'}\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii")
            + body
        )
        await writer.drain()

    @staticmethod
    async def _close_writer(writer: asyncio.StreamWriter) -> None:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass

    async def close(self) -> None:
        """Close listeners and all accepted tunnels."""
        for server in self._servers:
            server.close()
        await asyncio.gather(*(server.wait_closed() for server in self._servers))
        await self.pause()


async def _serve(proxy: NacosFaultProxy) -> None:
    await proxy.start()
    print(
        f"loopback Nacos fault proxy ready: HTTP {proxy.http_port}, "
        f"gRPC {proxy.grpc_port}, control {proxy.control_port}; "
        "upstream is fixed to 127.0.0.1:8848/9848",
        flush=True,
    )
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stopped.set)
    try:
        await stopped.wait()
    finally:
        await proxy.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http-port", type=_port, default=18848)
    parser.add_argument("--grpc-port", type=_port, default=19848)
    parser.add_argument("--control-port", type=_port, default=18849)
    args = parser.parse_args()
    asyncio.run(
        _serve(
            NacosFaultProxy(
                http_port=args.http_port,
                grpc_port=args.grpc_port,
                control_port=args.control_port,
            )
        )
    )


if __name__ == "__main__":
    main()
