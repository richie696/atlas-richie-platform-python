#!/usr/bin/env bash
set -Eeuo pipefail

# Setup-window and runtime-locator stores reject symlinked parents; macOS
# TMPDIR commonly resolves through /var/folders, so use /private/tmp directly.
state_dir="$(mktemp -d /private/tmp/sentinel-t07-run.XXXXXX)"
chmod 700 "$state_dir"
repo_root="$(git -C "$(dirname "${BASH_SOURCE[0]}")/../../../.." rev-parse --show-toplevel)"
console_root="$repo_root/components/sentinel/sentinel-console"
dashboard_root="$repo_root/components/sentinel/dashboard-prototype"
docker_bin="${DOCKER_BIN:-docker}"
node_bin="${NODE_BINARY:-$(command -v node || true)}"
uv_bin="${UV_BINARY:-$(command -v uv || true)}"
if [[ -z "$node_bin" && -x /Users/richie696/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node ]]; then
  node_bin=/Users/richie696/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node
fi
if [[ ! -x "$node_bin" ]]; then
  printf 'Node.js executable not found; set NODE_BINARY to the workspace Node.js path.\n' >&2
  exit 69
fi
if [[ -z "$uv_bin" ]]; then
  printf 'uv executable not found; set UV_BINARY to the workspace uv path.\n' >&2
  exit 69
fi
server_pid=""
preview_pid=""
mock_preview_pid=""
collector_pid=""
rust_container=""
runtime_pids=()
available_loopback_port() {
  python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}
ui_port="${SENTINEL_T07_UI_PORT:-$(available_loopback_port)}"
console_port="${SENTINEL_T07_CONSOLE_PORT:-$(available_loopback_port)}"
metrics_port="${SENTINEL_T07_METRICS_PORT:-$(available_loopback_port)}"
mock_port="${SENTINEL_T07_MOCK_UI_PORT:-$(available_loopback_port)}"
managed_binding_id="${SENTINEL_T07_MANAGED_BINDING_ID:-t07-e2e-flow-20261016-0900}"
publication_profile_ids="${SENTINEL_T07_RULE_PUBLICATION_PROFILES:-sentinel-python-v1,sentinel-java-v1,sentinel-go-v1,sentinel-rust-v1}"
run_suffix="${SENTINEL_E2E_DOCKER_RUN_ID:-missing}"
run_suffix="${run_suffix:0:12}"
java_binding_id="${SENTINEL_T07_JAVA_BINDING_ID:-t07-java-e2e-$run_suffix}"
go_binding_id="${SENTINEL_T07_GO_BINDING_ID:-t07-go-e2e-$run_suffix}"
rust_binding_id="${SENTINEL_T07_RUST_BINDING_ID:-t07-rust-e2e-$run_suffix}"
managed_binding_ids="${SENTINEL_T07_MANAGED_RULE_BINDING_IDS:-$managed_binding_id,$java_binding_id,$go_binding_id,$rust_binding_id}"
managed_rule_profile="${SENTINEL_T07_RULE_PROFILE:-sentinel-python-v1}"
focused_rust_acceptance="${SENTINEL_T07_FOCUSED_RUST_ACCEPTANCE:-0}"
if [[ "$focused_rust_acceptance" == 1 ]]; then
  # T07.1 is currently open only for the Rust runtime's integrated rule path.
  # Keep bootstrap as the disposable environment prerequisite, but avoid
  # repeating the already-closed Mock, identity, Java, Go, metrics, and protocol
  # acceptance suites.
  export SENTINEL_T07_SKIP_MOCK_E2E=1
  export SENTINEL_T07_RUNTIME_RECEIPTS=1
  export SENTINEL_T07_PROTOCOL_INCIDENTS=0
  export SENTINEL_E2E_LIVE_MONITORING=0
  export SENTINEL_T053_ENABLE_T07_LIFECYCLE=0
  export SENTINEL_E2E_TEST_FILE=live-bootstrap.e2e.test.mjs
  export SENTINEL_E2E_TEST_NAME='LIVE T07.1 prerequisite provisioning: fresh MySQL\+Consul setup and first admin login'
fi

assert_port_free() {
  local port="$1"
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    printf 'Refusing to use already occupied acceptance port 127.0.0.1:%s.\n' "$port" >&2
    exit 73
  fi
}

listener_owned_by() {
  local port="$1"
  local expected_pid="$2"
  local listening_pids
  local listener_pid
  local process_group
  listening_pids="$(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -n "$listening_pids" ]] || return 1
  while IFS= read -r listener_pid; do
    process_group="$(ps -o pgid= -p "$listener_pid" 2>/dev/null | tr -d '[:space:]')"
    if [[ "$process_group" == "$expected_pid" ]]; then
      return 0
    fi
  done <<<"$listening_pids"
  printf 'Acceptance port 127.0.0.1:%s is not owned by launched process group %s (listeners: %s).\n' \
    "$port" "$expected_pid" "${listening_pids:-none}" >&2
  exit 70
}

stop_process_group() {
  local process_group="$1"
  [[ -n "$process_group" ]] || return 0
  if ps -axo pgid= | awk -v group="$process_group" '$1 == group {found=1} END {exit !found}'; then
    kill -TERM -- "-$process_group" >/dev/null 2>&1 || true
  fi
}

