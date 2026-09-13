"""M6.4.1 双 Agent 验收夹具 (pytest conftest).

中文
----
M6.4 双 Agent 真实网络故障与恢复验收夹具:

- **Server subprocess** (P1): 跑 ``StandaloneTokenServer`` CLI, 真实端口
- **TCP Proxy subprocess** (P2): 转发 Client → Server, 故障注入用
- **Client Agent A** (P3): 真实 RemoteTokenService 进程, 独立 instance_id
- **Client Agent B** (P4): 同上, 独立 instance_id

测试 driver (pytest 主进程) 通过:

- Server CLI 的 ``--bind 127.0.0.1:0`` (ephemeral port) + 解析 stdout 拿 bound port
- Proxy CLI 的 stdin ``BOUND_PORT=...`` 协议
- Agent CLI 的 stdin/stdout JSON 协议

**故障注入** (M6.4.4 用):

- ``proxy.kill()`` → Client 端连接被 RST → ClusterFailurePolicy
- ``proxy.set_forward_delay(N)`` → 模拟送达但响应丢失
- ``proxy.restart()`` → 网络恢复

**反例** (1.0 拒绝):

- ❌ 共享 event loop (M6.7 决策, 不能跨进程)
- ❌ mock callback (M6.1.7d 决策, 不用 fake 宣称完成)
- ❌ 任何 3rd-party (toxiproxy / docker network / iptables / tc)
- ❌ pickle (跨进程 dataclass 不可靠)

English
--------
M6.4 dual-Agent acceptance harness:

- **Server subprocess** (P1): real StandaloneTokenServer CLI
- **TCP Proxy subprocess** (P2): forwards Client → Server, fault injection
- **Client Agent A** (P3): real RemoteTokenService process, independent instance_id
- **Client Agent B** (P4): same, independent instance_id

Test driver (pytest main process) via:

- Server ``--bind 127.0.0.1:0`` + parse stdout for bound port
- Proxy stdin ``BOUND_PORT=...`` protocol
- Agent stdin/stdout JSON protocol
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

import pytest


# ---------------------------------------------------------------------------
# 进程包装 (小 helper, 不用 multiprocessing 因为要 stdio 流)
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """找一个当前空闲的端口 (subprocess 启动前)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class SubprocessProc:
    """subprocess 包装, 含 stdin/stdout 流 + lifecycle 控制."""

    proc: subprocess.Popen[bytes]
    stdin: IO[bytes]
    stdout: IO[bytes]

    def send_line(self, line: str) -> None:
        """写 1 行到 stdin (自动加 \\n)."""
        self.stdin.write((line + "\n").encode("utf-8"))
        self.stdin.flush()

    def read_line(self, timeout_s: float = 30.0) -> str:
        """读 1 行 stdout (同步阻塞, 用 timeout 防止 hang)."""
        import selectors

        sel = selectors.DefaultSelector()
        sel.register(self.stdout, selectors.EVENT_READ)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            ev = sel.select(timeout=deadline - time.time())
            if ev:
                line = self.stdout.readline()
                if line:
                    return line.decode("utf-8", errors="replace").rstrip("\n")
                # EOF
                raise EOFError("subprocess closed stdout")
        raise TimeoutError(f"read_line timeout after {timeout_s}s")

    def is_alive(self) -> bool:
        return self.proc.poll() is None

    def terminate(self, timeout_s: float = 5.0) -> None:
        """先 SIGTERM, 5s 后还活着 SIGKILL."""
        if not self.is_alive():
            return
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2.0)
        finally:
            for f in (self.stdin, self.stdout):
                try:
                    f.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Server subprocess
# ---------------------------------------------------------------------------


@dataclass
class ServerSubprocess:
    """StandaloneTokenServer 跑在独立 subprocess."""

    proc: SubprocessProc
    server_address: str  # e.g. "127.0.0.1:18765"
    auth_secret: str
    _tmp_config: Path | None = field(default=None, repr=False)

    def stop(self) -> None:
        self.proc.terminate()
        if self._tmp_config is not None and self._tmp_config.exists():
            try:
                self._tmp_config.unlink()
            except Exception:
                pass


