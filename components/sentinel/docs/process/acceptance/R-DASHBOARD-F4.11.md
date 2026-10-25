# F4.11 实时监控筛选与实例 scope 验收

日期：2026-10-08  
状态：前端本地 demo/UI 切片已验收；Python Console/真实采集链路未验收  
范围：本地 dashboard demo + Codex 内置浏览器；无真实 Console、采集器或配置中心

## 已实现

- 实时页通过 Applications feature 的公开 `InstancePort` 读取实例目录，不直接依赖其私有模块。
- 环境、应用和时间窗作为目录查询上下文；实例选择将确切的 `appId`、`instanceId` 与目录声明的 `supportedScopes` 投影到实时指标查询。
- 实例 scope 只允许目录显式声明的能力；无可用 scope 的实例不会触发指标请求。显式实例深链在目录确认前不请求指标；目录缺失或 scope 不支持时显示明确状态。
- 清除实例恢复 Fleet/Application 汇总；环境或应用改变会清除旧实例，不把上一实例的数据带入新查询。
- 增加中、英、日文的实例、全部实例、采集范围、scope 不支持与目录读取状态文案；筛选区调整为四列自适应布局。
- 实例目录资源遵循 `useOwnedDisposal`，开发期 StrictMode 的 effect replay 只取消请求，不永久 dispose 可复用资源。

## 验收证据

- Codex 内置浏览器（本地 demo）中，app-one 显示 `instance-1` / `instance-2`；选中 `instance-1` 后 URL 包含 `instance=instance-1&scope=process`，范围栏显示“进程”，同窗指标继续展示。
- 清除实例回到 `scope=application`；在 app-two 可见并选中 `instance-3`；应用选择改变 URL 中的 app，仍停留在实时监控路由，没有跳转至应用页面。
- 新增 `MONITOR-FILTERS` 逻辑测试，覆盖精确 app/instance/supported scope、清除后恢复聚合 scope、空能力拒绝选择。
- 2026-10-08 `npm run check` 完整通过（命令退出码 0）：格式、类型、lint、hooks、架构、逻辑、HTTP（83/83）、Console contract、浏览器工具、视觉/i18n/验证工具、i18n 资源、production/demo build、build profile 与 Sites 检查。
- 本次续验：重新执行完整 `npm run check`，退出码 **0**；第一次在默认沙箱运行时，HTTP live-control loopback 用例因 `listen EPERM` 失败，获准后重跑通过。IAB 用当前目录内的有效应用复核 `app-one` → `app-two`：选择器、URL 与查询目标同步，页面继续停留在实时监控，QPS 分别为 42 / 84 req/s；这只证明有效应用间的一次筛选切换，不证明长时间轮询稳定。
- 本次也复核了恢复注入深链：`mock-recovering-metrics` 的自动请求恢复后从 stale 回到 partial，但该保留 ID 不在权威应用目录，选择器显示“选择…”且指标为 `no_samples`。因此该场景仅能作为 monitor 状态恢复探针，不能作为有效应用筛选或有数据 UI 的端到端证据；见 F4.12 的限制说明。
- 本轮追加 IAB 复测：重载后 app-two → app-three → app-one → app-two → app-one → app-three 六次切换均保留实时页控件与指标；app-two 选中 `instance-3` 后切换 app-one，URL 清除了 instance 并回到 `scope=application`，无失败态。
- 旧标签再次出现 stale 后，用新建的 Codex IAB 标签对照：不带绝对时间 URL 的实时路由加载与下一轮轮询正常；再加载旧标签完全相同的带 `from/to` URL，连续等待一个轮询周期仍正常；在新标签执行“总览 → 实时监控”后等待下一轮也正常。该对照排除了“绝对窗口 URL 必然导致失败”及“所有路由往返必然失败”，但没有解释旧标签为何进入 stale。
- 后续复测修正了“问题仅限旧标签”的判断：两个 IAB 标签先后都进入 `stale`，并保留相同的上次成功指标。语义化点击“重试读取”后状态没有变化；在一个标签执行暂停→恢复后，立即仍是 stale。对该标签整页 reload 后恢复为 `partial`（TPS 未接入导致），等待一个 5 秒轮询周期，读取时间推进且没有回到 stale。控制台 error/warn 为空。此组证据说明重载能够暂时恢复，但无法区分请求故障、mock worker/transport 状态、计时器节流或 owner 生命周期问题；不再将其归为旧标签独有。
- 未运行 `npm run test:e2e`：该项目自动化 E2E 会启动 Chrome；按用户明确要求，本任务不启动 Chrome/Edge。Codex 内置浏览器人工验收单独记录，不冒充该自动化套件。

