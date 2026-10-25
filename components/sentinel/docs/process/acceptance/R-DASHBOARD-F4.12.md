# F4.12 实时监控异常状态、发布标注与轮询释放验收

日期：2026-10-08  
状态：前端实现与定向验证完成；真实服务联调和最终 E2E 待后续阶段  
范围：本地 Dashboard demo、MSW 合成数据、Codex 内置浏览器；非 Python Console/生产采集验收

## 已实现与本轮修正

- 指标查询模型保留可区分的未接入、缺测、partial、stale、error/denied 等状态；已有 query owner 对同 key 刷新保留可信旧值、对身份变化/撤权/迟到响应做隔离，轮询不自动重试写操作。
- `RealtimeObservationContainer` 为 monitor 和实例资源注册 `useOwnedDisposal`。路由真正卸载时最终调用 `dispose()`，解除访问/查询订阅并完成 PollingStore；React StrictMode effect replay 仍先取消、允许 owner 复用。
- Demo app-one 的观测 bundle 有一个位于窗口中间的合成规则发布注释，其他应用不注入注释。
- 修复 `metricsMockHandlers` 的 wire projection：原来 fixture 已创建 `annotations`，但 HTTP handler 丢弃了该字段，导致 UI 看不到发布注释；现在通过 HTTP mock 正常编码时间并交给正式 mapper/图表。

## 验收证据

- `npm run check`（允许仅绑定 `127.0.0.1` 的隔离 HTTP 测试监听器）退出码 0：typecheck、format、lint、Hooks lint **6/6**、architecture **13/13**、logic **240/240**、HTTP **85/85**、Console OpenAPI **42 paths**、browser tools **7/7**、visual tools **7/7**、i18n tools **9/9**、verification tools **5/5**、i18n parity、production/demo build、build profiles **2/2**、Sites **4/4**。
- HTTP 测试 `METRICS-MOCK` 断言 app-one 的 publication annotation 经 HTTP mock 与 production mapper 保留，app-two 不产生该标注。
- Logic 测试 `OBS-ANNOTATION` 验证 publication 标注投影到实际时间位置；`MONITOR-POLL`、`MONITOR-STALE`、`MONITOR-CLEANUP` 覆盖单轮询 owner、暂停/取消、失败后保留原 freshness、恢复替换以及 dispose 后不可重新启动。
- Codex 内置浏览器切到 app-one，QPS、p95、拦截率、CPU、内存图表均显示“规则发布”图表标注；此验证使用 MSW 合成数据。
- 内置浏览器导航离开实时监控后等待超过一个 5 秒轮询周期；控制台中最后一条 `/api/v1/metrics/query` 时间戳保持不变，未观察到后台轮询继续。
- HTTP 用例 `METRICS-RECOVERY` 覆盖两个 opt-in mock application：`mock-recovering-metrics` 成功→503→成功，`mock-retry-metrics` 503→成功；恢复响应保留目标 application id 和有效指标，不影响普通应用。
- HTTP 用例 `METRICS-MONITOR-RECOVERY` 将真实 feature monitor、Console HTTP transport、MSW handler 和严格 mapper 串联：加载成功→503 时保留原快照为 stale→后续 200 后替换快照并更新 window/asOf，focused test **1/1 passed**；纳入当前 HTTP 套件后共 **85/85 passed**。
- Codex 内置浏览器中的 `mock-retry-metrics` 首次请求返回 503；在 5 秒自动轮询前点击可重试按钮，随后 HTTP 200 且页面错误消失、指标显示，读取时间更新。
- 首次观察的 `mock-recovering-metrics` 标签在 `200 → 503 → 200 → 200 → 200` 后仍显示 stale，但该标签日志在 20:01:35 停止，之后没有继续请求记录；不能据此认定后续 200 被页面拒绝，也不能定位为 React owner/响应校验缺陷。
- 新开的内置浏览器标签重新跑完同一隔离场景：MSW 日志 `200 → 503 → 200 → 200 → 200 → 200`；成功响应后页面显示正常 partial 状态、读取时间推进至 20:14:56，stale 提示消失。与 Node feature monitor+HTTP 合同回归相符，**一次性故障后的自动恢复路径已通过 IAB 手工验证**。旧标签不一致现象仍未解释，可能受标签后台挂起/观察窗口影响，但这只是推测，不作为已证实根因。
- 当前续验确认：`mock-recovering-metrics` 不在应用目录，自动恢复后页面虽回到 partial，但应用选择器为空、指标为 `no_samples`。因此 IAB 观察只证明故障探针的 stale → recovered 状态变化，不证明一个可选真实目录应用上的有数据 UI 自动恢复；该差异不改变 mock HTTP/monitor 对 DTO 的测试结果。
- 其他普通 app 的对照中，两个标签都曾显示 stale；其观察缺少持续请求日志，不能据此证明 monitor 挂起或归因到 owner 生命周期。控制台 error/warn 为空。
- 本轮未启动 Chrome/Edge，也未运行会自动启动 Chrome/CDP 的 `test:e2e`。

