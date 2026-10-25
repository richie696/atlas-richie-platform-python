#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KUBECONFIG_PATH="${KUBECONFIG:-${HOME}/.kube/10.20.1.13.yaml}"
NAMESPACE="sentinel-e2e-infra-20261018"
REGISTRY_HOST="${SENTINEL_E2E_REGISTRY_HOST:-}"

if [[ -z "$REGISTRY_HOST" ]]; then
  echo "SENTINEL_E2E_REGISTRY_HOST is required; pass the current stable host:port explicitly" >&2
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

kubectl --kubeconfig "$KUBECONFIG_PATH" create namespace "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f -

if ! kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" \
  get secret middleware-credentials >/dev/null 2>&1; then
  POSTGRES_PASSWORD="$(openssl rand -hex 24)"
  MYSQL_PASSWORD="$(openssl rand -hex 24)"
  MYSQL_ROOT_PASSWORD="$(openssl rand -hex 24)"
  NACOS_AUTH_TOKEN="$(openssl rand -base64 48 | tr -d '\n')"

  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" create secret generic \
    middleware-credentials \
    --from-literal="postgres-password=${POSTGRES_PASSWORD}" \
    --from-literal="mysql-password=${MYSQL_PASSWORD}" \
    --from-literal="mysql-root-password=${MYSQL_ROOT_PASSWORD}" \
    --from-literal="nacos-auth-token=${NACOS_AUTH_TOKEN}" >/dev/null

  unset POSTGRES_PASSWORD MYSQL_PASSWORD MYSQL_ROOT_PASSWORD NACOS_AUTH_TOKEN
fi

if ! kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" \
  get secret nacos-bootstrap-credentials >/dev/null 2>&1; then
  NACOS_BOOTSTRAP_PASSWORD="$(openssl rand -hex 24)"
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" create secret generic \
    nacos-bootstrap-credentials \
    --from-literal=username=nacos \
    --from-literal="password=${NACOS_BOOTSTRAP_PASSWORD}" >/dev/null
  unset NACOS_BOOTSTRAP_PASSWORD
fi

middleware_resources=(
  deployment/postgres
  deployment/mysql
  deployment/nacos
  deployment/consul
  deployment/prometheus
  daemonset/node-exporter
)
existing_resources=0
for resource in "${middleware_resources[@]}"; do
  if kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" \
    get "$resource" >/dev/null 2>&1; then
    existing_resources=$((existing_resources + 1))
  fi
done

if [[ "$existing_resources" == 0 ]]; then
  sed "s|__SENTINEL_REGISTRY_HOST__|$REGISTRY_HOST|g" "$SCRIPT_DIR/e2e-middleware.yaml" \
    | kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f -
elif [[ "$existing_resources" == "${#middleware_resources[@]}" ]]; then
  echo "Existing complete E2E middleware stack detected; preserving its Pods and emptyDir data."
else
  echo "Partial E2E middleware stack detected; refusing to reconcile resources automatically." >&2
  echo "Inspect namespace $NAMESPACE before applying or deleting any resources." >&2
  exit 3
fi

kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" rollout status deployment/postgres --timeout=10m
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" rollout status deployment/mysql --timeout=10m
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" rollout status deployment/nacos --timeout=10m
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" delete job nacos-bootstrap \
  --ignore-not-found --wait=true
sed "s|__SENTINEL_REGISTRY_HOST__|$REGISTRY_HOST|g" "$SCRIPT_DIR/nacos-bootstrap-job.yaml" \
  | kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f -
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" wait \
  --for=condition=complete job/nacos-bootstrap --timeout=5m
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" rollout status deployment/consul --timeout=5m
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" rollout status deployment/prometheus --timeout=5m
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" rollout status daemonset/node-exporter --timeout=5m
