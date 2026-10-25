#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KUBECONFIG_PATH="${KUBECONFIG:-${HOME}/.kube/10.20.1.13.yaml}"
REGISTRY_HOST="${SENTINEL_E2E_REGISTRY_HOST:-}"

if [[ -z "$REGISTRY_HOST" ]]; then
  echo "SENTINEL_E2E_REGISTRY_HOST is required; use a node-reachable stable host:port" >&2
  exit 2
fi
if [[ ! "$REGISTRY_HOST" =~ ^[[:alnum:].-]+:[0-9]{1,5}$ ]]; then
  echo "SENTINEL_E2E_REGISTRY_HOST must be a host:port without a scheme or path" >&2
  exit 2
fi
registry_port="${REGISTRY_HOST##*:}"
if ((10#$registry_port < 1 || 10#$registry_port > 65535)); then
  echo "SENTINEL_E2E_REGISTRY_HOST port must be in 1..65535" >&2
  exit 2
fi
if [[ ! -r "$KUBECONFIG_PATH" ]]; then
  echo "Kubeconfig is not readable: $KUBECONFIG_PATH" >&2
  exit 2
fi

render_apply() {
  local manifest="$1" rendered
  rendered="$(mktemp)"
  trap 'rm -f "$rendered"' RETURN
  sed "s|__SENTINEL_REGISTRY_HOST__|$REGISTRY_HOST|g" "$manifest" > "$rendered"
  if grep -Fq '__SENTINEL_REGISTRY_HOST__' "$rendered"; then
    echo "Unresolved registry placeholder in $manifest" >&2
    return 1
  fi
  kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f "$rendered"
  rm -f "$rendered"
  trap - RETURN
}

render_apply "$SCRIPT_DIR/t003-console-edge-acceptance.yaml"
render_apply "$SCRIPT_DIR/t003-console-shared-state-acceptance.yaml"
render_apply "$SCRIPT_DIR/t003-metrics-collector-acceptance.yaml"

kubectl --kubeconfig "$KUBECONFIG_PATH" -n sentinel-t003-console-20261019 \
  rollout status deployment/postgres --timeout=5m
kubectl --kubeconfig "$KUBECONFIG_PATH" -n sentinel-t003-console-20261019 \
  rollout status deployment/console --timeout=8m
kubectl --kubeconfig "$KUBECONFIG_PATH" -n sentinel-t003-console-20261019 \
  rollout status deployment/metrics-collector --timeout=5m
kubectl --kubeconfig "$KUBECONFIG_PATH" -n envoy-gateway-system \
  wait --for=condition=Programmed=true gateway/sentinel-t003-console --timeout=5m