remove_owned_rust_container() {
  [[ -n "$rust_container" ]] || return 0
  local inspection
  local container_id
  local owner_run_id
  if ! inspection="$("$docker_bin" container inspect \
    --format '{{ .Id }} {{ index .Config.Labels "com.atlas-richie.sentinel-e2e.run" }}' \
    "$rust_container" 2>/dev/null)"; then
    return 0
  fi
  read -r container_id owner_run_id <<<"$inspection"
  if [[ "$container_id" =~ ^[0-9a-f]{64}$ && \
    "$owner_run_id" == "${SENTINEL_E2E_DOCKER_RUN_ID:-}" ]]; then
    "$docker_bin" rm --force --volumes "$container_id" >/dev/null 2>&1 || true
  else
    printf 'Refusing to remove Rust container without matching owner label: %s\n' \
      "$rust_container" >&2
  fi
}

assert_port_free "$ui_port"
assert_port_free "$console_port"
assert_port_free "$metrics_port"
assert_port_free "$mock_port"

cleanup() {
  local exit_status=$?
  trap - EXIT INT TERM HUP
  if [[ "${SENTINEL_T07_KEEP_SERVICES:-0}" == 1 && ( "$exit_status" == 0 || "${SENTINEL_T07_KEEP_ON_FAILURE:-0}" == 1 ) ]]; then
    printf 'Retaining %s live acceptance services and state for review under %s.\n' \
      "$([[ "$exit_status" == 0 ]] && printf successful || printf failed)" "$state_dir"
    printf 'Console: http://127.0.0.1:%s; dashboard: http://localhost:%s.\n' \
      "$console_port" "$ui_port"
    exit "$exit_status"
  fi
  for pid in "${runtime_pids[@]}" "$collector_pid" "$mock_preview_pid" "$preview_pid" "$server_pid"; do
    stop_process_group "$pid"
  done
  for pid in "${runtime_pids[@]}" "$collector_pid" "$mock_preview_pid" "$preview_pid" "$server_pid"; do
    [[ -z "$pid" ]] || wait "$pid" >/dev/null 2>&1 || true
  done
  remove_owned_rust_container
  rm -rf -- "$state_dir"
  exit "$exit_status"
}
trap cleanup EXIT INT TERM HUP

export SENTINEL_CONSOLE_SETUP_WINDOW_PATH="$state_dir/setup-window.json"
export SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH="$state_dir/bootstrap-authority.json"
export SENTINEL_CONSOLE_BOOTSTRAP_FINGERPRINT_KEY="$(openssl rand -base64 32)"
export SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH="$state_dir/runtime-locator.enc"
export SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_ACTIVE_KEY_ID="e2e-locator"
export SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_KEY_RING="e2e-locator=$(openssl rand -base64 32)"
export SENTINEL_CONSOLE_BOOTSTRAP_INITIALIZATION_LOCK_PATH="$state_dir/bootstrap-init.lock"
export SENTINEL_CONSOLE_BOOTSTRAP_IDEMPOTENCY_KEY="$(openssl rand -base64 32)"
export SENTINEL_CONSOLE_ACCOUNT_FINGERPRINT_ACTIVE_KEY_ID="e2e-account"
export SENTINEL_CONSOLE_ACCOUNT_FINGERPRINT_KEY_RING="e2e-account=$(openssl rand -base64 32)"
export SENTINEL_CONSOLE_CLIENT_IDENTITY_HMAC_KEY="$(openssl rand -base64 32)"
export SENTINEL_CONSOLE_SOURCE_SECRET_ACTIVE_KEY_ID="e2e-source-secret"
export SENTINEL_CONSOLE_SOURCE_SECRET_KEY_RING="e2e-source-secret=$(openssl rand -base64 32)"
export SENTINEL_CONSOLE_SOURCE_FINGERPRINT_ACTIVE_KEY_ID="e2e-source-fingerprint"
export SENTINEL_CONSOLE_SOURCE_FINGERPRINT_KEY_RING="e2e-source-fingerprint=$(openssl rand -base64 32)"
export SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID="e2e-rule-command"
export SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING="e2e-rule-command=$(openssl rand -base64 32)"
export SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS="consul"
export SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID="$publication_profile_ids"
export SENTINEL_CONSOLE_MANAGED_RULE_BINDING_IDS="$managed_binding_ids"
export SENTINEL_T07_MANAGED_BINDING_ID="$managed_binding_id"
export SENTINEL_T07_RULE_PROFILE="$managed_rule_profile"
export SENTINEL_T07_JAVA_BINDING_ID="$java_binding_id"
export SENTINEL_T07_GO_BINDING_ID="$go_binding_id"
export SENTINEL_T07_RUST_BINDING_ID="$rust_binding_id"
export SENTINEL_T07_JAVA_ENVIRONMENT_ID="${SENTINEL_T07_JAVA_ENVIRONMENT_ID:-sentinel-t07-java-$run_suffix}"
export SENTINEL_T07_GO_ENVIRONMENT_ID="${SENTINEL_T07_GO_ENVIRONMENT_ID:-sentinel-t07-go-$run_suffix}"
export SENTINEL_T07_RUST_ENVIRONMENT_ID="${SENTINEL_T07_RUST_ENVIRONMENT_ID:-sentinel-t07-rust-$run_suffix}"
export SENTINEL_T07_JAVA_APP_ID="${SENTINEL_T07_JAVA_APP_ID:-sentinel-java-demo}"
export SENTINEL_T07_GO_APP_ID="${SENTINEL_T07_GO_APP_ID:-sentinel-go-demo}"
export SENTINEL_T07_RUST_APP_ID="${SENTINEL_T07_RUST_APP_ID:-sentinel-rust-demo}"
export SENTINEL_CONSOLE_LOGIN_FAILURE_THRESHOLD=5
export SENTINEL_CONSOLE_LOGIN_FAILURE_WINDOW_SECONDS=300
export SENTINEL_CONSOLE_LOGIN_BLOCK_DURATION_SECONDS=60
export SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS="http://localhost:${ui_port}"
# Optional, narrowly-scoped target grants for live monitoring-source acceptance.
# The caller supplies an exact hostname/CIDR/port policy; never enable a blanket
# private-network or arbitrary loopback exception in the test runner.
if [[ -n "${SENTINEL_T07_MONITORING_TARGETS:-}" ]]; then
  export SENTINEL_CONSOLE_MONITORING_TARGETS="$SENTINEL_T07_MONITORING_TARGETS"