def _start_server_subprocess(
    *,
    resources: list[dict[str, Any]],
    auth_secret: str = "m64-test-secret",
    bind_port: int | None = None,  # None = 自动找空闲端口
) -> ServerSubprocess:
    """启 1 个 StandaloneTokenServer subprocess. 返 bound address.

    Note: 不用 ``--bind 127.0.0.1:0`` (ephemeral) 因为 Server log 走 stderr
    不是 stdout, driver 拿不到 bound port. 1.0 简化: driver 先找空闲端口,
    显式 bind.
    """
    if bind_port is None or bind_port == 0:
        bind_port = _find_free_port()
    # 写临时 config.json (跟 ClusterTokenConfig.from_json schema 对齐)
    # 资源: resources[] + failure_policy_per_resource{} (1.0 split, 不合并)
    resource_names = [r["name"] for r in resources]
    cfg = {
        "name": "atlas-richie-sentinel-cluster",
        "version": "0.2.0",
        "cluster_token_mode": "standalone",
        "auth_secret": auth_secret,
        "bind_address": f"127.0.0.1:{bind_port}",
        "max_inflight": 64,
        "max_payload_bytes": 8192,
        "shutdown_timeout_s": 2.0,
        "request_timeout_ns": 5_000_000_000,
        "lease_ttl_ns": 30_000_000_000,
        "scrub_interval_ns": 1_000_000_000,
        "idempotency_ttl_ns": 300_000_000_000,
        "resources": [
            {"name": r["name"], "max_permits": r["max_permits"]}
            for r in resources
        ],
        "failure_policy_per_resource": {
            r["name"]: r["failure_policy"] for r in resources
        },
    }
    # Sanity: 每个 resource 必须在 failure_policy_per_resource 有 key
    assert set(resource_names) == set(cfg["failure_policy_per_resource"].keys())
    tmp_cfg = Path("/tmp") / f"m64-server-cfg-{uuid.uuid4()}.json"
    tmp_cfg.write_text(json.dumps(cfg, indent=2))
    # 启 subprocess
    repo_root = Path(__file__).resolve().parents[4]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        sys.executable,
        "-m",
        "atlas_richie.sentinel_cluster",
        "--bind",
        f"127.0.0.1:{bind_port}",
        "--config",
        str(tmp_cfg),
        "--auth-secret",
        auth_secret,
    ]
    p = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,  # 1.0: 保留 stderr, Server 启动错能看到
        cwd=str(repo_root),
        env=env,
    )
    proc = SubprocessProc(
        proc=p,
        stdin=p.stdin,  # type: ignore[arg-type]
        stdout=p.stdout,  # type: ignore[arg-type]
    )
    # 1.0 简化: driver 已知端口, 不需要从 stdout 解析
    # 但等 Server 实际 accept (TCP connect 验证)
    import socket as _socket
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if p.poll() is not None:
            # Server 进程死了, 读 stderr
            try:
                stderr_data = p.stderr.read(2000).decode("utf-8", errors="replace")  # type: ignore[union-attr]
            except Exception:
                stderr_data = "<no stderr>"
            raise RuntimeError(
                f"Server subprocess died early (rc={p.returncode}). stderr:\n{stderr_data}"
            )
        try:
            with _socket.create_connection(("127.0.0.1", bind_port), timeout=0.5):
                # TCP accept OK
                return ServerSubprocess(
                    proc=proc,
                    server_address=f"127.0.0.1:{bind_port}",
                    auth_secret=auth_secret,
                    _tmp_config=tmp_cfg,
                )
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError(
        f"Server subprocess did not accept connections on port {bind_port} within 10s"
    )


# ---------------------------------------------------------------------------
# TCP Proxy subprocess
# ---------------------------------------------------------------------------


