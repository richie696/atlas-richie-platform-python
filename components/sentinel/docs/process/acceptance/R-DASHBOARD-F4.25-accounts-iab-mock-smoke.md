# F4.25 Account Management — IAB Mock Smoke

Status: frontend Mock acceptance passed; Python Console/live E2E remains outside this record.

## Scope and setup

- Ran the dashboard locally in explicit `?mode=mock` and used only the Codex
  in-app browser (IAB). No Chrome, Edge, CDP, Python Console, database, or
  external configuration service was used.
- Signed in with the documented synthetic demo account and opened the account
  maintenance tab under System Management.

## Observed behavior

| Check | Result |
|---|---|
| Account list | The page rendered the canonical `admin` and `viewer` demo rows. |
| Search | Searching for `view` and submitting reduced the result to `viewer` and the count to one. |
| Create dialog | The dialog exposed username, password, and role; it did not expose display-name or confirmation-password fields. |
| Successful create | A synthetic test account was accepted by the Mock HTTP handlers and appeared in the refreshed directory. |
| Duplicate create | Reusing `viewer` produced the translated duplicate-name error and kept the dialog/input values available for correction; the accessibility tree redacted password values. |
| Additional create commands | In a fresh IAB Mock session, 19 synthetic accounts were created through the visible dialog. Each UI submission was followed by waiting for the corresponding refreshed total; all were confirmed, with no command replay. The earlier immediate observation of an unresolved result was not reproduced with this completion-aware interaction. |
| Rendered pagination | With 21 total rows and the application page size of 20, page 1 rendered 20 rows and enabled only “next”; page 2 rendered the remaining `viewer` row and enabled only “previous”; returning to page 1 restored 20 rows and the expected button states. |
| Mock state cleanup | After closing the IAB tab and stopping the local server, a fresh IAB session returned to the canonical two-account seed; the synthetic row was not retained. |

## Automated checks

- `npm run test:logic`: **247/247 passed** in the current turn. Includes account
  create validation, pending single-flight/double-submit protection,
  unknown-result non-replay, authorization, and list query bounds.
- `npm run test:http`: **94/94 passed** in the current turn with the isolated
  listener restricted to `127.0.0.1`. A prior sandbox-only attempt was **93/94**
  because loopback bind returned `EPERM`; the local-only reruns passed.

The legacy `npm run test:e2e` command was not run because its configured runner
starts external CDP browser automation, contrary to the user's explicit browser
constraint. Rendered behavior was instead exercised through the Codex IAB and
verified from the visible DOM/accessibility tree. The initial transient
“outcome unconfirmed” observation was not reproducible after awaiting the
visible result; safety behavior was left unchanged.

## Remaining boundary

This passes the frontend account-management slice against the explicit in-browser
HTTP Mock. It does not prove Python Console integration, relational persistence,
production password hashing, database uniqueness/concurrency, or React-to-Python
E2E; those remain B0/backend acceptance work.
