#!/usr/bin/env bash

set -euo pipefail

readonly expected_context="docker-desktop"
readonly current_context="$(kubectl config current-context)"
if [[ "$current_context" != "$expected_context" ]]; then
  printf 'Refusing Kubernetes acceptance: expected context %s, found %s\n' \
    "$expected_context" "$current_context" >&2
  exit 2
fi

readonly node_count="$(kubectl get nodes --no-headers | wc -l | tr -d ' ')"
if [[ "$node_count" != "1" ]]; then
  printf 'Refusing local acceptance: expected one disposable node, found %s\n' \
    "$node_count" >&2
  exit 2
fi

readonly storage_class="$(kubectl get storageclass hostpath -o name 2>/dev/null || true)"
if [[ "$storage_class" != "storageclass.storage.k8s.io/hostpath" ]]; then
  printf 'Refusing local acceptance: required hostpath StorageClass is absent\n' >&2
  exit 2
fi

readonly script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly package_root="$script_root"
readonly namespace="sentinel-b02-share-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:10])')"
created_namespace=0

cleanup() {
  local exit_status=$?
  if [[ "$created_namespace" == "1" ]]; then
    kubectl delete namespace "$namespace" --wait=true --timeout=120s >/dev/null || {
      printf 'Cleanup incomplete; inspect exact namespace: %s\n' "$namespace" >&2
      exit_status=1
    }
  fi
  exit "$exit_status"
}
trap cleanup EXIT

kubectl create namespace "$namespace" >/dev/null
created_namespace=1
kubectl create configmap shared-volume-acceptance \
  --namespace "$namespace" \
  --from-file=local_atomic_file_store.py="$package_root/src/atlas_richie/sentinel_console/infrastructure/persistence/local_atomic_file_store.py" \
  --from-file=worker.py="$package_root/tests/kubernetes_shared_volume_worker.py" \
  >/dev/null

kubectl apply --namespace "$namespace" -f - <<'YAML'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: shared-authority
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: hostpath
  resources:
    requests:
      storage: 16Mi
YAML
kubectl wait --namespace "$namespace" --for=jsonpath='{.status.phase}'=Bound \
  pvc/shared-authority --timeout=120s

kubectl apply --namespace "$namespace" -f - <<'YAML'
apiVersion: batch/v1
kind: Job
metadata:
  name: shared-lock-workers
spec:
  completions: 2
  parallelism: 2
  completionMode: Indexed
  backoffLimit: 0
  activeDeadlineSeconds: 180
  template:
    spec:
      restartPolicy: Never
      securityContext:
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
      containers:
        - name: worker
          image: python:3.13-slim
          imagePullPolicy: IfNotPresent
          command: ["python", "/opt/acceptance/worker.py", "worker"]
          volumeMounts:
            - name: shared
              mountPath: /shared
            - name: acceptance-code
              mountPath: /opt/acceptance
              readOnly: true
      volumes:
        - name: shared
          persistentVolumeClaim:
            claimName: shared-authority
        - name: acceptance-code
          configMap:
            name: shared-volume-acceptance
YAML

kubectl wait --namespace "$namespace" --for=condition=complete \
  job/shared-lock-workers --timeout=240s
kubectl logs --namespace "$namespace" job/shared-lock-workers --all-containers=true

kubectl apply --namespace "$namespace" -f - <<'YAML'
apiVersion: batch/v1
kind: Job
metadata:
  name: shared-lock-verifier
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 120
  template:
    spec:
      restartPolicy: Never
      securityContext:
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
      containers:
        - name: verifier
          image: python:3.13-slim
          imagePullPolicy: IfNotPresent
          command: ["python", "/opt/acceptance/worker.py", "verify"]
          volumeMounts:
            - name: shared
              mountPath: /shared
            - name: acceptance-code
              mountPath: /opt/acceptance
              readOnly: true
      volumes:
        - name: shared
          persistentVolumeClaim:
            claimName: shared-authority
        - name: acceptance-code
          configMap:
            name: shared-volume-acceptance
YAML

kubectl wait --namespace "$namespace" --for=condition=complete \
  job/shared-lock-verifier --timeout=180s
kubectl logs --namespace "$namespace" job/shared-lock-verifier --all-containers=true
printf 'Local Kubernetes shared-volume acceptance passed; namespace=%s\n' "$namespace"