## 未收口 / 证据边界

- 断网、迟到、撤权等行为目前由 logic/HTTP 合同验证；IAB 没有真实 Python Console/采集服务可供故障注入，故不把本地 MSW 表现当作真实网络/生产断网验收。
- 轮询退出的 UI 观察覆盖切离路由；没有对真实宿主执行长时间资源/内存剖析。
- 普通实时 monitor 长时间运行或暂停/恢复时曾出现 stale；显式 mock 的“首次失败后手动重试”路径在 IAB 可恢复，但“已有可信数据→短暂刷新失败→自动轮询恢复”的页面路径出现了可重复的不一致现象，根因未证实。
- 全量 CDP E2E 未执行（会启动 Chrome）；F4.12 保持未勾选，待剩余状态路径与允许的浏览器验收边界完成。

## 2026-10-08 补充：撤权后的迟到响应隔离

- **缺口：**既有 `MONITOR-OWNER` 覆盖更换查询时取消旧读，以及撤权后立即清空已加载数据；它没有证明忽略 `AbortSignal` 的远端读在撤权后才返回时不会重新填充数据。
- **回归：**新增 `MONITOR-LATE-REVOKED`：启动一个未完成读取，撤销 `metrics:view` 后断言请求 signal aborted、selection/data 清空且状态为 denied；随后模拟 Port 无视 abort 返回旧指标，denied 状态仍不含数据、没有重复请求；改为新 session owner 后必须重新发起请求并读取新快照。
- **验证：**`npm run test:logic:focused -- 'MONITOR-LATE-REVOKED'` **1/1 passed**；完整 monitor 相关 focused 集 `MONITOR-(QUERY|FILTERS|POLL|STALE|OWNER|LATE-REVOKED|TIMEOUT|CLEANUP)` **8/8 passed**；`npm run check:fast` exit 0。未运行全量 milestone 或页面 E2E。
- **边界：**这是 feature owner 对撤权/迟到竞态的逻辑证据，不是浏览器权限撤销或 Python Console 授权验收。后台/长时间资源剖析、真实网络中断和完整 milestone 页面旅程仍未完成，F4.12 继续未勾。

## 2026-10-09 补充：重复页面 owner 的轮询与订阅释放压力回归

- **风险/用例：**新增 `MONITOR-LIFECYCLE-STRESS`，在单测中连续创建 64 个独立 monitor owner；每个启动并完成首读后立即 dispose，随后等待超过一个 100 ms 轮询间隔。
- **断言：**每次 dispose 后 access subscription 数回到 0、快照清空且为 idle；所有 owner 销毁后调用数仍为 64，证明轮询没有在 dispose 后继续触发，也没有累积访问订阅。
- **验证：**`npm run test:logic:focused -- 'MONITOR-LIFECYCLE-STRESS'` **1/1 passed**；`npm run check:fast` exit 0（typecheck、Prettier、ESLint、Console OpenAPI 42 paths）。本轮没有运行全量 logic/HTTP、milestone gate 或浏览器 E2E。
- **边界：**这是快速的确定性生命周期压力回归，不等于真实浏览器多小时 soak、宿主内存/CPU profiling，也不覆盖后台标签节流或真实 Python/Collector 网络故障。F4.12 仍未勾选。