## 2026-10-08 当前工作区 IAB 复核

- 使用当前工作区启动的本机 Vite demo，在 Codex 内置浏览器新开两个实时监控标签；两个页面都显示有效 `test-env` 汇总，HTTP QPS、p95、拦截率和 CPU/内存样本为 available/partial（TPS 明确 unavailable）。
- 单标签连续观察约 30 秒、双标签并行再观察约 30 秒，两个 URL 的 `读取时间` 均持续前进，页头保持“正在定时读取”，没有进入 stale/error。
- 在第二标签执行“总览 → 实时监控”，重新载入后继续观察约 30 秒，读取时间继续前进，未进入 stale。整个复核期间未修改业务数据或发起写命令。
- 工程化回归：`npm run test:logic` **253/253 passed**，包含 `MONITOR-POLL`、`MONITOR-STALE`、`MONITOR-OWNER`、`MONITOR-TIMEOUT`；`npm run i18n:check` 通过，三语各 **1,148** 键，静态校验 **1,016** 个键、仍有 **16** 个动态调用未静态解析；`git diff --check` 通过。此处测试不模拟浏览器后台休眠或真实网络故障。
- 本次不复现旧报告的双标签 stale 症状；短时未复现不等于解释了过去的故障，也没有覆盖更长时间、请求故障或后台节流条件。仍须把“持续轮询稳定性/可解释恢复”作为未收口风险，因此 F4.11 不勾选。
- 只使用 Codex IAB；没有调用 Chrome、Edge、CDP，也没有连接 Python Console、数据库或配置中心。

## 2026-10-08 可见 IAB 实时轮询复测

- 在一个新的、可见的 Codex IAB 标签直接打开本机 `#/realtime?env=test-env&app=all&range=1h`；页面显示 60/60 曲线样本，HTTP QPS/p95/拦截率/CPU/内存有有效 Mock 数据，TPS 明确 unavailable。
- 约 30 秒后复读无障碍状态，`读取时间` 从 `12:11:38 UTC` 推进到 `12:12:18 UTC`，页面仍为“正在定时读取”，没有出现 stale/error。
- 此结果只证明该次前台可见会话中的短时轮询成功；旧报告中仍有新 IAB 标签约 20 秒进入 stale 的反例。未做网络故障注入、后台标签节流/恢复、长时间资源观察或 Python Console 联调，因此根因仍未知，F4.11/F4.12 均不关闭。全程没有启动 Chrome、Edge 或 CDP。

## 2026-10-08 后续 IAB 复核：stale 再现