def _start_tcp_proxy_subprocess(
    *, target_host: str, target_port: int, listen_port: int = 0
) -> SubprocessProc:
    """启 1 个 TCP proxy subprocess. 返 (proc, bound_port via BOUND_PORT=... line)."""
    repo_root = Path(__file__).resolve().parents[4]
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "tcp_proxy.py"),
        "--listen-host",
        "127.0.0.1",
        "--listen-port",
        str(listen_port),
        "--target-host",
        target_host,
        "--target-port",
        str(target_port),
        "--log-level",
        "WARNING",
    ]
    p = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=str(repo_root),
    )
    proc = SubprocessProc(
        proc=p,
        stdin=p.stdin,  # type: ignore[arg-type]
        stdout=p.stdout,  # type: ignore[arg-type]
    )
    # 读 BOUND_PORT=NNNN
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            line = proc.read_line(timeout_s=2.0)
        except TimeoutError:
            continue
        if line.startswith("BOUND_PORT="):
            port = int(line.split("=", 1)[1])
            # 把 port 存到 proc 上 (作为 attribute)
            setattr(proc, "bound_port", port)
            return proc
    proc.terminate()
    raise RuntimeError("TCP proxy did not announce bound port within 5s")


# ---------------------------------------------------------------------------
# Client Agent subprocess
# ---------------------------------------------------------------------------


def _start_agent_subprocess(
    *,
    server_address: str,
    auth_secret: str,
    instance_id: str,
    startup_epoch: int = 0,
    resources: list[dict[str, Any]],
    local_fallback: bool = False,
) -> SubprocessProc:
    """启 1 个 Client Agent subprocess."""
    repo_root = Path(__file__).resolve().parents[4]
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "agent_runtime.py"),
        "--server-address",
        server_address,
        "--auth-secret",
        auth_secret,
        "--instance-id",
        instance_id,
        "--startup-epoch",
        str(startup_epoch),
        "--resources",
        json.dumps(resources),
        "--local-fallback",
        "yes" if local_fallback else "no",
        "--log-level",
        "WARNING",
    ]
    p = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,  # 1.0: 保留 stderr, Agent 启动错能看到
        cwd=str(repo_root),
    )
    proc = SubprocessProc(
        proc=p,
        stdin=p.stdin,  # type: ignore[arg-type]
        stdout=p.stdout,  # type: ignore[arg-type]
    )
    setattr(proc, "_stderr", p.stderr)
    # 读 ready 信号
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if p.poll() is not None:
            try:
                stderr_data = p.stderr.read(2000).decode("utf-8", errors="replace")  # type: ignore[union-attr]
            except Exception:
                stderr_data = "<no stderr>"
            raise RuntimeError(
                f"Agent died early (rc={p.returncode}). stderr:\n{stderr_data}"
            )
        try:
            line = proc.read_line(timeout_s=2.0)
        except TimeoutError:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("result") == "ready" and msg.get("ok"):
            return proc
    proc.terminate()
    raise RuntimeError("Agent did not send ready within 5s")


# ---------------------------------------------------------------------------
# 公共 fixtures
# ---------------------------------------------------------------------------


DEFAULT_RESOURCES = [
    {"name": "/r1", "max_permits": 5.0, "failure_policy": "fail_closed"},
]


@pytest.fixture
def auth_secret() -> str:
    return "m64-test-secret"


@pytest.fixture
def resources() -> list[dict[str, Any]]:
    return DEFAULT_RESOURCES


@pytest.fixture
def server_subprocess(
    resources: list[dict[str, Any]], auth_secret: str
) -> Iterator[ServerSubprocess]:
    """启 1 个真实 StandaloneTokenServer subprocess."""
    srv = _start_server_subprocess(
        resources=resources, auth_secret=auth_secret, bind_port=0
    )
    try:
        yield srv
    finally:
        srv.stop()


@pytest.fixture
def tcp_proxy_subprocess(
    server_subprocess: ServerSubprocess,
) -> Iterator[SubprocessProc]:
    """启 1 个 TCP proxy, 转发 127.0.0.1:proxy_port → server:server_port."""
    # server_subprocess.server_address = "127.0.0.1:NNNNN"
    _, port_str = server_subprocess.server_address.rsplit(":", 1)
    target_port = int(port_str)
    proxy = _start_tcp_proxy_subprocess(
        target_host="127.0.0.1", target_port=target_port, listen_port=0
    )
    try:
        yield proxy
    finally:
        try:
            proxy.send_line("quit")
        except Exception:
            pass
        proxy.terminate()