## 2026-10-09 补充：网络错误语义、可信数据保留与安全恢复提示

- **实现：**实时观测页将首次网络失败与 stale 网络刷新失败分开给出中/英/日文文案；有可信同范围快照时继续保留原数据并明确不是最新状态，说明自动轮询恢复与手动重试入口。raw transport message 不展示。网络故障探针改为目录中有效的 `app-three`，并与 HTTP 503 计数分离。
- **定向验证：**`npm run test:logic:focused -- 'REALTIME-READ-COPY'` **3/3 passed**；`npm run test:http:focused -- 'METRICS-NETWORK-RECOVERY'` **1/1 passed**，顺序覆盖 HTTP 503、有效样本、网络无响应、恢复样本，且无 transport 隐式重试；`node --test tests/architecture/workflow-ownership.test.mjs` **7/7 passed**；`npm run check:fast` exit **0**；`npm run i18n:check` 通过，三语键数量均为 1147；`git diff --check` 通过。
- **Codex IAB 观察：**本机 demo 的有效 `app-three` 实时页正常加载并持续展示 QPS/RT/资源指标及 TPS 未接入状态；在这次页面观察窗口没有看到网络故障横幅，因而页面级断网/stale/自动恢复尚未验收。Node HTTP/文案映射证明不能替代可见页面故障路径。
- **仍未完成：**尚未实现/证明一次性网络故障在稳定首帧之后必然落到页面状态的确定性注入方式；未做真实 Console/Reporter/Collector 故障注入、长时间宿主 profiling、完整 milestone IAB 页面旅程。F4.12 继续未勾。

## 2026-10-09 补充：断网注入等待有效读后触发

- **根因修正：**旧网络故障场景按绝对请求序号触发；React StrictMode 的挂载/清理重放或失败前的首轮读取可能消费故障序号，页面进入稳定状态后就没有可见断网事件。场景改为先观察目标应用成功返回两个有效 HTTP 指标响应，再注入一次无 HTTP 响应；其余请求读取可成功恢复。应用目录选择与原始错误脱敏保持不变。
- **验证：**`npm run test:http:focused -- 'METRICS-NETWORK-RECOVERY'` **1/1 passed**，明确断言 `503 → 成功 → 成功 → NETWORK（不自动重试）→ 成功恢复`；`npm run check:fast` exit **0**；`npm run i18n:check` 通过（三语各 1147 keys）；`git diff --check` 通过。
- **边界：**这是受控 MSW/HTTP adapter 的确定性状态序列，不是可见页面恢复证据。本轮 Codex IAB 无可访问标签，CUA 报告本机已锁定；没有重启/操纵浏览器，也没有运行完整 E2E。故障 banner、旧数据 stale 呈现与自动轮询后的页面恢复仍需后续 IAB 页面专项验证。真实 Console/Reporter/Collector 断网及长时宿主资源 profiling 也未覆盖，F4.12 继续未勾选。

## 历史一次性读故障探针记录（由下方续验修正）

| ID                    | 层级                 | 前置条件                                                                | 动作                                  | 关键断言                                                                                                                                     |
| --------------------- | -------------------- | ----------------------------------------------------------------------- | ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| METRICS-RECOVERY-HTTP | HTTP 合同            | 显式 `test-env` mock 保留目标 application id；scenario counter 已 reset | 对同一窗口连续读取 3 次               | ✅ 第 1 次成功、第 2 次返回 503 `service_unavailable`、第 3 次成功；恢复 bundle 与请求窗口一致，指标按契约为 `no_samples`，普通 app 不受影响 |
| METRICS-RECOVERY-IAB  | Codex 内置浏览器手工 | 仅 demo/mock，打开不在目录中的 `mock-recovering-metrics` 深链           | 初始加载后观察注入失败及后续自动 poll | ⚠️ stale 后恢复 partial、读取时间推进；选择器为空且指标无样本，只证明状态恢复，不作为有效应用 UI 的完整 E2E 证据                             |
| METRICS-RETRY-IAB     | Codex 内置浏览器手工 | 仅 demo/mock，打开 `mock-retry-metrics` 深链                            | 首次读取失败后点击“重试读取”          | ✅ 可重试 error 清晰显示；点击后同一路由展示成功指标且更新时间；不访问真实 Console                                                           |