- 在 Codex IAB 新建标签直接打开 `#/realtime`，页面初始成功显示 `test-env` Mock 指标：HTTP QPS 189、p95 63 ms、拦截率 4%、CPU 49%、内存 50%；TPS 明确标为 unavailable。
- 约 20 秒后，页面进入 stale 并显示“刷新失败，以下是上次成功读取的数据，并非最新状态。”；图表的时间范围与读取时间停留在 `2026/10/8 06:45:14–07:45:14 UTC`。再观察约 12 秒，状态与时间仍未推进。
- 这次是在新 IAB 标签的直接实时页路径复现，不支持把症状归因于旧标签独有。通过 IAB 键盘 Tab 聚焦并按 Return 激活“重试读取”后，状态从 stale 变为“正在刷新”；约 14 秒后又回到 stale，读取时间仍未推进。该操作证明 UI 触发了重读状态变化，但请求未恢复到可见新数据。与此同时，另一新 IAB 标签的实时页连续约 27 秒读取时间推进且未 stale，说明故障具有间歇性/标签间差异；尚不能据此断定是 worker 问题。
- 后续新建的第三个 IAB 标签进入实时监控后，连续约 30 秒读取时间推进且保持定时读取。这进一步确认故障并非每次启动都会发生，但短时正常仍不足以关闭长时间轮询验收。
- 另在 IAB 地址栏打开对应 `/api/v1/metrics/query` URL 时，Vite 返回 SPA 页面而非可读 JSON；这是顶层导航探针，不构成 API handler 响应证据。
- 只使用 Codex IAB，没有调用 Chrome、Edge、CDP，也未访问真实 Python Console、数据库或配置中心。未运行浏览器自动化套件。此证据将“短时双标签未复现”更新为“单个新标签也可复现、并可与另一成功轮询标签并存”，但不证明真实网络、生产采集或长期稳定性。`F4.11` 保持未勾。

## 原始未收口观察（已由下方复验更新状态）

- 历史标签确实出现过 stale；整页 reload 后至少一个 5 秒周期读取恢复。该随机历史现象的触发根因仍未知；本轮则在有效 app-two 上以受控一次性 503 观察到当前 stale→自动恢复 UI 行为。前者不否定当前受控路径的验收，后者也不解释历史随机现象。
- 实例下拉框最多载入 100 条；超出时已显示总数提示并建议收窄应用筛选。通用可搜索/分页实例选择仍需后续产品决策，不在本次完成范围。
- 当前证据是本地 MSW 合成数据，不证明 Python Console 或生产 Reporter/Collector 的实例目录与指标协同。

## 2026-10-08 当前工作区复验：应用筛选与 stale 自动恢复

- **筛选/同窗摘要：**在 Codex 内置浏览器本机 demo 从 app-two 切至 app-three，URL 和应用筛选器同时更新，仍停留实时监控；QPS 从 84 变为 63 req/s、p95 从 58 变为 46 ms。前台轮询读取时间推进 5 秒。
- **错误/恢复：**打开新鲜可见的 app-two 标签，确认 QPS 84。受控一次性 HTTP mock 503 使指标 QueryView 进入 stale；页面说明数据不是最新状态，出现“重试读取”，上次可信 QPS 84 仍保留。没有点击 retry；下一自动轮询后状态恢复、读取时间从 `14:44:55` 前进到 `14:45:05`，QPS 84 仍在、retry 按钮消失。
- **验证命令：**`npm run test:logic:focused -- 'MONITOR-(POLL|STALE)'` **2/2**；`npm run test:http:focused -- 'METRICS-(MOCK|RECOVERY|MONITOR-RECOVERY)'` **3/3**；`npm run check:fast` exit 0。未运行 `check:milestone` 或完整 E2E。
- **更新结论：**F4.11 的本地前端 query/filter/same-window/自动轮询可见路径已验收，可勾该前端切片。此前记录的随机标签 stale 未找到根因，且本轮 stale 是显式受控的一次性 503；不据此声称长时间稳定或真实网络恢复。后台计时器、迟到响应、权限撤销、长期内存/订阅与 Python Console/Reporter/Collector 真实来源留在 F4.12/B0 验收。
- **浏览器/服务边界：**只使用 Codex IAB；本机 demo server 绑定 `127.0.0.1:5198`。未使用 Chrome/Edge/CDP，未访问或写入真实 Console、数据库、Nacos 或 Consul。临时标签和 Vite 服务在本轮结束时关闭。

## 2026-10-08 IAB 后台标签与可见标签并行对照