fi
export SENTINEL_CONSOLE_BIND_HOST=127.0.0.1
export SENTINEL_CONSOLE_PORT="$console_port"
export SENTINEL_CONSOLE_METRICS_BIND_HOST=127.0.0.1
export SENTINEL_CONSOLE_METRICS_PORT="$metrics_port"
export SENTINEL_CONSOLE_METRICS_SERVER_CERTIFICATE="$state_dir/server-cert.pem"
export SENTINEL_CONSOLE_METRICS_SERVER_PRIVATE_KEY="$state_dir/server-key.pem"
export SENTINEL_CONSOLE_METRICS_CLIENT_CA_CERTIFICATE="$state_dir/reporter-ca.pem"
export SENTINEL_CONSOLE_API_PROXY_TARGET="http://127.0.0.1:${console_port}"
export VITE_CONSOLE_MODE=live
export VITE_CONSOLE_API_BASE_URL="http://localhost:${ui_port}"
export BASE_URL="$VITE_CONSOLE_API_BASE_URL"
export SENTINEL_E2E_LIVE=1
export SENTINEL_E2E_LIVE_SOURCE=1
export SENTINEL_E2E_LIVE_MYSQL_CONSUL=1
export SENTINEL_E2E_TEST_FILE="${SENTINEL_E2E_TEST_FILE:-live-bootstrap.e2e.test.mjs}"
export SENTINEL_E2E_TEST_NAME="${SENTINEL_E2E_TEST_NAME:-LIVE fresh MySQL\\+Consul: setup, first admin login, and installed page reads}"
export SENTINEL_E2E_LIVE_ACCOUNT_AUTH=1
export SENTINEL_LIVE_E2E_USERNAME=admin
export SENTINEL_E2E_CONSOLE_ORIGIN="http://127.0.0.1:${console_port}"
if [[ "${SENTINEL_T07_KEEP_SERVICES:-0}" == 1 ]]; then
  # Live acceptance can opt into one visible, isolated Edge window for operator
  # review. All later suites still select their own headless lifecycle explicitly.
  if [[ "${SENTINEL_T07_VISIBLE_EDGE:-0}" == 1 ]]; then
    export SENTINEL_E2E_HEADLESS=0
    export SENTINEL_E2E_KEEP_EDGE=1
    review_start_url="${BASE_URL}/#/setup"
  else
    export SENTINEL_E2E_HEADLESS=1
    export SENTINEL_E2E_KEEP_EDGE=0
    review_start_url="${BASE_URL}/#/login?app=all&range=1h"
  fi
else
  export SENTINEL_E2E_HEADLESS=1
  review_start_url="${BASE_URL}/#/setup"
fi
export SENTINEL_E2E_START_URL="${SENTINEL_E2E_START_URL:-$review_start_url}"
if [[ -z "${SENTINEL_LIVE_E2E_PASSWORD:-}" ]]; then
  SENTINEL_LIVE_E2E_PASSWORD="$(openssl rand -hex 24)"
  export SENTINEL_LIVE_E2E_PASSWORD
fi

require_env() {
  local name="$1"
  local guidance="$2"
  if [[ -z "${!name:-}" ]]; then
    printf 'Required environment variable %s is missing: %s\n' "$name" "$guidance" >&2
    exit 64
  fi
}

require_env SENTINEL_E2E_DOCKER_RUN_ID "run through with_disposable_e2e_dependencies.sh"
require_env SENTINEL_E2E_MYSQL_CONTAINER "run through with_disposable_e2e_dependencies.sh"
require_env SENTINEL_E2E_MYSQL_DATABASE "disposable MySQL database is required"
require_env SENTINEL_E2E_MYSQL_USER "disposable MySQL user is required"
require_env SENTINEL_E2E_MYSQL_PASSWORD "disposable MySQL password is required"
require_env SENTINEL_E2E_MYSQL_PORT "disposable MySQL port is required"
require_env SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE "disposable MySQL CA is required"
require_env SENTINEL_E2E_CONSUL_URL "disposable Consul URL is required"

start_detached() {
  local cwd="$1"
  local log_path="$2"
  shift 2
  "$node_bin" "$console_root/tools/.t07_spawn_detached.mjs" \
    "$cwd" "$log_path" -- "$@"
}

mysql_owner_run_id="$("$docker_bin" inspect --format \
  '{{ index .Config.Labels "com.atlas-richie.sentinel-e2e.run" }}' \
  "$SENTINEL_E2E_MYSQL_CONTAINER")"
