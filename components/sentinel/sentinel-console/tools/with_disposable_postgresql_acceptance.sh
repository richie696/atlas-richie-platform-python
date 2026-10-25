#!/usr/bin/env bash

# Run PostgreSQL acceptance against a unique loopback-only disposable container.
set -Eeuo pipefail

if [[ $# -eq 0 ]]; then
  printf 'Usage: %s <command> [args...]\n' "$0" >&2
  exit 64
fi

docker_bin="${DOCKER_BIN:-docker}"
if ! command -v "$docker_bin" >/dev/null 2>&1 || ! "$docker_bin" info >/dev/null 2>&1; then
  printf 'Docker CLI or daemon is unavailable; no container was started.\n' >&2
  exit 69
fi
if ! command -v openssl >/dev/null 2>&1; then
  printf 'Required local utility not found: openssl\n' >&2
  exit 69
fi

run_id="$(openssl rand -hex 16)"
container_name="sentinel-e2e-postgres-${run_id}"
database_name="sentinel_console_test_${run_id}"
database_user='sentinel_e2e'
database_password="$(openssl rand -hex 24)"
temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/sentinel-postgres-e2e.XXXXXX")"
container_started=0

if "$docker_bin" container inspect "$container_name" >/dev/null 2>&1; then
  printf 'Refusing to reuse existing container name: %s\n' "$container_name" >&2
  exit 73
fi

cleanup() {
  local exit_status=$?
  local inspection
  local container_id
  local owner_run_id
  trap - EXIT INT TERM HUP
  if [[ "$container_started" == 1 ]]; then
    if inspection="$("$docker_bin" container inspect \
      --format '{{ .Id }} {{ index .Config.Labels "com.atlas-richie.sentinel-e2e.run" }}' \
      "$container_name" 2>/dev/null)"; then
      read -r container_id owner_run_id <<<"$inspection"
      if [[ "$container_id" =~ ^[0-9a-f]{64}$ && "$owner_run_id" == "$run_id" ]]; then
        "$docker_bin" rm --force --volumes "$container_id" >/dev/null 2>&1 || true
      fi
    fi
    if "$docker_bin" container inspect "$container_name" >/dev/null 2>&1; then
      printf 'Failed to remove run-owned container %s.\n' "$container_name" >&2
      [[ "$exit_status" != 0 ]] || exit_status=70
    fi
  fi
  if [[ -n "$temporary_directory" ]]; then
    rm -f -- \
      "$temporary_directory/ca.pem" \
      "$temporary_directory/ca-key.pem" \
      "$temporary_directory/ca.srl" \
      "$temporary_directory/server-cert.pem" \
      "$temporary_directory/server-key.pem" \
      "$temporary_directory/server.csr" \
      "$temporary_directory/server.ext"
    rmdir -- "$temporary_directory" >/dev/null 2>&1 || true
  fi
  unset database_password
  exit "$exit_status"
}

handle_signal() {
  local signal="$1"
  local exit_status="$2"
  trap - INT TERM HUP
  if [[ -n "${child_pid:-}" ]]; then
    kill -s "$signal" "$child_pid" >/dev/null 2>&1 || true
    wait "$child_pid" >/dev/null 2>&1 || true
    child_pid=''
  fi
  exit "$exit_status"
}

trap cleanup EXIT
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM
trap 'handle_signal HUP 129' HUP

openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 1 \
  -keyout "$temporary_directory/ca-key.pem" \
  -out "$temporary_directory/ca.pem" \
  -addext 'basicConstraints=critical,CA:TRUE' \
  -addext 'keyUsage=critical,keyCertSign,cRLSign' \
  -addext 'subjectKeyIdentifier=hash' \
  -subj '/CN=Sentinel PostgreSQL E2E Temporary CA' >/dev/null 2>&1
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
chmod 0444 "$temporary_directory/ca.pem" \
  "$temporary_directory/server-cert.pem" "$temporary_directory/server-key.pem"

container_started=1
POSTGRES_PASSWORD="$database_password" "$docker_bin" run --detach \
  --name "$container_name" \
  --label "com.atlas-richie.sentinel-e2e.run=${run_id}" \
  --publish '127.0.0.1::5432/tcp' \
  --mount "type=bind,source=${temporary_directory},target=/sentinel-e2e-certs,readonly" \
  --env POSTGRES_DB="$database_name" \
  --env POSTGRES_USER="$database_user" \
  --env POSTGRES_PASSWORD \
  postgres:16.10 \
  sh -c 'cp /sentinel-e2e-certs/server-cert.pem /var/lib/postgresql/server-cert.pem && cp /sentinel-e2e-certs/server-key.pem /var/lib/postgresql/server-key.pem && chown postgres:postgres /var/lib/postgresql/server-cert.pem /var/lib/postgresql/server-key.pem && chmod 600 /var/lib/postgresql/server-key.pem && exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/var/lib/postgresql/server-cert.pem -c ssl_key_file=/var/lib/postgresql/server-key.pem' \
  >/dev/null

host_port() {
  local mapping
  mapping="$("$docker_bin" port "$container_name" '5432/tcp')"
  if [[ "$mapping" != 127.0.0.1:* ]]; then
    printf 'Expected loopback-only PostgreSQL mapping; got %s\n' "$mapping" >&2
    return 1
  fi
  printf '%s' "${mapping##*:}"
}

postgres_port="$(host_port)"
ready=0
for attempt in {1..60}; do
  if "$docker_bin" exec "$container_name" pg_isready \
    --quiet --username="$database_user" --dbname="$database_name"; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  printf 'Disposable PostgreSQL did not become ready.\n' >&2
  exit 1
fi

export SENTINEL_CONSOLE_TEST_POSTGRES_URL="postgresql+psycopg://${database_user}:${database_password}@127.0.0.1:${postgres_port}/${database_name}"
export SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE="$temporary_directory/ca.pem"
export SENTINEL_E2E_POSTGRES_HOST=127.0.0.1
export SENTINEL_E2E_POSTGRES_PORT="$postgres_port"
export SENTINEL_E2E_POSTGRES_DATABASE="$database_name"
export SENTINEL_E2E_POSTGRES_USER="$database_user"
export SENTINEL_E2E_POSTGRES_PASSWORD="$database_password"
"$@" &
child_pid=$!
wait "$child_pid"
child_status=$?
child_pid=''
exit "$child_status"
