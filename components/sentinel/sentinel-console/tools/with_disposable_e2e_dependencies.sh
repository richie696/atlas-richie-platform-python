#!/usr/bin/env bash

# Run one acceptance command against isolated, loopback-only MySQL and Consul.
# Containers have unique names, only temporary read-only certificate mounts,
# and are removed on every exit path. Existing containers are never modified.

set -Eeuo pipefail

usage() {
  printf 'Usage: %s <command> [args... ]\n' "$0" >&2
  printf 'Starts disposable MySQL 8.4.11 and Consul 1.21.1 for the command.\n' >&2
}

if [[ $# -eq 0 ]]; then
  usage
  exit 64
fi

docker_bin="${DOCKER_BIN:-docker}"
if ! command -v "$docker_bin" >/dev/null 2>&1; then
  printf 'Docker CLI not found: %s\n' "$docker_bin" >&2
  exit 69
fi
if ! "$docker_bin" info >/dev/null 2>&1; then
  printf 'Docker daemon is unavailable. No containers were started.\n' >&2
  exit 69
fi
if ! command -v openssl >/dev/null 2>&1; then
  printf 'Required local utility not found: openssl\n' >&2
  exit 69
fi

run_id="$(openssl rand -hex 16)"
mysql_name="sentinel-e2e-mysql-${run_id}"
consul_name="sentinel-e2e-consul-${run_id}"
mysql_started=0
consul_started=0
temporary_directory=""

for container_name in "$mysql_name" "$consul_name"; do
  if "$docker_bin" container inspect "$container_name" >/dev/null 2>&1; then
    printf 'Refusing to reuse existing container name: %s\n' "$container_name" >&2
    exit 73
  fi
done

cleanup() {
  local exit_status=$?
  local cleanup_failed=0
  trap - EXIT INT TERM HUP
  if [[ \
    ("${SENTINEL_E2E_KEEP_DEPENDENCIES:-0}" == 1 && "$exit_status" == 0) || \
    ("${SENTINEL_E2E_KEEP_DEPENDENCIES_ON_FAILURE:-0}" == 1 && "$exit_status" != 0) \
  ]]; then
    printf 'Retaining run-owned acceptance dependencies for review: %s, %s.\n' \
      "$mysql_name" "$consul_name"
    printf 'Retaining temporary certificates/configuration under %s.\n' \
      "$temporary_directory"
    exit "$exit_status"
  fi
  remove_owned_container "$consul_name" "$consul_started" || cleanup_failed=1
  remove_owned_container "$mysql_name" "$mysql_started" || cleanup_failed=1
  if [[ -n "$temporary_directory" ]]; then
    rm -f -- \
      "$temporary_directory/ca.pem" \
      "$temporary_directory/ca-key.pem" \
      "$temporary_directory/ca.srl" \
      "$temporary_directory/mysql-ssl.cnf" \
      "$temporary_directory/server-cert.pem" \
      "$temporary_directory/server-key.pem" \
      "$temporary_directory/server.csr" \
      "$temporary_directory/server.ext" \
      "$temporary_directory/certs/ca.pem" \
      "$temporary_directory/certs/server-cert.pem" \
      "$temporary_directory/certs/server-key.pem"
    rmdir -- "$temporary_directory/certs" "$temporary_directory" \
      >/dev/null 2>&1 || true
  fi
  if [[ "$cleanup_failed" == 1 ]]; then
    printf 'One or more run-owned containers could not be confirmed removed.\n' >&2
    if [[ "$exit_status" == 0 ]]; then
      exit_status=70
    fi
  fi
  exit "$exit_status"
}

remove_owned_container() {
  local container_name="$1"
  local creation_attempted="$2"
  local inspection
  local container_id
  local owner_run_id
  local removal_status=0
  [[ "$creation_attempted" == 1 ]] || return 0
  if ! inspection="$("$docker_bin" container inspect \
    --format '{{ .Id }} {{ index .Config.Labels "com.atlas-richie.sentinel-e2e.run" }}' \
    "$container_name" 2>/dev/null)"; then
    if ! "$docker_bin" info >/dev/null 2>&1; then
      printf 'Cannot verify cleanup for container %s: Docker daemon unavailable.\n' \
        "$container_name" >&2
      return 1
    fi
    return 0
  fi
  read -r container_id owner_run_id <<<"$inspection"
  if [[ "$container_id" =~ ^[0-9a-f]{64}$ && "$owner_run_id" == "$run_id" ]]; then
    "$docker_bin" rm --force --volumes "$container_id" >/dev/null 2>&1 || removal_status=$?
    if inspection="$("$docker_bin" container inspect \
      --format '{{ .Id }} {{ index .Config.Labels "com.atlas-richie.sentinel-e2e.run" }}' \
      "$container_name" 2>/dev/null)"; then
      read -r container_id owner_run_id <<<"$inspection"
      if [[ "$container_id" =~ ^[0-9a-f]{64}$ && "$owner_run_id" == "$run_id" ]]; then
        printf 'Failed to remove run-owned container %s (docker rm status %s).\n' \
          "$container_name" "$removal_status" >&2
        return 1
      fi
    elif ! "$docker_bin" info >/dev/null 2>&1; then
      printf 'Cannot verify cleanup for container %s after docker rm.\n' \
        "$container_name" >&2
      return 1
    fi
  fi
}

handle_signal() {
  local signal="$1"
  local exit_status="$2"
  trap - INT TERM HUP
  if [[ -n "${child_pid:-}" ]]; then
    kill -s "$signal" "$child_pid" >/dev/null 2>&1 || true
    wait "$child_pid" >/dev/null 2>&1 || true
    child_pid=""
  fi
  exit "$exit_status"
}

trap cleanup EXIT
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM
trap 'handle_signal HUP 129' HUP

mysql_database="sentinel_console_test_${run_id}"
mysql_user="sentinel_e2e"
mysql_password="$(openssl rand -hex 24)"
mysql_root_password="$(openssl rand -hex 24)"
temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/sentinel-e2e.XXXXXX")"
mkdir "$temporary_directory/certs"

openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 1 \
  -keyout "$temporary_directory/ca-key.pem" \
  -out "$temporary_directory/ca.pem" \
  -addext 'basicConstraints=critical,CA:TRUE' \
  -addext 'keyUsage=critical,keyCertSign,cRLSign' \
  -addext 'subjectKeyIdentifier=hash' \
  -subj '/CN=Sentinel E2E Temporary CA' >/dev/null 2>&1
openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout "$temporary_directory/server-key.pem" \
  -out "$temporary_directory/server.csr" \
  -subj '/CN=localhost' >/dev/null 2>&1
printf '%s\n' \
  'subjectAltName=DNS:localhost,IP:127.0.0.1' \
  'extendedKeyUsage=serverAuth' \
  'keyUsage=digitalSignature,keyEncipherment' \
  >"$temporary_directory/server.ext"
openssl x509 -req -sha256 -days 1 \
  -in "$temporary_directory/server.csr" \
  -CA "$temporary_directory/ca.pem" \
  -CAkey "$temporary_directory/ca-key.pem" \
  -CAcreateserial \
  -extfile "$temporary_directory/server.ext" \
  -out "$temporary_directory/server-cert.pem" >/dev/null 2>&1
chmod 0444 "$temporary_directory/ca.pem" "$temporary_directory/server-cert.pem"
chmod 0444 "$temporary_directory/server-key.pem"
cp "$temporary_directory/ca.pem" "$temporary_directory/certs/ca.pem"
cp "$temporary_directory/server-cert.pem" "$temporary_directory/certs/server-cert.pem"
cp "$temporary_directory/server-key.pem" "$temporary_directory/certs/server-key.pem"
chmod 0444 "$temporary_directory/certs/"*.pem
printf '%s\n' \
  '[mysqld]' \
  'ssl_ca=/etc/mysql/certs/ca.pem' \
  'ssl_cert=/etc/mysql/certs/server-cert.pem' \
  'ssl_key=/etc/mysql/certs/server-key.pem' \
  'log_bin_trust_function_creators=ON' \
  >"$temporary_directory/mysql-ssl.cnf"

mysql_started=1
MYSQL_PASSWORD="$mysql_password" MYSQL_ROOT_PASSWORD="$mysql_root_password" \
"$docker_bin" run --detach \
  --name "$mysql_name" \
  --label "com.atlas-richie.sentinel-e2e.run=${run_id}" \
  --publish '127.0.0.1::3306/tcp' \
  --mount "type=bind,source=${temporary_directory}/certs,target=/etc/mysql/certs,readonly" \
  --mount "type=bind,source=${temporary_directory}/mysql-ssl.cnf,target=/etc/mysql/conf.d/zz-sentinel-e2e-ssl.cnf,readonly" \
  --env "MYSQL_DATABASE=${mysql_database}" \
  --env "MYSQL_USER=${mysql_user}" \
  --env MYSQL_PASSWORD \
  --env MYSQL_ROOT_PASSWORD \
  mysql:8.4.11 >/dev/null

consul_started=1
"$docker_bin" run --detach \
  --name "$consul_name" \
  --label "com.atlas-richie.sentinel-e2e.run=${run_id}" \
  --publish '127.0.0.1::8500/tcp' \
  hashicorp/consul:1.21.1 \
  agent -dev -client=0.0.0.0 -http-port=8500 >/dev/null

host_port() {
  local container_name="$1"
  local container_port="$2"
  local mapping
  mapping="$("$docker_bin" port "$container_name" "$container_port")"
  if [[ "$mapping" != 127.0.0.1:* ]]; then
    printf 'Expected loopback-only port mapping for %s; got %s\n' \
      "$container_name" "$mapping" >&2
    return 1
  fi
  printf '%s' "${mapping##*:}"
}

mysql_port="$(host_port "$mysql_name" '3306/tcp')"
consul_port="$(host_port "$consul_name" '8500/tcp')"

wait_for_mysql() {
  local attempt
  for attempt in {1..90}; do
    if MYSQL_PWD="$mysql_password" "$docker_bin" exec \
      --env MYSQL_PWD \
      "$mysql_name" \
      mysqladmin ping --protocol=tcp --host=127.0.0.1 \
        --user="$mysql_user" --silent >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  printf 'Disposable MySQL did not become ready.\n' >&2
  return 1
}

wait_for_consul() {
  local attempt
  for attempt in {1..60}; do
    if "$docker_bin" exec "$consul_name" consul members >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  printf 'Disposable Consul did not become ready.\n' >&2
  return 1
}

wait_for_mysql
wait_for_consul

export SENTINEL_CONSOLE_TEST_MYSQL_URL="mysql+asyncmy://${mysql_user}:${mysql_password}@127.0.0.1:${mysql_port}/${mysql_database}"
export SENTINEL_E2E_MYSQL_HOST=127.0.0.1
export SENTINEL_E2E_MYSQL_PORT="$mysql_port"
export SENTINEL_E2E_MYSQL_DATABASE="$mysql_database"
export SENTINEL_E2E_MYSQL_USER="$mysql_user"
export SENTINEL_E2E_MYSQL_PASSWORD="$mysql_password"
export SENTINEL_E2E_DOCKER_RUN_ID="$run_id"
export SENTINEL_E2E_MYSQL_CONTAINER="$mysql_name"
export SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE="$temporary_directory/ca.pem"
export SENTINEL_E2E_MYSQL_CERTIFICATE_DIRECTORY="$temporary_directory/certs"
export SENTINEL_E2E_MYSQL_CONFIG="$temporary_directory/mysql-ssl.cnf"
export SENTINEL_CONSOLE_BOOTSTRAP_DATABASE_TARGETS="${SENTINEL_CONSOLE_BOOTSTRAP_DATABASE_TARGETS:+${SENTINEL_CONSOLE_BOOTSTRAP_DATABASE_TARGETS};}mysql|127.0.0.1/32|${mysql_port}"
export SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS="${SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS:+${SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS};}consul|127.0.0.1|127.0.0.1/32|${consul_port}"
export SENTINEL_E2E_CONSUL_URL="http://127.0.0.1:${consul_port}"
export SENTINEL_E2E_CONSUL_TOKEN=""
export SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1
unset mysql_root_password

printf 'Disposable dependencies ready (MySQL 8.4.11, Consul 1.21.1).\n'
printf 'Container names: %s, %s\n' "$mysql_name" "$consul_name"
printf 'Executing acceptance command; these containers will be removed on exit.\n'
"$@" &
child_pid=$!
if wait "$child_pid"; then
  command_status=0
else
  command_status=$?
fi
child_pid=""
exit "$command_status"
