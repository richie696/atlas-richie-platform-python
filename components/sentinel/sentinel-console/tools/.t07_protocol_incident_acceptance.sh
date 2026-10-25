#!/usr/bin/env bash
set -Eeuo pipefail

: "${SENTINEL_T07_STATE_DIR:?acceptance state directory is required}"
: "${SENTINEL_T07_UV_BINARY:?uv executable is required}"
: "${SENTINEL_T07_CONSOLE_ROOT:?Console source project root is required}"
: "${SENTINEL_T07_DASHBOARD_ROOT:?dashboard root is required}"
: "${SENTINEL_T07_NODE_BINARY:?Node.js executable is required}"
: "${SENTINEL_T07_REPO_ROOT:?repository root is required}"
: "${SENTINEL_T07_METRICS_PORT:?Collector port is required}"
: "${SENTINEL_E2E_DOCKER_RUN_ID:?disposable run identity is required}"

state_dir="$SENTINEL_T07_STATE_DIR"
uv_bin="$SENTINEL_T07_UV_BINARY"
console_root="$SENTINEL_T07_CONSOLE_ROOT"
dashboard_root="$SENTINEL_T07_DASHBOARD_ROOT"
node_bin="$SENTINEL_T07_NODE_BINARY"
repo_root="$SENTINEL_T07_REPO_ROOT"
metrics_port="$SENTINEL_T07_METRICS_PORT"
console_root="$repo_root/components/sentinel/sentinel-console"
run_suffix="${SENTINEL_E2E_DOCKER_RUN_ID:0:12}"

enroll_reporter() {
  local name="$1"
  local reporter_id="$2"
  local principal="$3"
  local environment_id="$4"
  local app_id="$5"
  local instance_id="$6"
  local process_id="$7"
  local cert="$state_dir/${name}-client-cert.pem"
  local key="$state_dir/${name}-client-key.pem"
  local csr="$state_dir/${name}-client.csr"
  local ext="$state_dir/${name}-client.ext"
  printf '%s\n' 'extendedKeyUsage=clientAuth' \
    'keyUsage=digitalSignature,keyEncipherment' >"$ext"
  openssl req -newkey rsa:2048 -sha256 -nodes -keyout "$key" \
    -out "$csr" -subj "/CN=$principal" >/dev/null 2>&1
  openssl x509 -req -sha256 -days 1 -in "$csr" \
    -CA "$state_dir/reporter-ca.pem" -CAkey "$state_dir/reporter-ca-key.pem" \
    -CAcreateserial -extfile "$ext" -out "$cert" >/dev/null 2>&1
  chmod 600 "$key"
  local fingerprint
  fingerprint="$(openssl x509 -in "$cert" -noout -fingerprint -sha256 | sed 's/.*=//;s/://g' | tr '[:upper:]' '[:lower:]')"
  "$uv_bin" run --project "$console_root" --extra mysql --extra server --extra collector --extra nacos-grpc --extra test sentinel-console metrics-reporter enroll \
    --principal "$principal" --certificate-sha256 "$fingerprint" \
    --reporter-id "$reporter_id" --environment-id "$environment_id" \
    --app-id "$app_id" --instance-id "$instance_id" --process-id "$process_id" >/dev/null
  printf '%s\n%s\n' "$cert" "$key"
}

run_matrix_browser() {
  local agent_state="$1" incident_state="$2" revoked="${3:-0}"
  (
    cd "$dashboard_root"
    SENTINEL_T07_CONSUMER_REPORTER_ID="$consumer_reporter_id" \
      SENTINEL_T07_CONSUMER_INSTANCE_ID="$consumer_instance_id" \
      SENTINEL_T07_MATRIX_REPORTER_ID="$matrix_reporter_id" \
      SENTINEL_T07_MATRIX_ENVIRONMENT_ID="$environment_id" \
      SENTINEL_T07_MATRIX_APP_ID="$app_id" \
      SENTINEL_T07_MATRIX_INSTANCE_ID="$matrix_instance_id" \
      SENTINEL_T07_MATRIX_AGENT_STATE="$agent_state" \
      SENTINEL_T07_MATRIX_INCIDENT_STATE="$incident_state" \
      SENTINEL_T07_MATRIX_REVOKED="$revoked" \
      SENTINEL_E2E_TEST_FILE=live-rules.e2e.test.mjs \
      SENTINEL_E2E_TEST_NAME='LIVE PROTOCOL-01: per-worker unknown' \
      SENTINEL_E2E_LIVE_RULES=1 SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
      "$node_bin" scripts/test/run-edge-e2e.mjs
  )
}

