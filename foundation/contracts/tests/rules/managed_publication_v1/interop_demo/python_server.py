"""Tiny Python HTTP peer for cross-language transport smoke checks only."""

from __future__ import annotations

import argparse
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

_FIXED_RESPONSE = "atlas-sentinel-interop-ok"
_MAX_DELAY_SECONDS = 5.0


class InteropRequestHandler(BaseHTTPRequestHandler):
    """Expose deterministic fixed and bounded-delay demo endpoints."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlsplit(self.path)
        if parsed.path == "/demo/fixed":
            self._respond(_FIXED_RESPONSE)
            return
        if parsed.path == "/demo/delay":
            self._respond_after_delay(parsed.query)
            return
        self._respond("not-found", status=404)

    def log_message(self, format: str, *args: object) -> None:
        """Keep demo request logs deterministic and free of query contents."""

    def _respond_after_delay(self, query: str) -> None:
        values = parse_qs(query, strict_parsing=True)
        if set(values) != {"seconds"} or len(values["seconds"]) != 1:
            self._respond("invalid-delay", status=400)
            return
        try:
            delay = float(values["seconds"][0])
        except ValueError:
            self._respond("invalid-delay", status=400)
            return
        if not 0 <= delay <= _MAX_DELAY_SECONDS:
            self._respond("invalid-delay", status=400)
            return
        time.sleep(delay)
        self._respond(_FIXED_RESPONSE)

    def _respond(self, value: str, *, status: int = 200) -> None:
        body = value.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    """Start the standard-library Python demo HTTP peer."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18761)
    arguments = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", arguments.port), InteropRequestHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
