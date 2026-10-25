"""Call the Java demo peer and verify response, delay, timeout, and recovery."""

from __future__ import annotations

import time
import socket
import sys
from urllib.error import URLError
from urllib.request import urlopen

_EXPECTED = b"atlas-sentinel-interop-ok"


def _request(base_url: str, path: str, timeout: float) -> bytes:
    with urlopen(f"{base_url}{path}", timeout=timeout) as response:
        if response.status != 200:
            raise AssertionError("Java demo returned a non-success status")
        return response.read()


def main() -> None:
    """Run Java-peer happy, delay, caller-timeout, and recovery checks."""
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18762"
    if _request(base_url, "/demo/fixed", 2.0) != _EXPECTED:
        raise AssertionError("Java fixed response differs from the demo contract")
    start = time.monotonic()
    if _request(base_url, "/demo/delay?seconds=0.2", 2.0) != _EXPECTED:
        raise AssertionError("Java delay response differs from the demo contract")
    if time.monotonic() - start < 0.15:
        raise AssertionError("Java delay endpoint returned too early")
    try:
        _request(base_url, "/demo/delay?seconds=0.4", 0.05)
    except (TimeoutError, URLError, socket.timeout):
        pass
    else:
        raise AssertionError("Java delay endpoint did not trigger client timeout")
    if _request(base_url, "/demo/fixed", 2.0) != _EXPECTED:
        raise AssertionError("Java peer did not recover after client timeout")
    print("Python -> Java demo passed: fixed, delayed, timeout, recovery")


if __name__ == "__main__":
    main()