- 同一时段保留两个本机 Mock 实时页：标签 95 创建时指定 `visible:false`，标签 96 创建时指定 `visible:true`；二者查询上下文均为 `test-env`、全部应用、最近 1 小时。
- 检查时，后台标签 95 的 `读取时间` 冻结于 `12:10:56 UTC` 并显示 stale；可见标签 96 的 `读取时间` 已推进到 `12:13:08 UTC`，仍显示定时读取和有效样本。之前对标签 96 的约 30 秒观察也正常。
- 这为“后台/不可见页面节流或 worker 可见性相关”提供了新的相关性线索，但不是根因证明：没有读取 `document.visibilityState`、浏览器后台计时器策略或实际网络请求日志；标签创建时间和运行时状态并非受控单变量实验。下一步应在 IAB 中进行同一页面隐藏→可见→恢复的可重复对照，并分别确认重试后时间戳是否推进。
- 全部是 Mock 数据；未访问真实 Console、数据库或配置中心，未调用 Chrome、Edge、CDP。F4.11/F4.12 继续保持未完成。

### 后续观察：后台创建标签恢复（2026-10-08）

- 对 `visible:false` 创建的标签 95 再等待约 30 秒，读取时间从此前的 `12:10:56 UTC` 推进到 `12:16:16 UTC`，stale 状态消失，页面恢复有效 Mock 样本。可见标签 96 同时推进至 `12:16:23 UTC` 并保持定时读取。
- 因此先前后台标签 stale 是某一时点状态，不是持续失败；可见性/后台节流仍只有相关性线索。本次没有受控执行同一标签的隐藏→前台切换，也没有网络或 worker 日志，无法归因恢复原因。
- 仅为本地 Mock 页的 IAB 观察；不构成浏览器长时稳定性或真实后端验收。F4.11/F4.12 仍不关闭。

## 2026-10-08 当前工作树复核

- 在 Codex IAB 的新 `localhost:5184` 标签访问 `#/setup` 后，页面依据服务端 Mock bootstrap 状态重定向到 `#/login`；以测试专用内置 admin 合成凭证登录后抵达总览，页面显示示例 banner、QPS 189、p95 63 ms、TPS unavailable 与 3 个应用。没有执行 setup 或持久化/配置中心写操作。
- 同一工作树 `npm run check` 经仅对 `127.0.0.1` loopback 测试授权后 exit **0**；该命令不包含会启动 Chrome 的 E2E。
- 此次仅证明 initialized Mock session 的登录→总览与完整非浏览器工程门禁。后台标签 stale 观察仍属间歇现象；网络原因、首启初始化、长时恢复、Python 后端及配置中心都未验证。F4.11/F4.12 不勾选。

## 2026-10-08 新鲜 Codex IAB 前台轮询窗口

- 在本机 `127.0.0.1:5195` 新建 Codex IAB 标签，使用合成 admin 进入 `#/realtime?env=test-env&app=all&range=1h`。页面显示 `test-env` 汇总，QPS 189 req/s、p95 63 ms、拦截率 4%、CPU 49%、内存 50%；TPS 明确 unavailable；QPS/RT/拦截/CPU/内存曲线均为 **60/60** 点。
- 页面“读取时间”在多次复读间从 `13:48:21 UTC` 前进到 `13:48:56`、`13:49:31`、`13:50:11`、`13:50:46 UTC`；这一可见会话观察约 80 秒，没有 stale/error。
- 这属于新鲜 IAB 前台 Mock 会话的短时成功观察。既往新标签也曾进入 stale，因此无法关闭间歇性失败、后台节流、网络错误、长时间稳定性或 Python Console 实时指标验收。F4.11/F4.12 保持未勾。
- 只使用 Codex 内置浏览器，未调用 Chrome、Edge 或 CDP；临时 Vite 服务已停止。未访问 Python Console、数据库、Nacos/Consul 或生产服务。
