# B0.2 setup-window local process lock test

Status: **focused local-filesystem implementation evidence; deployment acceptance remains open**.

## Test case

| ID | Risk | Preconditions | Action | Required assertion |
| --- | --- | --- | --- | --- |
| BOOT-LOCK-PROC-01 | Two Console worker processes both accept a write using one stale setup-window revision | One explicit open setup-window file and revision on a disposable local POSIX test directory; two independent spawned Python processes | Release both workers through a process-shared gate; each attempts a different `is_open` value against the same expected revision | Exactly one returns a new revision and exactly one receives `SetupWindowRevisionConflict`; persisted snapshot exactly matches the winner's state and revision |

The test exercises OS-process isolation, the sidecar `flock`, and file CAS. It does not claim behavior for NFS, Kubernetes multi-replica volumes, containers on separate hosts, or a production mount. Those must be verified against the deployment's actual storage and worker topology.

## Verification

```sh
PYTHONPATH=components/sentinel/sentinel-console/src \
  .venv/bin/pytest -q \
  components/sentinel/sentinel-console/tests/test_setup_window_file_store.py
```

Result: **13 passed**. No external database, Nacos, Consul, browser, or E2E was used.
