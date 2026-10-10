# F4.27 Role Target and Access — IAB Mock Smoke

Status: complete for the React + Mock frontend slice; Python Console acceptance remains separate.

## Evidence

- Used only the Codex in-app browser against the local Mock profile at
  `127.0.0.1:4180`; no Chrome, Edge, CDP, database, Python Console, or external
  configuration service was used.
- Opened `#/roles?account=does-not-exist`. The selector stayed at “选择…” and
  the page stated “未找到账号；不会自动选择其他账号。” No other account or
  role editor was substituted. The rendered screenshot was inspected in-session.
- Opened a fresh `#/roles?account=account-view` route. It selected `viewer`,
  rendered the account as active, and exposed exactly two role options
  (`管理员`, `查看者`) with `查看者` selected. Starting from `#/roles` and
  explicitly selecting `viewer` also reached the same role editor.
- The initial multi-tab IAB run showed a transient read failure after switching
  from a missing account to `viewer`. I repeated the same transition alone in a
  fresh IAB tab on a dedicated local origin/Mock worker; selection and detail
  read both succeeded. Clean direct-link and selector flows now pass; the first
  failure was not reproducible in an isolated page and is not treated as an
  application defect.
- The preceding F4.26 IAB evidence (§15.73) verified the viewer lacks System
  navigation and direct account-maintenance access. Current account command
  wire has only create/status/role variants; own-password uses a separate
  session-bound workflow and HTTP endpoint. There is no administrator password
  reset UI/API variant in the current scope.
- Full `npm run check`: **passed**, including typecheck, format, lint, 6 Hooks
  lint tests, 13 architecture tests, logic **247/247**, HTTP **94/94**, contract,
  browser/visual/i18n/verification tooling, i18n validation, production and demo
  builds, build-profile **2/2**, and Sites **4/4**. The full gate required
  permission for its controlled test server to bind only to `127.0.0.1`; it did
  not contact external services. Vite still reports the known ~1.19 MB initial
  JS chunk; bundle reduction remains F5.6 work.

## Remaining

- Python Console authorization and persistent account/role behavior remain
  unverified; Mock and source inspection do not prove server authorization.
- The ~1.19 MB initial JS bundle warning remains F5.6 work.
