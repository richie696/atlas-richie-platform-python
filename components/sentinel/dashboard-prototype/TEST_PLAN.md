# Dashboard prototype test plan

This is a browser-verified design prototype, not an integration acceptance test.

| ID    | Risk                                                         | Evidence                                                                                                                                                                      |
| ----- | ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| UI-01 | Six pages are merely navigation chrome                       | Visit each page and verify a distinct operational question, data context, and primary action.                                                                                 |
| UI-02 | The fleet overview falsely represents demo data as live      | Persistent demonstration badge; no network publish calls; status copy identifies simulated data.                                                                              |
| UI-03 | App/instance diagnosis loses scope                           | Change application and instance; container displays example charts, host/process explicitly display unavailable state instead of reusing container numbers.                   |
| UI-04 | Rule editing pretends to persist                             | Create a local draft, validate, compare the complete JSON array; publish action explicitly says no configuration-center write.                                                |
| UI-08 | Five rule families collapse into one threshold field         | Select FlowRule, DegradeRule, SystemRule, AuthorityRule and ParamFlowRule; verify each renders its own Sentinel-compatible fields and conditional fields.                     |
| UI-09 | Form values diverge from configuration-center content        | Change a field in a draft and verify its JSON array preview changes; SystemRule blank values remain `-1`, and ParamFlow `classType` has a compatibility note.                 |
| UI-10 | Protocol keys leak into form labels or locale corrupts rules | Switch `zh-CN` / `en-US` / `ja-JP`; verify formal labels and options change while the JSON array keeps `resource`, `count`, enum codes, resource names, and values unchanged. |
| UI-11 | Scheduled rule changes leave no deterministic daily baseline | Verify a scheduled complete snapshot shows start, end, `Asia/Shanghai`, and an explicit restore version; it must not describe a browser timer or an implicit rollback.        |
| UI-05 | Realtime and fault controls are decorative                   | Pause/resume the example playback cursor, change chart range/metric, filter faults by app/range/severity, select event and drill down.                                        |
| UI-06 | Permission model grows accidentally                          | System page shows only metrics:view and rules:write; no tenant or approval UI.                                                                                                |
| UI-07 | Screenshot fidelity and accessibility regress                | Compare overview and instance pages to selected references at 1440×1024; check 390px responsive, keyboard navigation, visible focus, and console errors.                      |

Build and browser checks are evidence only for the prototype. They do not prove Nacos/Consul writeback, real host metrics, Agent Reporting ingestion, or cross-language integration.