if [[ "$mysql_owner_run_id" != "$SENTINEL_E2E_DOCKER_RUN_ID" ]]; then
  printf 'Refusing to use MySQL container without this run owner label.\n' >&2
  exit 73
fi
mysql_database="$SENTINEL_E2E_MYSQL_DATABASE"
mysql_user="$SENTINEL_E2E_MYSQL_USER"

openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 1 \
  -keyout "$state_dir/reporter-ca-key.pem" -out "$state_dir/reporter-ca.pem" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -subj "/CN=Sentinel T07 E2E Reporter CA" >/dev/null 2>&1
openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout "$state_dir/server-key.pem" -out "$state_dir/server.csr" \
  -subj "/CN=localhost" >/dev/null 2>&1
printf '%s\n' 'subjectAltName=DNS:localhost,DNS:host.docker.internal,IP:127.0.0.1' \
  'extendedKeyUsage=serverAuth' 'keyUsage=digitalSignature,keyEncipherment' \
  >"$state_dir/server.ext"
openssl x509 -req -sha256 -days 1 -in "$state_dir/server.csr" \
  -CA "$state_dir/reporter-ca.pem" -CAkey "$state_dir/reporter-ca-key.pem" \
  -CAcreateserial -extfile "$state_dir/server.ext" \
  -out "$state_dir/server-cert.pem" >/dev/null 2>&1