以上表格记录当时的探针；有效应用绑定和可见页面自动恢复结论以 2026-10-08 续验为准。受控故障不改变 live query DTO、真实 API retry 策略或普通应用 fixture；node tests 显式 reset counter，浏览器整页 reload 重置页面内 scenario state。Mock/IAB 仍不替代真实 Console/Reporter 网络验收、后台标签恢复或长期稳定性证明。

## 2026-10-08 本地有效应用 stale → 自动恢复续验

- **发现与修正：**此前恢复/重试 ID 不在应用目录，无法从正常应用选择器验收；改为 `app-two` / `app-three` 并增加 HTTP 合同对目录成员的断言。第一次浏览器检查没有看到 stale：故障计数落在初次挂载窗口。React 开发 StrictMode 会重放 effect，且第一次请求可能被取消；原注入在第二次读取，可能在有稳定数据前被消费。将恢复故障放到第三次读取，并扩展合同测试覆盖“第二次读取成功、第三次 503、第四次恢复”，避免把 UI 挂载读取误作用户可见的轮询故障。
- **HTTP 合同：**`npm run test:http:focused -- 'METRICS-(MOCK|RECOVERY|MONITOR-RECOVERY)'` **3/3 passed**；`npm run test:logic:focused -- 'MONITOR-(POLL|STALE)'` **2/2 passed**。monitor 测试在故障前保存最新成功 bundle，断言 stale 期间同一对象/窗口被保留，后续成功才替换。
- **页面路径：**本机 Vite `127.0.0.1:5197`、Codex IAB、Mock viewer，仅打开 `#/realtime?env=test-env&app=app-two&range=15m`。加载后 QPS **84 req/s**、p95 **58 ms**、拦截率 **3%**、CPU **43%**、内存 **49%** 均有有效合成样本；首轮轮询后页面出现“刷新失败，以下是上次成功读取的数据，并非最新状态。”及“重试读取”；下一轮自动轮询后 stale 提示和重试按钮消失，读取时间继续前进，app-two 与有效样本保留。
- `npm run check` 当前映射 `check:fast` 并通过（typecheck、format、lint、Console OpenAPI 42 paths）。未跑 `check:milestone`、全量浏览器 E2E、Chrome/Edge/CDP；未访问 Python Console、数据库、Nacos/Consul 或 Collector。此项是 IAB 页面专项验收，不是全量 E2E，也不证明真实网络/后台标签或长时稳定性。
- **剩余：**F4.12 不勾选；真实故障注入、迟到响应、撤权、离页释放长时资源分析和完整 milestone E2E 仍开放。旧 IAB 跨会话 stale 反例的根因没有因此被解释。

## 2026-10-09 前端切片关闭与最终验收边界

- **定向验证：**重新运行 `npm run test:logic:focused -- 'MONITOR-'`，**9/9 passed**；`npm run test:http:focused -- 'METRICS-MONITOR'`，**1/1 passed**；`npm run check:fast` 通过（typecheck、Prettier、ESLint、Console OpenAPI 43 paths）。
- **覆盖：**单一轮询 owner、暂停/恢复、同范围 stale 数据保留、成功响应自动恢复、切换查询/撤权后的迟到结果隔离、读取超时、StrictMode 可重启、dispose 清理及 64-owner 订阅/定时器释放压力；HTTP 集成层验证 stale 后恢复替换同窗口快照。既有 IAB 记录验证了发布图表标注和离开页面后轮询停止，并曾在有效 app-two 上看到 stale→自动恢复页面结果。
- **范围调整：**本项关闭的是 React 前端功能与局部行为合同。Python Console/Reporter/Collector 真实故障、生产主机长时 profiling 属于 B0.4/B0.5 或最终运行验收，不再阻止前端源代码切片完成；完整跨页旅程仍按用户要求只在全部实现之后执行。此轮没有启动 Chrome、Edge、CDP 或浏览器 E2E。
- **限制：**本轮定向 suites 依赖 mock/测试 Port，不证明真实服务网络故障、后台标签节流、多实例或生产内存/CPU 特性；这些边界保持明确开放。
