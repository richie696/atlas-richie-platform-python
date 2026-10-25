# Single-node E2E middleware stack

This stack is for the isolated Sentinel acceptance namespace, not a production
deployment. It provides PostgreSQL, MySQL, Nacos 3, Consul, Prometheus, and
node-exporter in the user's Kubernetes cluster while the Console/demo process
under test can run as a single node.

All data volumes are `emptyDir`; middleware data is disposable and can be lost
if a Pod is recreated. The namespace is intentionally separate from
`sentinel-system` and the cluster's existing workloads. Services are
`ClusterIP` only. Do not add a NodePort/LoadBalancer or expose these test
services to the LAN.

## Apply

1. Run `apply-e2e-middleware.sh` with the dedicated acceptance kubeconfig. The
   script generates random namespace-local database, Nacos-signing, and
   first-administrator credentials; it never writes their values to the
   repository or prints them. The `nacos-bootstrap` Job calls the Nacos 3
   first-admin endpoint and, on later runs, verifies the same credential using
   the login endpoint. A fresh Nacos 3 instance does not promise a pre-created
   `nacos/nacos` account. The credential remains in the namespace Secret
   `nacos-bootstrap-credentials` for acceptance clients. On reruns, a complete
   existing middleware stack is preserved (including its `emptyDir` data); a
   partial stack causes the script to stop for explicit inspection rather than
   reconciling or restarting services automatically.
2. Wait for the PostgreSQL, MySQL, Nacos, Consul and Prometheus deployments,
   the Nacos bootstrap Job, and the node-exporter DaemonSet to become ready.

Images are pinned and mirrored to a local HTTP registry. The deployment script
requires `SENTINEL_E2E_REGISTRY_HOST=host:port`; it intentionally has no IP
default because developer-machine DHCP addresses drift. Select an address
reserved through DHCP/IPAM or a stable DNS name. Before applying workloads,
configure that exact endpoint in containerd on every node and verify its HTTP
`/v2/` endpoint is reachable from each node. KubeKit Phase 2 can write this
per-node trust when its optional local-registry host is supplied. For example:

```sh
SENTINEL_E2E_REGISTRY_HOST=registry.lab.example:55000 ./apply-e2e-middleware.sh
```

Do not copy the example hostname literally. The operator must provide the
actual reserved endpoint for the target network; an unreserved laptop DHCP
address is acceptable only for a short-lived local acceptance run.

Images are pinned and mirrored to the local HTTP registry:

- PostgreSQL `16.10`
- MySQL `8.4.11`
- Nacos `3.2.3` (standalone, auth enabled; first admin initialized by a Job)
- Consul `1.21.1` (single-node dev mode, acceptance only)
- Prometheus `3.5.0`
- node-exporter `1.9.1`

Prometheus discovers node-exporter Pods only in this namespace, labels the
node name as `host_id`, and labels samples with `environment=sentinel-e2e`.
The Prometheus service account has namespace-scoped Pod discovery only.
Node-exporter mounts host `/proc`, `/sys`, and `/` read-only, drops all Linux
capabilities, and does not use host networking or host ports.

## Local access

For host-run acceptance clients, use loopback-only `kubectl port-forward` on
unused local ports. Suggested ports are PostgreSQL `15433`, MySQL `13307`,
Nacos HTTP/gRPC `18849/19849`, Consul `18501`, and Prometheus `19091`.
Keep the forwards running while the local Console and language demos are under
test. Never use the cluster Pod IPs as stable endpoints.

## Cleanup

The middleware should remain running after acceptance for user review, as
requested. When explicitly asked to remove it, delete only namespace
`sentinel-e2e-infra-20261018`; that removes its workloads, Secret, and all
`emptyDir` data. The local registry images are retained separately.