chmod 600 "$state_dir"/*key.pem

printf 'Owner-verified disposable DB: host=127.0.0.1 port=%s database=%s user=%s.\n' \
  "$SENTINEL_E2E_MYSQL_PORT" "$mysql_database" "$mysql_user"
printf 'MySQL TLS CA certificate path: %s\n' "$SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"
printf 'Isolated Consul URL: %s\n' "$SENTINEL_E2E_CONSUL_URL"

uv_args=(run --project "$console_root" --extra mysql --extra server --extra collector --extra nacos-grpc --extra test)
console_cli() {
  "$uv_bin" "${uv_args[@]}" sentinel-console "$@"
}

printf 'E2E runtime: source checkout via uv; no wheel build, pip installation, or package publication.\n'
console_cli setup-window open
server_pid="$(start_detached "$console_root" "$state_dir/console.log" \
  "$uv_bin" "${uv_args[@]}" sentinel-console serve)"
preview_pid="$(start_detached "$dashboard_root" "$state_dir/vite.log" \
  "$node_bin" node_modules/vite/bin/vite.js --host 127.0.0.1 --port "$ui_port" --strictPort)"

printf 'Isolated run ready: UI http://localhost:%s; Console API http://127.0.0.1:%s; Metrics mTLS listener 127.0.0.1:%s.\n' \
  "$ui_port" "$console_port" "$metrics_port"
printf 'Managed rule binding ID for receipt acceptance: %s\n' "$managed_binding_id"
printf 'Managed publication profiles: %s; binding allowlist: %s.\n' \
  "$publication_profile_ids" "$managed_binding_ids"
printf 'Primary live rule profile: %s.\n' "$managed_rule_profile"
printf 'Java/Go managed binding IDs: %s / %s.\n' "$java_binding_id" "$go_binding_id"
printf 'Temporary acceptance state directory: %s\n' "$state_dir"
for attempt in {1..90}; do
  if listener_owned_by "$console_port" "$server_pid" && \
    listener_owned_by "$ui_port" "$preview_pid" && \
    curl --fail --silent "http://127.0.0.1:${console_port}/healthz" >/dev/null && \
    curl --fail --silent "http://localhost:${ui_port}/" >/dev/null; then
    break
  fi
  if [[ "$attempt" == 90 ]]; then
    printf 'Console or Vite did not become ready; inspect logs under %s.\n' "$state_dir" >&2
    exit 70
  fi
  sleep 1
done
mock_preview_pid="$(start_detached "$dashboard_root" "$state_dir/mock-vite.log" \
  env -u VITE_CONSOLE_API_BASE_URL -u SENTINEL_CONSOLE_API_PROXY_TARGET \
    VITE_CONSOLE_MODE=mock "$node_bin" node_modules/vite/bin/vite.js \
    --host 127.0.0.1 --port "$mock_port" --strictPort)"
for attempt in {1..30}; do
  if listener_owned_by "$mock_port" "$mock_preview_pid" && \
    curl --fail --silent "http://localhost:${mock_port}/" >/dev/null; then
    break
  fi
  if [[ "$attempt" == 30 ]]; then
    printf 'Mock dashboard did not become ready on 127.0.0.1:%s; inspect %s/mock-vite.log.\n' \
      "$mock_port" "$state_dir" >&2
    exit 70
  fi
  sleep 1
done
(
  cd "$dashboard_root"
  if [[ "${SENTINEL_T07_SKIP_MOCK_E2E:-0}" == 1 ]]; then
    printf 'Skipping the already-verified full Mock E2E by explicit focused-run request.\n'
  else
    env -u SENTINEL_E2E_TEST_FILE -u SENTINEL_E2E_TEST_FILES -u SENTINEL_E2E_TEST_NAME \
      -u SENTINEL_E2E_LIVE -u SENTINEL_E2E_LIVE_SOURCE \
      -u SENTINEL_E2E_LIVE_MYSQL_CONSUL -u SENTINEL_E2E_LIVE_ACCOUNT_AUTH \
      -u SENTINEL_E2E_LIVE_AUTHENTICATED -u SENTINEL_E2E_LIVE_BOOTSTRAP_INITIALIZED \
      -u SENTINEL_E2E_LIVE_RULES -u SENTINEL_E2E_LIVE_MONITORING \
      -u SENTINEL_E2E_KEEP_EDGE \
      BASE_URL="http://localhost:${mock_port}" \
      "$node_bin" scripts/test/run-edge-e2e.mjs
  fi
)
kill "$mock_preview_pid" >/dev/null 2>&1 || true
wait "$mock_preview_pid" >/dev/null 2>&1 || true
mock_preview_pid=""
(
  cd "$dashboard_root"
  SENTINEL_E2E_HEADLESS="${SENTINEL_E2E_HEADLESS:-1}" \
    SENTINEL_E2E_KEEP_EDGE="${SENTINEL_E2E_KEEP_EDGE:-0}" \
    "$node_bin" scripts/test/run-edge-e2e.mjs
)
  if [[ "${SENTINEL_T07_FOCUSED_MONITORING_ONLY:-0}" != 1 && "$focused_rust_acceptance" != 1 ]]; then
    (
      cd "$dashboard_root"
      SENTINEL_E2E_TEST_FILE=live-identity.e2e.test.mjs \
        SENTINEL_E2E_TEST_NAME='LIVE identity: viewer can read, cannot manage, and account re-enable never revives its revoked session' \
        SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
        "$node_bin" scripts/test/run-edge-e2e.mjs
    )
  else
    printf 'Skipping unrelated live identity E2E for focused acceptance.\n'
  fi
if [[ "${SENTINEL_T07_FOCUSED_MONITORING_ONLY:-0}" != 1 || "$focused_rust_acceptance" == 1 ]]; then
  collector_pid="$(start_detached "$console_root" "$state_dir/collector.log" \
    "$uv_bin" "${uv_args[@]}" sentinel-console serve-metrics)"
  for attempt in {1..30}; do
    if listener_owned_by "$metrics_port" "$collector_pid"; then break; fi
    if [[ "$attempt" == 30 ]]; then
      printf 'Metrics Collector did not bind 127.0.0.1:%s; inspect %s/collector.log.\n' \
        "$metrics_port" "$state_dir" >&2
      exit 70
    fi
    sleep 1
  done
  if [[ "$focused_rust_acceptance" != 1 ]]; then
    (
      cd "$dashboard_root"
      SENTINEL_E2E_TEST_FILE=live-rules.e2e.test.mjs \
        SENTINEL_E2E_TEST_NAME='LIVE RULE-01' \
        SENTINEL_E2E_LIVE_RULES=1 \
        SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
        "$node_bin" scripts/test/run-edge-e2e.mjs
    )
  else
    printf 'Focused Rust T07.1 run: starting Collector without replaying the completed baseline Rules E2E.\n'
  fi
else
  printf 'Skipping unrelated live rules and Metrics Collector E2E for focused HOST lifecycle acceptance.\n'
fi
if [[ "${SENTINEL_T07_RUNTIME_RECEIPTS:-0}" == 1 ]]; then
  java_demo_port=""
  go_demo_port=""
  rust_demo_port=""
  rust_root="$repo_root/components/sentinel/demos/rust-sentinel"
  case "$(uname -m)" in
    arm64|aarch64) rust_platform="linux/arm64" ;;
    x86_64|amd64) rust_platform="linux/amd64" ;;
    *) printf 'Unsupported host architecture for Rust acceptance: %s.\n' "$(uname -m)" >&2; exit 69 ;;
  esac
  rust_builder_image="${SENTINEL_T07_RUST_BUILDER_IMAGE:-rust:1.89}"
  rust_runtime_image="${SENTINEL_T07_RUST_RUNTIME_IMAGE:-debian:bookworm-slim}"
  "$docker_bin" run --rm --platform "$rust_platform" \
    -v "$rust_root:/work" -w /work "$rust_builder_image" \
    cargo build --locked --bin sentinel-rust-runtime-demo
  runtime_languages=(JAVA GO RUST)
  if [[ "$focused_rust_acceptance" == 1 ]]; then
    runtime_languages=(RUST)
  fi
  for language in "${runtime_languages[@]}"; do
    if [[ "$language" == JAVA ]]; then
      language_lower=java
      binding_id="$java_binding_id"
      environment_id="$SENTINEL_T07_JAVA_ENVIRONMENT_ID"
      app_id="$SENTINEL_T07_JAVA_APP_ID"
      profile_id="sentinel-java-v1"
      instance_id="t07-java-worker-${SENTINEL_E2E_DOCKER_RUN_ID:0:12}"
      process_id="t07-java-process-${SENTINEL_E2E_DOCKER_RUN_ID:0:12}"
      demo_root="$repo_root/components/sentinel/demos/java-nacos-sentinel"
      demo_port="$(available_loopback_port)"
    elif [[ "$language" == GO ]]; then
      language_lower=go
      binding_id="$go_binding_id"
      environment_id="$SENTINEL_T07_GO_ENVIRONMENT_ID"
      app_id="$SENTINEL_T07_GO_APP_ID"
      profile_id="sentinel-go-v1"
      instance_id="t07-go-worker-${SENTINEL_E2E_DOCKER_RUN_ID:0:12}"
      process_id="t07-go-process-${SENTINEL_E2E_DOCKER_RUN_ID:0:12}"
      demo_root="$repo_root/components/sentinel/demos/go-nacos-sentinel"
      demo_port="$(available_loopback_port)"
    else
      language_lower=rust
      binding_id="$rust_binding_id"
      environment_id="$SENTINEL_T07_RUST_ENVIRONMENT_ID"
      app_id="$SENTINEL_T07_RUST_APP_ID"
      profile_id="sentinel-rust-v1"
      instance_id="t07-rust-worker-${SENTINEL_E2E_DOCKER_RUN_ID:0:12}"
      process_id="t07-rust-process-${SENTINEL_E2E_DOCKER_RUN_ID:0:12}"
      demo_root="$rust_root"
      demo_port="$(available_loopback_port)"
    fi
    (
      cd "$dashboard_root"
      SENTINEL_T07_BINDING_ID="$binding_id" \
        SENTINEL_T07_BINDING_ENVIRONMENT_ID="$environment_id" \
        SENTINEL_T07_BINDING_APP_ID="$app_id" \
        SENTINEL_T07_RULE_PROFILE="$profile_id" \
        SENTINEL_T07_SEED_EMPTY_SNAPSHOT=1 \
        SENTINEL_T07_MANAGED_BINDING_ID="$binding_id" \
        SENTINEL_E2E_TEST_FILE=live-rules.e2e.test.mjs \
        SENTINEL_E2E_TEST_NAME='LIVE RULE-01 slice: register a Consul binding from the UI and read the persisted binding back' \
        SENTINEL_E2E_LIVE_RULES=1 \
        SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
        "$node_bin" scripts/test/run-edge-e2e.mjs
    )
    (
      cd "$dashboard_root"
      SENTINEL_T07_RULE_PROFILE="$profile_id" \
        SENTINEL_T07_DEMO_RESOURCE='GET /api/hello' \
        SENTINEL_T07_MANAGED_BINDING_ID="$binding_id" \
        SENTINEL_E2E_TEST_FILE=live-rules.e2e.test.mjs \
        SENTINEL_E2E_TEST_NAME='LIVE RULE-01: save, validate, freeze, publish to Consul, and read back the full rule set' \
        SENTINEL_E2E_LIVE_RULES=1 \
        SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
        "$node_bin" scripts/test/run-edge-e2e.mjs
    )

    reporter_id="t07-${language_lower}-reporter-${SENTINEL_E2E_DOCKER_RUN_ID:0:12}"
    principal="t07-${language_lower}-principal-${SENTINEL_E2E_DOCKER_RUN_ID:0:12}"
    client_cert="$state_dir/${language_lower}-client-cert.pem"
    client_key="$state_dir/${language_lower}-client-key.pem"
    client_csr="$state_dir/${language_lower}-client.csr"
    client_ext="$state_dir/${language_lower}-client.ext"
    printf '%s\n' 'extendedKeyUsage=clientAuth' \
      'keyUsage=digitalSignature,keyEncipherment' >"$client_ext"
    openssl req -newkey rsa:2048 -sha256 -nodes -keyout "$client_key" \
      -out "$client_csr" -subj "/CN=$principal" >/dev/null 2>&1
    openssl x509 -req -sha256 -days 1 -in "$client_csr" \
      -CA "$state_dir/reporter-ca.pem" -CAkey "$state_dir/reporter-ca-key.pem" \
      -CAcreateserial -extfile "$client_ext" -out "$client_cert" >/dev/null 2>&1
    chmod 600 "$client_key"
    certificate_sha256="$(openssl x509 -in "$client_cert" -noout -fingerprint -sha256 | sed 's/.*=//;s/://g' | tr '[:upper:]' '[:lower:]')"
    console_cli metrics-reporter enroll \
      --principal "$principal" --certificate-sha256 "$certificate_sha256" \
      --reporter-id "$reporter_id" --environment-id "$environment_id" \
      --app-id "$app_id" --instance-id "$instance_id" --process-id "$process_id"

    if [[ "$language" == JAVA ]]; then
      client_keystore="$state_dir/java-client.p12"
      client_keystore_password="$(openssl rand -hex 24)"
      openssl pkcs12 -export -in "$client_cert" -inkey "$client_key" \
        -certfile "$state_dir/reporter-ca.pem" -out "$client_keystore" \
        -passout "pass:$client_keystore_password" >/dev/null 2>&1
      classpath="$demo_root/target/classes:$(<"$demo_root/target/classpath.txt")"
      runtime_pid="$(start_detached "$demo_root" "$state_dir/java-demo.log" env \
        RULE_SOURCE_PROVIDER=consul RULE_SOURCE_PROFILE=managed-envelope-v1 \
        RULE_BINDING_ID="$binding_id" RULE_PROFILE_ID="$profile_id" \
        CONSUL_URL="$SENTINEL_E2E_CONSUL_URL" CONSUL_KEY="sentinel/e2e/$binding_id/flow-rules.json" \
        CONSUL_DATACENTER=dc1 DEMO_PORT="$demo_port" \
        METRICS_COLLECTOR_URL="https://127.0.0.1:$metrics_port" \
        METRICS_REPORTER_ID="$reporter_id" METRICS_CLIENT_PKCS12="$client_keystore" \
        METRICS_CLIENT_PKCS12_PASSWORD="$client_keystore_password" \
        METRICS_COLLECTOR_CA="$state_dir/reporter-ca.pem" \
        java -cp "$classpath" io.atlasrichie.sentinel.demo.JavaSentinelDemo)"
    elif [[ "$language" == GO ]]; then
      runtime_pid="$(start_detached "$demo_root" "$state_dir/go-demo.log" env \
        RULE_SOURCE_PROVIDER=consul RULE_SOURCE_PROFILE=managed-envelope-v1 \
        RULE_BINDING_ID="$binding_id" RULE_PROFILE_ID="$profile_id" \
        CONSUL_URL="$SENTINEL_E2E_CONSUL_URL" CONSUL_KEY="sentinel/e2e/$binding_id/flow-rules.json" \
        CONSUL_DATACENTER=dc1 DEMO_PORT="$demo_port" \
        METRICS_COLLECTOR_URL="https://127.0.0.1:$metrics_port" \
        METRICS_REPORTER_ID="$reporter_id" METRICS_CLIENT_CERT="$client_cert" \
        METRICS_CLIENT_KEY="$client_key" METRICS_COLLECTOR_CA="$state_dir/reporter-ca.pem" \
        go run .)"
    else
      rust_consul_url="${SENTINEL_E2E_CONSUL_URL/127.0.0.1/host.docker.internal}"
      rust_container="sentinel-t07-rust-${SENTINEL_E2E_DOCKER_RUN_ID:0:12}"
      "$docker_bin" run --detach --platform "$rust_platform" \
        --name "$rust_container" \
        --label "com.atlas-richie.sentinel-e2e.run=$SENTINEL_E2E_DOCKER_RUN_ID" \
        --add-host=host.docker.internal:host-gateway \
        --publish "127.0.0.1:$demo_port:18094" \
        --volume "$rust_root/target/debug/sentinel-rust-runtime-demo:/opt/sentinel-rust-runtime-demo:ro" \
        --volume "$client_cert:/run/sentinel/client-cert.pem:ro" \
        --volume "$client_key:/run/sentinel/client-key.pem:ro" \
        --volume "$state_dir/reporter-ca.pem:/run/sentinel/reporter-ca.pem:ro" \
        --env HTTP_ADDR=0.0.0.0:18094 \
        --env RULE_SOURCE_PROVIDER=consul \
        --env RULE_SOURCE_PROFILE=managed-envelope-v1 \
        --env RULE_BINDING_ID="$binding_id" \
        --env RULE_PROFILE_ID="$profile_id" \
        --env SENTINEL_T07_DEMO_RESOURCE='GET /api/hello' \
        --env CONSUL_URL="$rust_consul_url" \
        --env CONSUL_KEY="sentinel/e2e/$binding_id/flow-rules.json" \
        --env CONSUL_DATACENTER=dc1 \
        --env METRICS_COLLECTOR_URL="https://host.docker.internal:$metrics_port" \
        --env METRICS_REPORTER_ID="$reporter_id" \
        --env METRICS_CLIENT_CERT=/run/sentinel/client-cert.pem \
        --env METRICS_CLIENT_KEY=/run/sentinel/client-key.pem \
        --env METRICS_COLLECTOR_CA=/run/sentinel/reporter-ca.pem \
        "$rust_runtime_image" /opt/sentinel-rust-runtime-demo >/dev/null
      runtime_pid=""
    fi
    [[ -z "$runtime_pid" ]] || runtime_pids+=("$runtime_pid")
    if [[ "$language" == JAVA ]]; then
      java_demo_port="$demo_port"
    elif [[ "$language" == GO ]]; then
      go_demo_port="$demo_port"
    else
      rust_demo_port="$demo_port"
      for attempt in {1..90}; do
        if curl --fail --silent "http://127.0.0.1:$demo_port/health" >/dev/null; then break; fi
        if [[ "$attempt" == 90 ]]; then
          "$docker_bin" logs --tail 60 "$rust_container" >&2 || true
          printf 'Rust Runtime did not become ready on 127.0.0.1:%s.\n' "$demo_port" >&2
          exit 70
        fi
        sleep 1
      done
      (
        cd "$dashboard_root"
        SENTINEL_T07_RUST_BINDING_ID="$binding_id" \
          SENTINEL_T07_RUST_DEMO_URL="http://127.0.0.1:$demo_port" \
          SENTINEL_T07_DEMO_RESOURCE='GET /api/hello' \
          SENTINEL_E2E_TEST_FILE=live-rules.e2e.test.mjs \
          SENTINEL_E2E_TEST_NAME='LIVE RUST-RULES-01' \
          SENTINEL_E2E_LIVE_RULES=1 \
          SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
          "$node_bin" scripts/test/run-edge-e2e.mjs
      )
    fi
    export "SENTINEL_T07_RECEIPT_BINDING_ID=$binding_id"
    export "SENTINEL_T07_RECEIPT_INSTANCE_ID=$instance_id"
    (
      cd "$dashboard_root"
      SENTINEL_T07_RECEIPT_BINDING_ID="$binding_id" \
        SENTINEL_T07_RECEIPT_INSTANCE_ID="$instance_id" \
        SENTINEL_T07_MANAGED_BINDING_ID="$binding_id" \
        SENTINEL_E2E_TEST_FILE=live-rules.e2e.test.mjs \
        SENTINEL_E2E_TEST_NAME='LIVE RECEIPT-01' \
        SENTINEL_E2E_LIVE_RULES=1 \
        SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
        "$node_bin" scripts/test/run-edge-e2e.mjs
    )
    if [[ "$language" == RUST ]]; then
      printf 'Retaining Rust runtime container %s.\n' "$rust_container"
    else
      printf 'Retaining %s runtime service with log %s/%s-demo.log.\n' \
        "$language" "$state_dir" "$language_lower"
    fi
  done
  if [[ "$focused_rust_acceptance" != 1 ]]; then
    (
      cd "$dashboard_root"
      SENTINEL_T07_JAVA_DEMO_URL="http://127.0.0.1:$java_demo_port" \
        SENTINEL_T07_GO_DEMO_URL="http://127.0.0.1:$go_demo_port" \
        SENTINEL_E2E_TEST_FILE=live-metrics.e2e.test.mjs \
        SENTINEL_E2E_TEST_NAME='LIVE OBS-01: Java and Go Metrics V2 facts match the realtime charts' \
        SENTINEL_E2E_LIVE_METRICS=1 \
        SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
        "$node_bin" scripts/test/run-edge-e2e.mjs
    )
    (
      cd "$dashboard_root"
      SENTINEL_T07_JAVA_BINDING_ID="$java_binding_id" \
        SENTINEL_T07_GO_BINDING_ID="$go_binding_id" \
        SENTINEL_T07_RUST_BINDING_ID="$rust_binding_id" \
        SENTINEL_E2E_TEST_FILE=live-rules.e2e.test.mjs \
        SENTINEL_E2E_TEST_NAME='LIVE RULE-OBS-01' \
        SENTINEL_E2E_LIVE_RULES=1 \
        SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
        "$node_bin" scripts/test/run-edge-e2e.mjs
    )
  else
    printf 'Focused Rust T07.1 run: skipping already-closed Java/Go metrics and cross-runtime rule-observation suites.\n'
  fi
fi
if [[ "${SENTINEL_T07_PROTOCOL_INCIDENTS:-0}" == 1 ]]; then
  # The consumer-role driver is test tooling, not a Console runtime dependency.
  # Resolve the consumer driver's narrow HTTP dependency through the same
  # workspace source environment used by the Console runtime.
  "$uv_bin" run --project "$console_root" --extra mysql --extra server --extra collector --extra nacos-grpc --extra test python -c 'import httpx'
  SENTINEL_T07_STATE_DIR="$state_dir" \
    SENTINEL_T07_UV_BINARY="$uv_bin" \
    SENTINEL_T07_CONSOLE_ROOT="$console_root" \
    SENTINEL_T07_DASHBOARD_ROOT="$dashboard_root" \
    SENTINEL_T07_NODE_BINARY="$node_bin" \
    SENTINEL_T07_REPO_ROOT="$repo_root" \
    SENTINEL_T07_METRICS_PORT="$metrics_port" \
    bash "$console_root/tools/.t07_protocol_incident_acceptance.sh"
fi
if [[ "${SENTINEL_E2E_LIVE_MONITORING:-0}" == 1 ]]; then
  : "${SENTINEL_T07_PROMETHEUS_ENDPOINT:=${SENTINEL_T053_PROMETHEUS_ENDPOINT:-}}"
  : "${SENTINEL_T07_PROMETHEUS_JOB:=t053-complete}"
  : "${SENTINEL_T07_PROMETHEUS_HOST_LABEL:=host}"
  : "${SENTINEL_T07_PROMETHEUS_HOST_ID:=synthetic-node-a}"
  export SENTINEL_T07_PROMETHEUS_ENDPOINT
  export SENTINEL_T07_PROMETHEUS_JOB
  export SENTINEL_T07_PROMETHEUS_HOST_LABEL
  export SENTINEL_T07_PROMETHEUS_HOST_ID
  (
    cd "$dashboard_root"
    : "${SENTINEL_T07_PROMETHEUS_ENDPOINT:?set the authorized loopback Prometheus endpoint}"
    SENTINEL_E2E_TEST_FILE=live-monitoring-source.e2e.test.mjs \
      SENTINEL_E2E_TEST_NAME='LIVE monitoring source: Edge registration reads real HOST samples' \
      SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
      "$node_bin" scripts/test/run-edge-e2e.mjs
  )
  (
    cd "$dashboard_root"
    SENTINEL_E2E_TEST_FILE=live-monitoring-source.e2e.test.mjs \
      SENTINEL_E2E_TEST_NAME='LIVE monitoring source: an unverified empty selector remains an honest empty HOST chart' \
      SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
      "$node_bin" scripts/test/run-edge-e2e.mjs
  )
  if [[ "${SENTINEL_T053_ENABLE_T07_LIFECYCLE:-0}" == 1 ]]; then
    (
      cd "$dashboard_root"
      SENTINEL_E2E_TEST_FILE=live-monitoring-source.e2e.test.mjs \
        SENTINEL_E2E_TEST_NAME='LIVE monitoring source: stopped exporter is stale, recovery restores real chart samples' \
        SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
        "$node_bin" scripts/test/run-edge-e2e.mjs
    )
  fi
fi
if [[ "${SENTINEL_T07_KEEP_SERVICES:-0}" == 1 ]]; then
  printf 'Browser journey passed. Keep this shell service processes alive for review.\n'
  printf 'Logs: %s/console.log, %s/vite.log, %s/collector.log.\n' \
    "$state_dir" "$state_dir" "$state_dir"
  exit 0
fi
wait "$server_pid"
