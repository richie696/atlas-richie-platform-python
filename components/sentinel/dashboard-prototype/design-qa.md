# Dashboard prototype design QA

Date: 2026-09-14

Visual references: selected 1440×1024 fleet overview and application/instance matrix. Compared both references and the local browser implementation at 1440×1024 in the same visual inspection pass. Also checked a 390×844 viewport.

## Findings and adjustments

- Kept the approved dark operational palette, top navigation, alert/health cards, shared release marker, dense application table, and selected-instance matrix + adjacent trends.
- Compressed the overview and application context rows so the overview application table and the instance matrix appear in the first desktop viewport. The persistent demonstration banner and six-page navigation intentionally consume more height than the reference images.
- Added a version-and-activation-plan strip for immutable full rule-set snapshots. The scheduled activity example visibly identifies its effective window, IANA time zone, and named daily restore version; it is expressly a local UI model, not a running scheduler.
- Added explicit application/range behavior, real 14:02 release marker, instance QPS/blocked dual axes, and readable low-QPS tick labels. Host/process scope displays an unavailable state instead of reusing container sample values.
- Expanded the Rules page into a two-column working surface: a searchable six-rule list and a wide, type-specific editor. The selected type now exposes the Sentinel-compatible fields for FlowRule, DegradeRule, SystemRule, AuthorityRule, or ParamFlowRule, including conditional fields and a JSON array preview.
- Added `zh-CN` / `en-US` / `ja-JP` language resources for the rule workspace and shared shell. Formal business labels replace protocol keys in forms; the JSON preview intentionally retains protocol keys. The other five pages have not yet completed their content migration, so this is not a full-console localization claim.
- Rules draft validation has no publish side effect. Real Nacos/Consul writeback, the SentinelRuleCodec, Agent Reporting, per-process integration, and metrics queries remain unimplemented in this prototype.

## Verification

| Check                                                                                              | Result                                             |
| -------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| Six navigation pages, each with distinct data and action                                           | passed in local in-app browser                     |
| Instance anomaly filter, scope change, and 15-minute chart window                                  | passed in local in-app browser                     |
| Rule app/type filtering; FlowRule edit + JSON preview; DegradeRule and SystemRule dedicated fields | passed in local in-app browser                     |
| English and Japanese rule labels/options; protocol JSON remains unchanged                          | passed in local in-app browser                     |
| Version activation plan exposes effective window, time zone, and explicit restore baseline         | passed in local in-app browser                     |
| Fault app/time filter, system permission and protocol tabs                                         | passed in local in-app browser                     |
| 1440×1024 reference comparison and 390×844 responsive view                                         | passed; differences above are intentional          |
| Browser console errors                                                                             | none observed                                      |
| `npm run build`, `npm run test:sites`                                                              | passed; build has non-blocking bundle-size warning |

Scope of this result: visual and interaction prototype only. Production data, permissions, Nacos/Consul writes, and live service E2E are not verified.

Known follow-up: production charts still need a keyboard-readable data-table alternative and real empty/error/permission states before accessibility acceptance.

final result: passed
