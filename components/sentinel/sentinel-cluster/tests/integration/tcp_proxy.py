"""M6.4.1 TCP proxy (网络故障注入工具).

中文
----
简单 TCP forwarder, 跑在独立 asyncio event loop. 0 3rd-party 依赖.

**目的** (M6.4 子任务验证需要):

- **网络不可达**: kill proxy → Client 连接被 RST
- **网络分区**: kill proxy + 持续 N 秒 → Client 走 ClusterFailurePolicy
- **送达但响应丢失**: proxy 收到包但延迟 N 秒再转 (模拟慢响应, Client deadline 超时)

**反例** (1.0 不引入):

- ❌ toxiproxy (1.0 简化, 0 3rd-party)
- ❌ docker network (依赖 docker daemon, 1.0 不依赖)
- ❌ iptables / tc (需要 root, 1.0 简化)

English
--------
Simple TCP forwarder on its own asyncio event loop. 0 3rd-party.

Use cases (M6.4 sub-tasks need):

- **Network unreachable**: kill proxy → Client gets RST
- **Network partition**: kill proxy for N seconds → Client goes ClusterFailurePolicy
- **Sent but no response**: proxy delays forwarding N seconds (Client deadline
  triggers)

Anti-patterns (1.0 forbidden):

- ❌ toxiproxy (1.0 0 3rd-party)
- ❌ docker network (depends on docker daemon, 1.0 not depending on it)
- ❌ iptables / tc (needs root, 1.0 simplification)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Sequence

_log = logging.getLogger("atlas_richie.sentinel_cluster.tests.integration.tcp_proxy")


class TcpProxy:
    """TCP forwarder: listen on (host, port) → forward to (target_host, target_port).

    1.0 简化:

    - 单 connection forward (1 个 client → 1 个 server connection)
    - 同时多 connection OK (每 connection 1 task)
    - Bytes level forwarding (不解析 HTTP, 不解析任何协议)
    - 控制 API 通过 stdin (跟 pytest 主进程通信)
    """

    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        target_host: str,
        target_port: int,
    ) -> None:
        self._listen_host = listen_host
        self._listen_port = listen_port
        self._target_host = target_host
        self._target_port = target_port
        self._server: asyncio.base_events.Server | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._bound_port: int | None = None
        # 故障注入
        self._forward_delay_s: float = 0.0

    @property
    def bound_port(self) -> int | None:
        """实际绑定的端口 (如果 listen_port=0, 用于 driver 拿 ephemeral port)."""
        return self._bound_port

    async def start(self) -> None:
        """启动 forwarder. 阻塞直到 ``stop()`` / ``kill()``."""
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self._listen_host,
            port=self._listen_port,
            reuse_address=True,
        )
        assert self._server is not None
        # 拿真实端口 (如果是 ephemeral)
        socks = self._server.sockets
        if socks:
            self._bound_port = socks[0].getsockname()[1]
        _log.info(
            "tcp_proxy started: %s:%d → %s:%d (bound_port=%s)",
            self._listen_host,
            self._listen_port,
            self._target_host,
            self._target_port,
            self._bound_port,
        )
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """停止 (graceful). cancel 所有 active connection, 关闭 listener."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        # cancel 所有 active connection tasks
        for task in list(self._tasks):
            task.cancel()
        # 等所有 task 结束
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        _log.info("tcp_proxy stopped")

    def set_forward_delay(self, delay_s: float) -> None:
        """设置转发延迟 (用于"送达但响应丢失"场景)."""
        self._forward_delay_s = delay_s

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """处理单个 client connection."""
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        try:
            # 连 target
            try:
                target_reader, target_writer = await asyncio.open_connection(
                    self._target_host, self._target_port
                )
            except (ConnectionRefusedError, OSError) as e:
                _log.warning("tcp_proxy: target connection failed: %s", e)
                writer.close()
                return
            try:
                # 双向 forward
                await asyncio.gather(
                    self._forward(reader, target_writer),
                    self._forward(target_reader, writer),
                    return_exceptions=True,
                )
            finally:
                try:
                    target_writer.close()
                    await target_writer.wait_closed()
                except Exception:  # pragma: no cover
                    pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # pragma: no cover
                pass
            if task is not None:
                self._tasks.discard(task)

    async def _forward(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """单方向 forward: reader → writer. 1.0 简化: 一次性 read until EOF."""
        try:
            while True:
                if self._forward_delay_s > 0:
                    await asyncio.sleep(self._forward_delay_s)
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass


# ---------------------------------------------------------------------------
# CLI entry point (subprocess 启动)
# ---------------------------------------------------------------------------


async def _run_proxy(args: argparse.Namespace) -> int:
    """proxy 异步 main: 启动 → 读 stdin 命令 (stop / kill) → 退出."""
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    proxy = TcpProxy(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        target_host=args.target_host,
        target_port=args.target_port,
    )

    # 启动 proxy (后台 task)
    proxy_task = asyncio.create_task(proxy.start())

    # 等到 proxy 启动完成
    while proxy.bound_port is None:
        await asyncio.sleep(0.05)

    # 第一个 stdout 行: bound port (driver 拿这个)
    sys.stdout.write(f"BOUND_PORT={proxy.bound_port}\n")
    sys.stdout.flush()

    # 读 stdin 命令
    loop = asyncio.get_running_loop()
    stdin_reader = asyncio.StreamReader()
    stdin_protocol = asyncio.StreamReaderProtocol(stdin_reader)
    try:
        await loop.connect_read_pipe(lambda: stdin_protocol, sys.stdin)
    except Exception as e:
        _log.error("failed to attach stdin: %s", e)
        proxy_task.cancel()
        return 2

    try:
        while True:
            line = await stdin_reader.readline()
            if not line:
                break
            cmd = line.decode("ascii", errors="replace").strip()
            if cmd == "stop":
                # graceful stop
                await proxy.stop()
                proxy_task.cancel()
                try:
                    await proxy_task
                except (asyncio.CancelledError, Exception):
                    pass
                sys.stdout.write("OK\n")
                sys.stdout.flush()
                return 0
            elif cmd.startswith("delay "):
                # delay <seconds>
                try:
                    delay = float(cmd.split(" ", 1)[1])
                    proxy.set_forward_delay(delay)
                    sys.stdout.write(f"OK delay={delay}\n")
                    sys.stdout.flush()
                except ValueError as e:
                    sys.stdout.write(f"ERR {e}\n")
                    sys.stdout.flush()
            elif cmd == "quit":
                return 0
            else:
                sys.stdout.write(f"ERR unknown command: {cmd!r}\n")
                sys.stdout.flush()
    except asyncio.CancelledError:
        pass
    finally:
        if not proxy_task.done():
            proxy_task.cancel()
            try:
                await proxy_task
            except (asyncio.CancelledError, Exception):
                pass
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主入口. python -m tcp_proxy [args]."""
    parser = argparse.ArgumentParser(
        prog="tcp_proxy",
        description="M6.4 TCP forwarder (网络故障注入工具)",
    )
    parser.add_argument(
        "--listen-host", default="127.0.0.1", help="监听地址 (default 127.0.0.1)"
    )
    parser.add_argument(
        "--listen-port", type=int, default=0, help="监听端口 (0 = ephemeral)"
    )
    parser.add_argument("--target-host", required=True, help="转发目标 host")
    parser.add_argument("--target-port", type=int, required=True, help="转发目标端口")
    parser.add_argument(
        "--log-level", default="INFO", help="日志级别 (default INFO)"
    )
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run_proxy(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
