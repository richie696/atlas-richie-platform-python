# Dashboard F4.08 — Complete RuleSet editing

Status: **frontend slice verified with focused tests and Codex in-app browser**.

## Ownership and boundary

The rules feature edits one explicitly selected `RuleBinding` as a complete
`RuleSetCandidate`. The source snapshot and its profile/revision are read-only
facts; local edits do not write the configuration center. Draft save/delete,
validation, and diff use the existing Console HTTP Port and command owner.
Python persistence, configuration-center CAS/write-back, and runtime load are
outside this frontend acceptance.

## Risk-to-test matrix

| Risk | Evidence | Required assertion |
| --- | --- | --- |
| A rule form edits only a fragment and silently loses sibling rules | Logic + rendered UI | Candidate and JSON preview contain the entire binding snapshot; add/remove affect only the local candidate |
| A candidate is confused with its source binding or profile | HTTP contract + UI | Exact binding/profile are visible and retained; server validation is bound to the candidate checksum and profile |
| Refresh or opening another draft overwrites unsaved values | Logic tests | Source refresh does not mutate the edit buffer; replacement requires explicit discard; draft read mismatch fails closed |
| Saving a partial/invalid set reaches the Port | Logic + HTTP contract | Whole-set validation rejects invalid/duplicate/non-finite values before dispatch |
| Draft save appears to be configuration-center publication | Rendered UI | Save updates only stored draft identity/revision and clean state; publication remains a separate workflow |
| Navigation loses dirty content silently | Rendered UI | SPA navigation asks for confirmation; staying preserves location and content; discard affects only local unsaved values |
| Unknown command result is retried and duplicates a write | Logic + HTTP contract | Original input remains locked; only lookup of original request is allowed; no replay until confirmed |
| Permission revocation retains rule bodies or reports | Logic tests | First access-owner transition hides local data and invalidates protected reports |

## Implemented behavior

- Explicit binding and source/profile facts; no implicit first-binding selection.
- Full-set rule creation, field editing, local removal, complete JSON preview,
  validation, comparison, save/update draft, reopen, discard, and persisted
  draft deletion.
- Dirty-navigation confirmation integrated with the application navigation
  boundary and native before-unload guard.
- Report invalidation on edits, access revocation, and confirmed draft changes;
  the immutable-version workflow remains a separate F4.09 concern.

## Verification performed (2026-10-08)

- Logic: `node --test --test-name-pattern='RULE-(DRAFT|SET)' tests/logic/run.mjs` —
  **8/8 passed**.
- HTTP: `node --test --test-name-pattern='RULE-(BINDINGS|SNAPSHOT|CANDIDATE|COLLECTIONS|COMMAND|MOCK)' tests/http/run.mjs` —
  **6/6 passed**.
- `npm run typecheck`, `npm run format:check`, `npm run lint`,
  `npm run contract:check`, and `npm run i18n:check` — passed.
- Codex in-app browser only (no Chrome or Edge): selected `binding-app-one`;
  edited 2000→2100, added and locally removed a second row, observed complete
  array preview, saved and observed `draft-revision-2`, ran candidate
  compatibility validation and whole-set diff, tried SPA navigation while
  dirty and chose to stay (2200 remained), discarded local edits back to 2100,
  and deleted the mock draft created in this isolated demo origin.

## Evidence boundary

All visible command receipts and data in the browser run were supplied by the
local demo MSW handlers. This is not proof of a Python Console database
transaction, durable restart recovery, Nacos/Consul conditional write, live
runtime application, or cross-language conformance. The repository's
`test:e2e` command launches external Chrome/CDP and was intentionally not run
under the user's browser constraint. Focused IAB validation is not reported as
the full E2E suite.
