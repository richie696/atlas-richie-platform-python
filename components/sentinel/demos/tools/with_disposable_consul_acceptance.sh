#!/usr/bin/env bash
set -euo pipefail

docker_bin="${DOCKER_BIN:-docker}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
run_id="$(date +%s)-$$-${RANDOM}"
container_name="sentinel-t004-consul-${run_id}"
owner="codex-t004-consul-${run_id}"
container_id=""

cleanup() {
  local status=$?
  local current_owner
  trap - EXIT
  if [[ -z "$container_id" ]]; then
    exit "$status"
  fi
  current_owner="$("$docker_bin" inspect --format='{{ index .Config.Labels "com.atlas-richie.sentinel-t004.run" }}' "$container_id" 2>/dev/null || true)"
  if [[ "$current_owner" != "$owner" ]]; then
    printf 'Refusing cleanup: owner label mismatch for container %s\n' "$container_id" >&2
    exit 1
  fi
  "$docker_bin" rm -f "$container_id" >/dev/null || status=1
  if "$docker_bin" inspect "$container_id" >/dev/null 2>&1; then
    printf 'Owned Consul container remains after cleanup: %s\n' "$container_id" >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if "$docker_bin" inspect "$container_name" >/dev/null 2>&1; then
  printf 'Generated container name unexpectedly exists; refusing to reuse it.\n' >&2
  exit 2
fi

container_id="$("$docker_bin" run -d \
  --name "$container_name" \
  --label "com.atlas-richie.sentinel-t004.run=$owner" \
  --publish 127.0.0.1::8500 \
  hashicorp/consul:1.21.1 \
  agent -dev -client=0.0.0.0 -bind=0.0.0.0)"
port="$("$docker_bin" port "$container_id" 8500/tcp | sed -n 's/.*:\([0-9][0-9]*\)$/\1/p' | head -n 1)"
if [[ -z "$port" ]]; then
  printf 'Could not resolve the owned Consul loopback port.\n' >&2
  exit 1
fi
consul_url="http://127.0.0.1:${port}"

ready=0
for _ in $(seq 1 60); do
  if curl --silent --show-error --fail "$consul_url/v1/status/leader" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  printf 'Disposable Consul did not become ready within 60 seconds.\n' >&2
  exit 1
fi

printf 'Running Go Runtime against owned loopback Consul on port %s.\n' "$port"
(
  cd "$repo_root/components/sentinel/demos/go-nacos-sentinel"
  SENTINEL_T004_CONSUL_ACCEPTANCE=true SENTINEL_T004_CONSUL_URL="$consul_url" \
    go test -run '^TestRealConsulPollingRuntimeAcceptance$' -count=1 -v .
)

printf 'Running Java Runtime against the same owned Consul provider.\n'
(
  cd "$repo_root/components/sentinel/demos/java-nacos-sentinel"
  SENTINEL_T004_CONSUL_ACCEPTANCE=true SENTINEL_T004_CONSUL_URL="$consul_url" \
    mvn -q -Dtest=ConsulPollingRuntimeAcceptanceTest test
)

printf 'Both real Consul Runtime acceptance suites passed; cleanup will remove only owner=%s.\n' "$owner"