environment_id="sentinel-t07-protocol-$run_suffix"
app_id="sentinel-protocol-demo"
consumer_reporter_id="t07-protocol-$run_suffix"
consumer_principal="t07-protocol-principal-$run_suffix"
consumer_instance_id="t07-protocol-worker-$run_suffix"
consumer_process_id="t07-protocol-process-$run_suffix"
readarray -t consumer_identity < <(
  enroll_reporter consumer "$consumer_reporter_id" "$consumer_principal" \
    "$environment_id" "$app_id" "$consumer_instance_id" "$consumer_process_id"
)
consumer_cert="${consumer_identity[0]}"
consumer_key="${consumer_identity[1]}"
process_epoch="$(python3 -c 'import uuid; print(uuid.uuid4())')"
driver_json="$(PYTHONPATH="$repo_root/components/http/src:$repo_root/components/sentinel/sentinel/src:$repo_root/components/sentinel/sentinel-reporter-v2/src:$repo_root/components/sentinel/sentinel-reporter-incidents/src:$repo_root/foundation/contracts/src" \
  "$uv_bin" run --project "$console_root" --extra test python "$console_root/tools/e2e/consumer_runtime_driver.py" \
    --collector-url "https://127.0.0.1:$metrics_port" \
    --server-ca "$state_dir/reporter-ca.pem" --client-certificate "$consumer_cert" \
    --client-private-key "$consumer_key" --credential-generation "e2e-$run_suffix" \
    --reporter-id "$consumer_reporter_id" --process-epoch "$process_epoch")"
incident_event_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["incident_event_id"])' <<<"$driver_json")"
printf 'Synthetic consumer facts accepted: reporter=%s incident=%s.\n' \
  "$consumer_reporter_id" "$incident_event_id"
(
  cd "$dashboard_root"
  SENTINEL_T07_CONSUMER_REPORTER_ID="$consumer_reporter_id" \
    SENTINEL_T07_CONSUMER_ENVIRONMENT_ID="$environment_id" \
    SENTINEL_T07_CONSUMER_APP_ID="$app_id" \
    SENTINEL_T07_CONSUMER_INSTANCE_ID="$consumer_instance_id" \
    SENTINEL_T07_CONSUMER_INCIDENT_EVENT_ID="$incident_event_id" \
    SENTINEL_E2E_TEST_FILE=live-rules.e2e.test.mjs \
    SENTINEL_E2E_TEST_NAME='LIVE PROTOCOL-01 / INCIDENT-01' \
    SENTINEL_E2E_LIVE_RULES=1 SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0 \
    "$node_bin" scripts/test/run-edge-e2e.mjs
)

matrix_reporter_id="t07-protocol-matrix-$run_suffix"
matrix_principal="t07-protocol-matrix-principal-$run_suffix"
matrix_instance_id="t07-protocol-matrix-worker-$run_suffix"
matrix_process_id="t07-protocol-matrix-process-$run_suffix"
readarray -t matrix_identity < <(
  enroll_reporter protocol-matrix "$matrix_reporter_id" "$matrix_principal" \
    "$environment_id" "$app_id" "$matrix_instance_id" "$matrix_process_id"
)
matrix_cert="${matrix_identity[0]}"
matrix_key="${matrix_identity[1]}"

run_matrix_browser unknown unknown
unsupported_agent="$(curl --fail --silent --show-error --cacert "$state_dir/reporter-ca.pem" \
  --cert "$matrix_cert" --key "$matrix_key" -H 'content-type: application/json' \
  --data '{"protocol_version":"atlas-richie.reporting/v999"}' \
  "https://127.0.0.1:$metrics_port/api/reporting/v1/protocol-negotiations/agent")"
[[ "$(python3 -c 'import json,sys; print(json.load(sys.stdin)["compatibility"])' <<<"$unsupported_agent")" == incompatible ]]
run_matrix_browser incompatible unknown
supported_incident="$(curl --fail --silent --show-error --cacert "$state_dir/reporter-ca.pem" \
  --cert "$matrix_cert" --key "$matrix_key" -H 'content-type: application/json' \
  --data '{"protocol_version":"atlas-richie.incident-events/v1"}' \
  "https://127.0.0.1:$metrics_port/api/reporting/v1/protocol-negotiations/incident-events")"
[[ "$(python3 -c 'import json,sys; print(json.load(sys.stdin)["compatibility"])' <<<"$supported_incident")" == compatible ]]
run_matrix_browser incompatible compatible
"$uv_bin" run --project "$console_root" --extra mysql --extra server --extra collector --extra nacos-grpc --extra test sentinel-console metrics-reporter revoke --principal "$matrix_principal"
run_matrix_browser unknown unknown 1

printf 'Protocol matrix durable setup complete: primary=%s; revoked=%s.\n' \
  "$consumer_reporter_id" "$matrix_reporter_id"
