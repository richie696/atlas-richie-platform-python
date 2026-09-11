"""Server-boot helpers for the `atlas-richie-http` E2E suite.

中文
----
封装 uvicorn 子进程启动逻辑:挑空闲端口 → 启动 uvicorn → 等待端口
可连 → 收尾时 `terminate() + wait()`。`pytest.importorskip("uvicorn")`
由调用方负责,这里只做开/关。

English
--------
Encapsulate the boilerplate of booting a uvicorn subprocess for
the E2E smoke test:

- `pick_free_port`: grab a free TCP port on loopback.
- `wait_for_port`: poll the port until uvicorn answers.
- `ServerHandle`: context manager that starts uvicorn and
  guarantees `terminate()` + `wait()` on exit.

The subprocess-based smoke test uses this; the in-process ASGI
tests do not.
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
import sys
import time
from collections.abc import Iterator


def pick_free_port() -> int:
    """Return an unused TCP port on `127.0.0.1`.

    English
    --------
    Bind a socket to port 0, read the OS-assigned port, and
    immediately close it. The port is **likely** free in the
    small window between `close()` and uvicorn binding, but a
    concurrent process may still race — callers should still
    pass `--port 0` when possible. Used as a fallback for the
    smoke test.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_port(host: str, port: int, timeout: float = 5.0) -> bool:
    """Poll `host:port` until a connection succeeds or `timeout` elapses.

    Args:
        host: hostname to probe.
        port: TCP port to probe.
        timeout: maximum wait in seconds.

    Returns:
        `True` when the port accepts a connection within
        `timeout`, `False` otherwise.

    English
    --------
    Poll `host:port` until a connection succeeds or `timeout`
    elapses.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.05)
    return False


@contextlib.contextmanager
def run_uvicorn(
    app_path: str,
    *,
    port: int,
    app_dir: str | None = None,
) -> Iterator[subprocess.Popen[bytes]]:
    """Boot a uvicorn subprocess and tear it down on exit.

    Args:
        app_path: `module:attr` import path passed to uvicorn.
        port: TCP port uvicorn should bind to.
        app_dir: optional absolute directory to add to
            `sys.path` via uvicorn's `--app-dir`. Required when
            `app_path` is a *test* module (e.g. the E2E test
            app) that lives outside the `atlas_richie.http`
            production source tree.

    Yields:
        The live `Popen` handle. Callers can `proc.pid` /
        `proc.poll()` for diagnostics.

    English
    --------
    Spawn a uvicorn subprocess pointed at `app_path`, then
    guarantee `terminate()` + `wait(timeout=5.0)` on context
    exit. The Popen's stdout/stderr are routed to DEVNULL so
    the test runner output stays clean; CI failures can flip
    the devnull capture back on by passing a real file.
    """
    args = [
        sys.executable,
        "-m",
        "uvicorn",
        app_path,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    if app_dir is not None:
        args.extend(["--app-dir", app_dir])
    proc = subprocess.Popen(  # noqa: S603 — test-only subprocess
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)
