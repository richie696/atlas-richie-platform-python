# B0.3 Rule Publication Target Management — Acceptance Matrix

Status: target read/configure path implemented; provider publication acceptance remains open. This is the admin command path for assigning one exact, credential-free configuration-center address to a rule binding.

## Contract and ownership

- Reuse `POST /api/v1/rulesets/{bindingId}/commands` and its original-operation read path; do not create a second write gateway.
- Read the configured target through session-protected `GET /api/v1/rulesets/{bindingId}/publication-target`; an unconfigured binding returns `{bindingId, target: null}`.
- The command contains a finite provider target (`nacos`: namespace/group/dataId; `consul`: key), exact registered `sourceId` and `expectedSourceRevision`, plus nullable `expectedTargetRevision` for create/CAS.
- The Console SQL authority validates that the binding owns the source, that source provider/revision still match, and that Nacos namespace / Consul datacenter do not override registered-source location.
- Target write, idempotency receipt, and audit fact commit in one transaction. Credentials and rule bodies are not included in this command or its audit.
- The server-side publication worker remains responsible for provider access and publication; configuring a target does not publish rules.

## Risk-to-test matrix

| ID | Risk | Minimum check |
|---|---|---|
| TGT-01 | Valid Nacos target create/update | Store test verifies versioned target and exact stored provider fields |
| TGT-02 | Valid Consul target create/update | Store test verifies key and source-owned datacenter |
| TGT-03 | Stale target revision or source revision | Command is rejected as conflict; old mapping remains unchanged |
| TGT-04 | Wrong binding/source/provider or wrong location | Reject without changing the target row |
| TGT-05 | Idempotent retry | Same actor/session/requestKey and payload returns original target receipt; changed payload conflicts |
| TGT-06 | Audit and transaction | Successful command has one `rules.configure_target` audit fact; rejected command records rejection; rollback leaves no target or success receipt |
| TGT-07 | Authorization | Anonymous/view/invalid CSRF are rejected before persistence |
| TGT-08 | Serialization/privacy | Receipt contains target mapping and revisions only; no registered credential envelope or rule content |

## Verification evidence

- Python ASGI + focused SQLite command tests: **4 passed** across target reads, anonymous rejection, target persistence, stale-source conflict, and no-credential projection.
- React typecheck and lint passed; focused Mock HTTP test `RULE-MOCK: explicit demo handlers support the same directory, snapshot, and durable draft HTTP path` passed **1/1**, covering target read, configure, read-back, and stale target CAS.
- Generated Console OpenAPI now contains **43 paths**, including target read and the expanded command union.

## Verification boundary

Focused SQLite-backed SQL/API tests prove local transaction and contract behavior only. PostgreSQL/MySQL migration and isolation behavior, rendered React workflow, live Nacos/Consul access, and final browser E2E remain separate gates.
