#!/usr/bin/env bash

# Run an opt-in real-provider acceptance against a private, disposable
# Prometheus + synthetic exporter pair. Only loopback Prometheus is published.
# A second Prometheus instance requires Basic Auth to exercise the real 401 path.

set -Eeuo pipefail

if [[ $# -eq 0 ]]; then
  printf 'Usage: %s <command> [args...]\n' "$0" >&2
  exit 64
fi

docker_bin="${DOCKER_BIN:-docker}"
for utility in "$docker_bin" openssl; do
  command -v "$utility" >/dev/null 2>&1 || {
    printf 'Required utility not found: %s\n' "$utility" >&2
    exit 69
  }
done
for utility in curl htpasswd; do
  command -v "$utility" >/dev/null 2>&1 || {
    printf 'Required utility not found: %s\n' "$utility" >&2
    exit 69
  }
done
"$docker_bin" info >/dev/null 2>&1 || {
  printf 'Docker daemon is unavailable; no resources were created.\n' >&2
  exit 69
}

run_id="$(openssl rand -hex 16)"
network_name="sentinel-t053-net-${run_id}"
exporter_name="sentinel-t053-exporter-${run_id}"
prometheus_name="sentinel-t053-prometheus-${run_id}"
auth_prometheus_name="sentinel-t053-auth-prometheus-${run_id}"
fixture_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")/../tests/fixtures" && pwd)"
temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/sentinel-t053.XXXXXX")"
network_id=""
exporter_id=""
prometheus_id=""
auth_prometheus_id=""
child_pid=""
auth_password="$(openssl rand -hex 24)"
auth_username="t053_$(openssl rand -hex 8)"
requested_prometheus_port="${SENTINEL_T053_PROMETHEUS_HOST_PORT:-}"

if [[ -n "$requested_prometheus_port" ]]; then
  [[ "$requested_prometheus_port" =~ ^[0-9]{1,5}$ ]] &&
    (( requested_prometheus_port >= 1024 && requested_prometheus_port <= 65535 )) || {
      printf 'SENTINEL_T053_PROMETHEUS_HOST_PORT must be an unprivileged TCP port.\n' >&2
      exit 64
    }
  if ! python3 -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1",int(sys.argv[1]))); s.close()' \
    "$requested_prometheus_port"; then
    printf 'Requested loopback Prometheus port is already occupied: %s.\n' \
      "$requested_prometheus_port" >&2
    exit 73
  fi
fi

htpasswd_line="$(printf '%s\n' "$auth_password" | htpasswd -n -B -C 10 -i "$auth_username")"
auth_hash="${htpasswd_line#*:}"
[[ "$htpasswd_line" == "${auth_username}:"* && -n "$auth_hash" ]] || {
  printf 'Could not generate a disposable Prometheus Basic Auth verifier.\n' >&2
  exit 70
}
printf "basic_auth_users:\n  %s: '%s'\n" "$auth_username" "$auth_hash" \
  >"${temporary_directory}/web.yml"

remove_owned_container() {
  local container_id="$1"
  [[ -n "$container_id" ]] || return 0
  local details
  if ! details="$("$docker_bin" container inspect \
    --format '{{ .Id }} {{ index .Config.Labels "com.atlas-richie.sentinel-t053.run" }}' \
    "$container_id" 2>/dev/null)"; then
    return 0
  fi
  local actual_id owner_id
  read -r actual_id owner_id <<<"$details"
  if [[ "$actual_id" =~ ^[0-9a-f]{64}$ && "$owner_id" == "$run_id" ]]; then
    "$docker_bin" rm --force --volumes "$actual_id" >/dev/null
  else
    printf 'Refusing to remove container not owned by this run: %s\n' "$container_id" >&2
    return 1
  fi
}

cleanup() {
  local exit_status=$?
  trap - EXIT INT TERM HUP
  if [[ -n "$child_pid" ]]; then
    kill "$child_pid" >/dev/null 2>&1 || true
    wait "$child_pid" >/dev/null 2>&1 || true
  fi
  if [[ "${SENTINEL_T053_KEEP_SERVICES:-0}" == 1 && "$exit_status" == 0 ]]; then
    printf 'Retaining successful run-owned Prometheus acceptance services for review: %s, %s, %s.\n' \
      "$exporter_name" "$prometheus_name" "$auth_prometheus_name"
    printf 'Prometheus: %s; auth-protected probe: %s; exporter control: %s/availability.\n' \
      "$SENTINEL_T053_PROMETHEUS_ENDPOINT" \
      "$SENTINEL_T053_PROMETHEUS_AUTH_ENDPOINT" \
      "$SENTINEL_T053_EXPORTER_CONTROL_URL"
    printf 'Owner label: com.atlas-richie.sentinel-t053.run=%s; network: %s.\n' \
      "$run_id" "$network_name"
    exit "$exit_status"
  fi
  remove_owned_container "$prometheus_id" || exit_status=70
  remove_owned_container "$auth_prometheus_id" || exit_status=70
  remove_owned_container "$exporter_id" || exit_status=70
  if [[ -n "$network_id" ]]; then
    local network_details actual_network owner_id
    if network_details="$("$docker_bin" network inspect \
      --format '{{ .Id }} {{ index .Labels "com.atlas-richie.sentinel-t053.run" }}' \
      "$network_id" 2>/dev/null)"; then
      read -r actual_network owner_id <<<"$network_details"
      if [[ "$actual_network" =~ ^[0-9a-f]{64}$ && "$owner_id" == "$run_id" ]]; then
        "$docker_bin" network rm "$actual_network" >/dev/null || exit_status=70
      else
        printf 'Refusing to remove network not owned by this run: %s\n' "$network_id" >&2
        exit_status=70
      fi
    fi
  fi
  rm -rf -- "$temporary_directory"
  if [[ "$exit_status" != 0 ]]; then
    printf 'Disposable Prometheus acceptance ended with status %s.\n' "$exit_status" >&2
  fi
  exit "$exit_status"
}

handle_signal() {
  local signal="$1" status="$2"
  trap - INT TERM HUP
  [[ -z "$child_pid" ]] || kill -s "$signal" "$child_pid" >/dev/null 2>&1 || true
  exit "$status"
}

trap cleanup EXIT
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM
trap 'handle_signal HUP 129' HUP

network_id="$("$docker_bin" network create \
  --label "com.atlas-richie.sentinel-t053.run=${run_id}" \
  "$network_name")"
exporter_id="$("$docker_bin" run --detach \
  --name "$exporter_name" \
  --label "com.atlas-richie.sentinel-t053.run=${run_id}" \
  --network "$network_id" \
  --network-alias sentinel-t053-exporter \
  --publish '127.0.0.1::9101/tcp' \
  --mount "type=bind,source=${fixture_directory}/synthetic_prometheus_exporter.py,target=/fixtures/exporter.py,readonly" \
  python:3.12-alpine python -u /fixtures/exporter.py)"
prometheus_publish='127.0.0.1::9090/tcp'
if [[ -n "$requested_prometheus_port" ]]; then
  prometheus_publish="127.0.0.1:${requested_prometheus_port}:9090/tcp"
fi
prometheus_id="$("$docker_bin" run --detach \
  --name "$prometheus_name" \
  --label "com.atlas-richie.sentinel-t053.run=${run_id}" \
  --network "$network_id" \
  --publish "$prometheus_publish" \
  --mount "type=bind,source=${fixture_directory}/prometheus_t053.yml,target=/etc/prometheus/prometheus.yml,readonly" \
  prom/prometheus:v3.5.0 \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --web.listen-address=0.0.0.0:9090)"
auth_prometheus_id="$("$docker_bin" run --detach \
  --name "$auth_prometheus_name" \
  --label "com.atlas-richie.sentinel-t053.run=${run_id}" \
  --network "$network_id" \
  --publish '127.0.0.1::9090/tcp' \
  --mount "type=bind,source=${fixture_directory}/prometheus_t053.yml,target=/etc/prometheus/prometheus.yml,readonly" \
  --mount "type=bind,source=${temporary_directory}/web.yml,target=/etc/prometheus/web.yml,readonly" \
  prom/prometheus:v3.5.0 \
  --config.file=/etc/prometheus/prometheus.yml \
  --web.config.file=/etc/prometheus/web.yml \
  --storage.tsdb.path=/prometheus \
  --web.listen-address=0.0.0.0:9090)"

mapping="$("$docker_bin" port "$prometheus_id" 9090/tcp)"
[[ "$mapping" == 127.0.0.1:* ]] || {
  printf 'Expected a loopback Prometheus mapping; received %s\n' "$mapping" >&2
  exit 70
}
prometheus_port="${mapping##*:}"
if [[ -n "$requested_prometheus_port" && "$prometheus_port" != "$requested_prometheus_port" ]]; then
  printf 'Requested Prometheus host port %s but Docker mapped %s.\n' \
    "$requested_prometheus_port" "$mapping" >&2
  exit 70
fi
control_mapping="$("$docker_bin" port "$exporter_id" 9101/tcp)"
[[ "$control_mapping" == 127.0.0.1:* ]] || {
  printf 'Expected a loopback exporter control mapping; received %s\n' "$control_mapping" >&2
  exit 70
}
export SENTINEL_T053_EXPORTER_CONTROL_URL="http://127.0.0.1:${control_mapping##*:}"
for _attempt in {1..60}; do
  if curl --fail --silent --max-time 2 \
    "http://127.0.0.1:${prometheus_port}/-/ready" >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error --max-time 2 \
  "http://127.0.0.1:${prometheus_port}/-/ready" >/dev/null || {
  printf 'Disposable Prometheus did not become ready.\n' >&2
  exit 70
}

auth_mapping="$("$docker_bin" port "$auth_prometheus_id" 9090/tcp)"
[[ "$auth_mapping" == 127.0.0.1:* ]] || {
  printf 'Expected a loopback authenticated Prometheus mapping; received %s\n' "$auth_mapping" >&2
  exit 70
}
auth_prometheus_port="${auth_mapping##*:}"
auth_ready=0
for _attempt in {1..60}; do
  auth_status="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 2 \
    "http://127.0.0.1:${auth_prometheus_port}/-/ready" || true)"
  if [[ "$auth_status" == "401" ]]; then
    auth_ready=1
    break
  fi
  sleep 1
done
[[ "$auth_ready" == 1 ]] || {
  printf 'Disposable authenticated Prometheus did not become ready (expected HTTP 401).\n' >&2
  exit 70
}

export SENTINEL_T053_PROMETHEUS_ENDPOINT="http://127.0.0.1:${prometheus_port}"
export SENTINEL_T053_PROMETHEUS_AUTH_ENDPOINT="http://127.0.0.1:${auth_prometheus_port}"
if [[ "${SENTINEL_T053_ENABLE_T07_LIFECYCLE:-0}" == 1 ]]; then
  lifecycle_grant="127.0.0.1|127.0.0.1/32|${prometheus_port}|loopback-http"
  if [[ -n "${SENTINEL_T07_MONITORING_TARGETS:-}" ]]; then
    export SENTINEL_T07_MONITORING_TARGETS="${SENTINEL_T07_MONITORING_TARGETS};${lifecycle_grant}"
  else
    export SENTINEL_T07_MONITORING_TARGETS="$lifecycle_grant"
  fi
  export SENTINEL_T07_PROMETHEUS_CONTROL_URL
  SENTINEL_T07_PROMETHEUS_CONTROL_URL="${SENTINEL_T053_EXPORTER_CONTROL_URL}/availability"
  export SENTINEL_T07_PROMETHEUS_CONTROL_JOB=t07-controlled
fi
printf 'Started run-owned Prometheus and synthetic exporter on private network %s.\n' "$network_name"
printf 'Prometheus is reachable only at %s; authenticated denial endpoint is %s; resources are removed on exit.\n' \
  "$SENTINEL_T053_PROMETHEUS_ENDPOINT" "$SENTINEL_T053_PROMETHEUS_AUTH_ENDPOINT"
"$@" &
child_pid=$!
if wait "$child_pid"; then
  command_status=0
else
  command_status=$?
fi
child_pid=""
exit "$command_status"
