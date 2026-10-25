"""Small deterministic exporter for disposable Prometheus acceptance tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

_PROFILE = """# HELP node_cpu_seconds_total Synthetic CPU counter.
# TYPE node_cpu_seconds_total counter
node_cpu_seconds_total{cpu="0",mode="idle"} 12
node_cpu_seconds_total{cpu="0",mode="iowait"} 1
node_cpu_seconds_total{cpu="0",mode="steal"} 1
# HELP node_memory_MemAvailable_bytes Synthetic available memory.
# TYPE node_memory_MemAvailable_bytes gauge
node_memory_MemAvailable_bytes 1024
# HELP node_memory_MemTotal_bytes Synthetic total memory.
# TYPE node_memory_MemTotal_bytes gauge
node_memory_MemTotal_bytes 4096
# HELP node_load1 Synthetic load.
# TYPE node_load1 gauge
node_load1 0.25
"""

_SCENARIOS = {
    "/complete": _PROFILE
    + '# HELP node_uname_info Synthetic host identity.\n'
    + '# TYPE node_uname_info gauge\n'
    + 'node_uname_info{host="synthetic-node-a",nodename="node-a"} 1\n',
    "/missing": _PROFILE
    + '# HELP node_uname_info Synthetic host identity.\n'
    + '# TYPE node_uname_info gauge\n'
    + 'node_uname_info{nodename="node-without-host"} 1\n',
    "/conflicting": _PROFILE
    + '# HELP node_uname_info Synthetic host identity.\n'
    + '# TYPE node_uname_info gauge\n'
    + 'node_uname_info{host="synthetic-duplicate",nodename="node-a"} 1\n'
    + 'node_uname_info{host="synthetic-duplicate",nodename="node-b"} 1\n',
    "/controlled": _PROFILE
    + '# HELP node_uname_info Synthetic host identity.\n'
    + '# TYPE node_uname_info gauge\n'
    + 'node_uname_info{host="t07-controlled-node",nodename="t07-controlled-node"} 1\n',
}

_availability = {"available": True}
_availability_lock = threading.Lock()


class _ExporterHandler(BaseHTTPRequestHandler):
    """Serve only the three explicit synthetic identity cases."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        body = _SCENARIOS.get(self.path)
        if self.path == "/controlled":
            with _availability_lock:
                available = _availability["available"]
            if not available:
                self.send_error(503)
                return
        if body is None:
            self.send_error(404)
            return
        encoded = body.encode("ascii")
        self.send_response(200)
        self.send_header(
            "Content-Type", "text/plain; version=0.0.4; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/availability":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("content-length", "0"))
            if size <= 0 or size > 128:
                raise ValueError
            request = json.loads(self.rfile.read(size))
            available = request["available"]
            if type(available) is not bool:
                raise ValueError
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.send_error(400)
            return
        with _availability_lock:
            _availability["available"] = available
        self.send_response(204)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    import threading

    scrape_server = _ThreadingHTTPServer(("0.0.0.0", 9100), _ExporterHandler)
    control_server = _ThreadingHTTPServer(("0.0.0.0", 9101), _ExporterHandler)
    threading.Thread(target=scrape_server.serve_forever, daemon=True).start()
    control_server.serve_forever()