# ---------------------------------------------------------------------------
# 公共 helper: 通过 proxy 给 Agent 发 acquire / release 命令
# ---------------------------------------------------------------------------


@dataclass
class AgentHandle:
    """Client Agent handle (driver 侧)."""

    proc: SubprocessProc
    instance_id: str

    def acquire(self, resource: str, permits: float) -> dict[str, Any]:
        cmd = {"cmd": "acquire", "resource": resource, "permits": permits}
        self.proc.send_line(json.dumps(cmd))
        line = self.proc.read_line(timeout_s=15.0)
        return json.loads(line)

    def release(self, token: dict[str, Any]) -> dict[str, Any]:
        cmd = {"cmd": "release", "token": token}
        self.proc.send_line(json.dumps(cmd))
        line = self.proc.read_line(timeout_s=15.0)
        return json.loads(line)

    def aclose(self) -> dict[str, Any]:
        cmd = {"cmd": "aclose"}
        self.proc.send_line(json.dumps(cmd))
        line = self.proc.read_line(timeout_s=5.0)
        return json.loads(line)

    def shutdown(self) -> dict[str, Any]:
        cmd = {"cmd": "shutdown"}
        self.proc.send_line(json.dumps(cmd))
        line = self.proc.read_line(timeout_s=5.0)
        try:
            return json.loads(line)
        except Exception:
            return {"result": "shutdown", "ok": True}

    def stop(self) -> None:
        try:
            self.shutdown()
        except Exception:
            pass
        self.proc.terminate()


@pytest.fixture
def agent_factory(
    tcp_proxy_subprocess: SubprocessProc,
    resources: list[dict[str, Any]],
    auth_secret: str,
) -> "Any":  # Any = Callable[..., Iterator[AgentHandle]]
    """启 1 个 Client Agent, 通过 tcp_proxy 跟 Server 通信.

    Usage::

        def test_x(agent_factory):
            agent = agent_factory()  # 1 个 Agent
            resp = agent.acquire("/r1", 1.0)
    """
    from collections.abc import Callable

    started: list[AgentHandle] = []

    def _factory(
        *,
        instance_id: str | None = None,
        startup_epoch: int = 0,
        local_fallback: bool = False,
    ) -> AgentHandle:
        if instance_id is None:
            instance_id = str(uuid.uuid4())
        # Agent 指向 tcp_proxy 的端口 (而不是直接 server 端口)
        proxy_port = getattr(tcp_proxy_subprocess, "bound_port", 0)
        assert proxy_port > 0, "tcp_proxy must have bound_port"
        proc = _start_agent_subprocess(
            server_address=f"127.0.0.1:{proxy_port}",
            auth_secret=auth_secret,
            instance_id=instance_id,
            startup_epoch=startup_epoch,
            resources=resources,
            local_fallback=local_fallback,
        )
        handle = AgentHandle(proc=proc, instance_id=instance_id)
        started.append(handle)
        return handle

    yield _factory
    # cleanup
    for h in started:
        try:
            h.stop()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 短路径 fixture (smoke test 用): 不用 proxy, Agent 直连 Server
# ---------------------------------------------------------------------------


@pytest.fixture
def direct_agent_factory(
    server_subprocess: ServerSubprocess,
    resources: list[dict[str, Any]],
    auth_secret: str,
) -> "Any":
    """Agent 直连 Server (无 proxy). 1.0 简化: M6.4.1 冒烟测试用."""
    from collections.abc import Callable

    started: list[AgentHandle] = []

    def _factory(
        *,
        instance_id: str | None = None,
        startup_epoch: int = 0,
        local_fallback: bool = False,
    ) -> AgentHandle:
        if instance_id is None:
            instance_id = str(uuid.uuid4())
        proc = _start_agent_subprocess(
            server_address=server_subprocess.server_address,
            auth_secret=auth_secret,
            instance_id=instance_id,
            startup_epoch=startup_epoch,
            resources=resources,
            local_fallback=local_fallback,
        )
        handle = AgentHandle(proc=proc, instance_id=instance_id)
        started.append(handle)
        return handle

    yield _factory
    for h in started:
        try:
            h.stop()
        except Exception:
            pass
