"""Shared fixtures for cross-language hello world contract tests.

Spins up the Go and Java hello world HTTP web services as background
subprocesses and tears them down after the test session. All HTTP I/O
uses ``urllib.request`` (stdlib only — no third-party deps).

Endpoints (both Go and Java):

- ``GET  http://127.0.0.1:<port>/healthz`` → 200 ``{"status":"ok"}``
- ``POST http://127.0.0.1:<port>/report``  → 200 with key_order echo,
  or 4xx with an error envelope. Body must contain the two wire
  marker fields ``protocol_version`` and ``event_kind``.

Both services bind to loopback only (per M6.5.7 protocol §3.5).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

CROSS_LANG_ROOT = Path(__file__).resolve().parent
GO_MAIN = CROSS_LANG_ROOT / "go" / "main.go"
GO_DEFAULT_PORT = 18080
JAVA_JAR = CROSS_LANG_ROOT / "java" / "target" / "hello-world-0.1.0.jar"
JAVA_DEFAULT_PORT = 18081

_HEALTHZ_TIMEOUT_S = 30.0
_REQUEST_TIMEOUT_S = 5.0


def _wait_for_healthz(url: str, timeout: float) -> None:
    deadline = time.perf_counter() + timeout
    last_err: Exception | None = None
    while time.perf_counter() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, socket.timeout, OSError) as e:
            last_err = e
            time.sleep(0.2)
    raise RuntimeError(f"service at {url} did not become healthy in {timeout}s "
                       f"(last error: {last_err!r})")


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _allocate_port(preferred: int) -> int:
    if _port_is_free(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post_json(url: str, body: bytes, timeout: float = _REQUEST_TIMEOUT_S):
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() or b""


# ---------------------------------------------------------------------------
# Go hello world fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def go_hello_server():
    if not GO_MAIN.exists():
        pytest.skip(f"Go hello world source not found at {GO_MAIN}")
    port = _allocate_port(GO_DEFAULT_PORT)
    url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.setdefault("GOFLAGS", "-mod=mod")
    proc = subprocess.Popen(
        ["go", "run", str(GO_MAIN), "-addr", f"127.0.0.1:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    try:
        _wait_for_healthz(f"{url}/healthz", _HEALTHZ_TIMEOUT_S)
    except Exception:
        proc.terminate()
        try:
            stderr = proc.stderr.read(2000).decode("utf-8", errors="replace")
        except Exception:
            stderr = ""
        raise RuntimeError(f"Go hello world failed to start: {stderr}")
    yield {"url": url, "process": proc}
    proc.terminate()
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# Java hello world fixture
# ---------------------------------------------------------------------------


def _build_java_jar() -> None:
    if JAVA_JAR.exists():
        return
    if not (CROSS_LANG_ROOT / "java" / "pom.xml").exists():
        pytest.skip(f"Java pom.xml not found at {CROSS_LANG_ROOT / 'java' / 'pom.xml'}")
    result = subprocess.run(
        ["mvn", "-q", "-f", str(CROSS_LANG_ROOT / "java" / "pom.xml"),
         "-DskipTests", "package"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180.0,
    )
    if result.returncode != 0:
        pytest.skip(
            f"Java hello world build failed (mvn exit {result.returncode}): "
            f"{result.stderr.decode(errors='replace')[:2000]}"
        )


@pytest.fixture(scope="session")
def java_hello_server():
    _build_java_jar()
    port = _allocate_port(JAVA_DEFAULT_PORT)
    url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        ["java", "-jar", str(JAVA_JAR), "-addr", f"127.0.0.1:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        _wait_for_healthz(f"{url}/healthz", _HEALTHZ_TIMEOUT_S)
    except Exception:
        proc.terminate()
        try:
            stderr = proc.stderr.read(2000).decode("utf-8", errors="replace")
        except Exception:
            stderr = ""
        raise RuntimeError(f"Java hello world failed to start: {stderr}")
    yield {"url": url, "process": proc}
    proc.terminate()
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class HelloClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def healthz(self) -> int:
        with urllib.request.urlopen(f"{self.base_url}/healthz", timeout=2.0) as r:
            return r.status

    def report(self, body: bytes):
        status, _headers, raw = _post_json(f"{self.base_url}/report", body)
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, {"_raw": raw.decode("utf-8", errors="replace")}


@pytest.fixture
def go_hello(go_hello_server) -> HelloClient:
    return HelloClient(go_hello_server["url"])


@pytest.fixture
def java_hello(java_hello_server) -> HelloClient:
    return HelloClient(java_hello_server["url"])
