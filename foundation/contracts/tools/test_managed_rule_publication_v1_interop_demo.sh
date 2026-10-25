#!/usr/bin/env bash

set -Eeuo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_directory/../../.." && pwd)"
contract_directory="$repository_root/foundation/contracts/tests/rules/managed_publication_v1"
java_source_directory="$contract_directory/java/src/main/java"
java_class_directory="$(mktemp -d "${TMPDIR:-/tmp}/sentinel-interop-java.XXXXXX")"
read -r python_port java_port < <(python3 - <<'PY'
import socket

ports = []
for _ in range(2):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        ports.append(listener.getsockname()[1])
print(*ports)
PY
)
python_pid=""
java_pid=""

cleanup() {
  if [[ -n "$java_pid" ]]; then
    kill "$java_pid" 2>/dev/null || true
    wait "$java_pid" 2>/dev/null || true
  fi
  if [[ -n "$python_pid" ]]; then
    kill "$python_pid" 2>/dev/null || true
    wait "$python_pid" 2>/dev/null || true
  fi
  rm -rf -- "$java_class_directory"
}
trap cleanup EXIT INT TERM

for required_command in python3 javac java; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    printf 'Required interop demo tool not found: %s\n' "$required_command" >&2
    exit 69
  fi
done

mkdir -p "$java_class_directory"
javac -d "$java_class_directory" \
  "$java_source_directory/com/atlas_richie/contracts/managedrulev1/InteropDemoServer.java" \
  "$java_source_directory/com/atlas_richie/contracts/managedrulev1/InteropDemoClient.java"

python3 "$contract_directory/interop_demo/python_server.py" --port "$python_port" &
python_pid=$!
java -cp "$java_class_directory" \
  com.atlas_richie.contracts.managedrulev1.InteropDemoServer "$java_port" &
java_pid=$!

python3 - "$contract_directory" "$python_port" "$java_port" <<'PY'
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

contract_directory = Path(sys.argv[1])
ports = tuple(int(value) for value in sys.argv[2:])
deadline = time.monotonic() + 10
for port in ports:
    while True:
        try:
            with urlopen(f"http://127.0.0.1:{port}/demo/fixed", timeout=0.2) as response:
                if response.read() != b"atlas-sentinel-interop-ok":
                    raise RuntimeError("interop demo readiness payload mismatch")
            break
        except (URLError, TimeoutError):
            if time.monotonic() >= deadline:
                raise RuntimeError(f"interop demo server on port {port} did not start")
            time.sleep(0.05)

PY

python3 "$contract_directory/interop_demo.py" "http://127.0.0.1:$java_port"
java -cp "$java_class_directory" \
  com.atlas_richie.contracts.managedrulev1.InteropDemoClient \
  "http://127.0.0.1:$python_port"
printf '%s\n' 'Cross-language HTTP demo passed. This does not claim Sentinel runtime rule-source interoperability.'
