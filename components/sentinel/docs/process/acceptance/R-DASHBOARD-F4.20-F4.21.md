# R-DASHBOARD-F4.20 / F4.21 首次初始化前端验收记录

日期：2026-10-08  
范围：Sentinel Dashboard 前端原型 / same-origin HTTP mock 及 Codex 内置浏览器。  
不包含：Python Console、真实数据库、Nacos / Consul 或生产环境验收。

## 本轮已验证

- 修复 setup 首屏加载循环：普通 bootstrap 读取复用已确认的共享认证快照；用户显式检查、初始化命令前和命令回执后的确认仍执行强制刷新，避免 setup 自己的检查把唯一认证 owner 反复重置到 `checking`。
- 初始化成功只证明安装状态已确认，不创建管理员登录会话。HTTP mock 回归断言 setup 后 bootstrap 已关闭且 principal 仍为 anonymous；登录身份必须另走登录和 `/auth/me` 确认流程。
- 在 Codex 内置浏览器中使用合成 demo 会话完成首次初始化页面流：setup 表单、配置摘要、提交后跳转登录页；初始化后重新进入 setup 会回到登录页。未初始化时直接打开 login 会被替换为 setup，setup 页面没有登录返回入口。浏览器操作仅使用 IAB，没有启动或连接 Chrome、Edge、CDP。
- 新鲜静态/HTTP 验证：typecheck、lint、format、contract、i18n、逻辑 243/243、架构 13/13、HTTP 88/88、build-profile 2/2、demo build、Sites worker 4/4 均通过。

## 2026-10-08 补充：跨标签首启状态再校验

- **复现事实：**IAB 的两个同源标签中，一个标签完成 mock 初始化后，另一个仍打开的 setup 标签继续显示旧的未初始化快照。静态检查和单标签首启流程此前没有覆盖此场景。
- **实现：**认证 Provider 在文档重新可见/窗口重新获得焦点时调用唯一 `AuthenticationWorkflow` owner 的 `revalidateAccess()`，从 bootstrap 与 session 权威端重读；刷新期间权限进入 checking。若初始化回执后的显式刷新与后台焦点刷新相撞，显式刷新 supersede 后台读取，避免用旧快照确认初始化。expired session、登录/登出结果未知、命令处理中或已有明确失败待用户检查时，不做自动恢复。
- **自动化：**逻辑测试现为 **246/246**，新增覆盖从 `uninitialized → anonymous → authenticated → anonymous` 的权威重读、unknown write 不被焦点刷新清除、初始化回执检查 supersede 未完成后台读取，以及 focus/visibility 监听仅在可见时读取并能清理监听。
- **完整非 CDP 门禁：**最终 `npm run check` 通过，包含 typecheck/format/lint、Hooks 6/6、架构 13/13、逻辑 246/246、HTTP 89/89、OpenAPI contract、浏览器工具单测、visual/i18n/verification 工具、i18n、live+demo build、build-profile 2/2 和 Sites worker 4/4。`npm run check` 未调用 Chrome/Edge/CDP 启动浏览器；`npm run test:e2e` 仍未运行。既有 Zod 注释与初始 JS chunk 警告保留。
- **浏览器边界：**仍只使用 Codex 内置浏览器。IAB 两个标签实际复现了旧 setup 快照；用测试 fixture 完成另一个标签的初始化后，原标签在本轮 IAB 操作界面中仍显示其原快照，随后整页 reload 才按权威 bootstrap 进入 login。IAB 操作接口本轮无法独立触发/确认真实浏览器标签切换产生的 `focus` / `visibilitychange` 事件；因此新的前台监听虽有注入事件单测覆盖，实际标签切换行为仍未取得 IAB 验收证据。不得将工作流测试或页面 reload 冒充该浏览器验收。
- **状态边界：**F4.20/F4.21 仍未完成；上述修改仅处理浏览器恢复前台后的客户端权威状态刷新，不替代 Python bootstrap/事务/持久化/并发锁、配置中心写回、完整字段及秘密清理验证。

## 仍未关闭

- F4.20 整项未完成：本记录没有逐一验收所有字段级错误、各种网络失败/恢复、数据库与配置源切换、凭证清理、取消/离开清理及实际后端校验语义。
- F4.21 整项未完成：真实 MySQL 首启 HTTP 切片已覆盖 initialized gate 关闭、重复 initialize 被拒，以及 `/auth/me` 仍为匿名（见 2026-10-12 补充）；React 到 Python 的 mounted 浏览器流程、生产配置中心写回和部署级验收仍开放。
- 完整 `npm run test:e2e` 未运行：该脚本通过 CDP 启动外部浏览器，与当前明确的“只使用内置浏览器”约束不兼容。IAB 手工交互及自动化逻辑/HTTP 测试不冒充全自动浏览器 E2E；需要覆盖的浏览器交互优先改用 IAB，不能回退到 Chrome/Edge。
- `tests/e2e/probes/first-run.html` 与 `first-run.ts` 仅为 Vite 本地验收入口，用于在 IAB 中设置确定性合成 bootstrap 情景；两者位于测试目录，build-profile 门禁须持续确认不会进入产品构建。
- Demo build 保留既有 Zod PURE 注释警告和约 1.19 MB 初始 JS chunk 体积提示；不是本轮首启行为的验收失败，但仍需性能任务处理。

## 2026-10-12 补充：真实 MySQL 首启关闭 gate 且不自动登录

- **缺口与修复：**真实 MySQL first-run ASGI 验收已检查 bootstrap initialized gate、重复初始化拒绝及持久化 receipt，但没有检查业务会话。现在初始化后同一 HTTP client 读取 `/api/v1/auth/me`，必须得到 `200` 与 JSON `null`，避免将一次性 setup/operator 授权误当成管理员登录。
- **验证：**在 `components/sentinel/sentinel-console` 执行 `./tools/with_disposable_e2e_dependencies.sh uv run --extra test --extra mysql pytest -q tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_z_full_first_run_http_path_persists_setup`，真实 MySQL `8.4.11` + Consul `1.21.1`，**1 passed**。本轮临时容器 `sentinel-e2e-mysql-09c0f8106944bd2fe664b7abb10d773f`、`sentinel-e2e-consul-09c0f8106944bd2fe664b7abb10d773f` 在脚本退出后按精确名称查询均不存在。
- **边界：**这是真实 MySQL + Python ASGI 首启路径证据，不是 React HTTP adapter 到 Python 的 mounted 浏览器 E2E，也不证明 PostgreSQL、生产 Ingress、多 worker、真实配置中心写回或所有 setup 表单 UI 状态。F4.20/F4.21 仍未完成；最终浏览器 E2E 仍按清单后置。

## 2026-10-09 补充：初始化 workflow 强制 bootstrap 刷新参数

- **发现与修复：**`InitializationWorkflow.restore(forceRefresh?)` 原先丢弃调用方参数，导致 `restore(true)` 仍以普通读取方式调用 Port。新增回归先观察到 `[false, false]`，随后将参数显式透传，使普通读取/强制刷新分别收到 `false` 和 `true`。
- **验证：**`npm run test:logic:focused -- 'SETUP-BOOTSTRAP restore forwards an explicit force refresh'` **1/1 passed**；`npm run test:logic:focused -- 'SETUP-'` **21/21 passed**；`npm run check:fast` exit **0**。
- **边界：**证明 workflow 到 Port 的刷新语义，不证明 HTTP adapter 是否绕过缓存、已挂载浏览器行为或 Python bootstrap 服务联调。F4.20/F4.21 仍未关闭，完整 E2E 留到全部实现任务收口后。

## 2026-10-08 补充：连接失败恢复的 workflow/HTTP 聚焦回归

- **覆盖路径：**将原来直接调用初始化 HTTP Port 的 fail-once 用例提升为 `InitializationWorkflow → Console HTTP adapter → MSW`。数据库和 Consul 检查都断言请求中为 `loading`、一次合成 503 后为 `error`、显式重试后为 `ready/reachable`；检查期间/之后的 workflow snapshot 均不含数据库密码或 ACL token。bootstrap 仍为未初始化，测试结束后清理 workflow。
- **验证：**目标 HTTP 用例 **1/1**、`SETUP-CHECK revisions` logic 用例 **1/1** 通过；`npm run check:fast` exit 0（typecheck、format、lint、Console OpenAPI 42 paths）。首次使用的过窄测试名正则未匹配任何测试、退出 2，未执行测试；改用匹配标题的正则后成功运行。
- **节奏边界：**这是初始化 workflow/传输切片的聚焦回归，不是页面 E2E；本轮没有启动浏览器，也没有运行 `check:milestone`/完整 E2E。完整页面 E2E 留到 milestone。F4.20/F4.21 仍未完成：真实 Python Console、所有字段/凭证切换清理分支、取消/卸载清理及服务端初始化安全属性仍未验收。

## 2026-10-08 补充：IAB setup 校验、重试与路由门禁

- **浏览器限制：**本轮只使用 Codex 内置浏览器（IAB）；未启动 Chrome/Edge，也未运行 CDP E2E。通过 Vite 本地 server + `tests/e2e/probes/first-run.html` 的显式合成场景测试；没有向真实 Python Console、关系数据库、Nacos 或 Consul 发请求。
- **字段错误与恢复：**空数据库连接信息点击“测试数据库连接”时显示字段提示；补填字段后旧提示立即消失。当前 HTTP schema 与 API 文档要求 PostgreSQL/MySQL 的密码必填，原前端校验漏掉密码导致空密码落到通用连接错误。本轮已把必填规则补齐并同步中/英/日文文案，`useSetupFlow` 现在在任意表单字段编辑后清掉过期 notice。此证据仅覆盖 Mock/UI。
- **连接失败安全重试：**本地 Mock 的 `database-check=fail-once` 场景先显示合成连接失败，再使用同一表单显式点击重试，状态变为“连接可达”；未自动重放，也未保存真实凭证。
- **路由门禁：**合成未初始化状态打开 `#/login`，接受未保存表单的显式丢弃确认后仍被路由回 `#/setup`；setup 页面没有返回登录的动作。合成已初始化状态进入 login 后，页面无 setup 入口；直接访问 `#/setup` 被路由回 login。
- **自动化与静态验证：**修复后 `npm run typecheck`、目标文件 ESLint、目标文件/三语 JSON Prettier、`npm run i18n:check` 均通过；`npm run test:logic` 247/247 通过；`npm run test:http` 首次因 sandbox 不允许监听 loopback 失败，按限定本地监听权限重跑后 94/94 通过；`git diff --check` 通过。
- **仍未覆盖：**没有执行初始化提交（因此没有 IAB 输入或保存管理员凭证）、成功后的页面跳转/重入、source-check 失败恢复、provider/auth/database 切换后的逐字段敏感数据清理、离开页面后的内存秘密清理、服务端 bootstrap/DB 事务/迁移锁/持久化/重启恢复。F4.20 与 F4.21 仍未完成；真实 Python Console 验收继续属于 B0。

## 运行环境限制

HTTP 测试需要绑定隔离的 `127.0.0.1` listener。本轮在明确限定为此本地测试命令的权限下运行，88 项全部通过；没有访问外网或真实服务。

## 2026-10-08 补充：内置浏览器首次初始化字段专项检查

- **浏览器路径：**本机 Vite demo 使用 `first-run` mock profile，Codex IAB 从 `#/setup` 进入一次性授权页；提交合成授权码后实际显示初始化向导。SQLite 连接检查显示“连接可达”；管理员字段空提交显示必填提示。整个流程没有提交最终初始化命令。
- **字段切换：**选择 PostgreSQL 并输入合成主机、用户名和密码后切至 MySQL，再返回 PostgreSQL；用户名与密码没有恢复为之前输入值。切换到规则源步骤后，“在控制台填写凭证”选项实际显示 Nacos 用户名/密码字段，满足内网部署直填路径的 UI 可达性。值全部为合成测试内容，不含真实凭证。
- **安全边界：**没有执行初始化完成、账号创建、规则源登记等最终写命令；IAB 标签已关闭，本机 Vite 进程已停止。未访问 Python Console、真实数据库、Nacos、Consul 或生产服务，未启动 Chrome、Edge 或 CDP。
- **证据边界：**这补充了页面字段和数据库类型切换的局部渲染证据，不证明所有表单秘密清除分支、离开/取消时的 React 内存清理、规则源连接检查反馈、Python 端验证或真实初始化事务。F4.20/F4.21 仍未完成。

## 2026-10-08 补充：可选 Mock 首启 profile 与 IAB 初始化闭环

- **实现：**Identity Mock scenario 增加默认 bootstrap facts。默认 profile `initialized` 保持现有演示登录路径；设 `VITE_CONSOLE_MOCK_BOOTSTRAP_PROFILE=first-run` 时，干净 localStorage 会报告 `initialized=false` 且 `operatorAuthorized=false`，明确经过授权门禁。显式保存的 mock 初始化/授权状态优先于启动默认值。只有 mock handler assembly 读取该环境变量，产品页面继续只调用统一 Console HTTP adapter；不在 live profile 引入该配置。`.env.example` 提供注释示例。
- **HTTP 回归：**新增 workflow + ConsoleTransport + MSW 测试：first-run profile 初始为 uninitialized/unauthorized；只在提交一次性授权 HTTP 请求并回读确认为 authorized 后才允许 setup；授权没有创建账户会话 principal。typecheck 通过，目标测试通过。
- **IAB 端到端页面路径：**在新鲜 `localhost:5185` origin 进入授权页；提交合成授权码进入初始化；SQLite 检查通过；填入合成首个管理员；选 Nacos、synthetic namespace 与匿名 Mock auth，source 检查通过；摘要确认后提交，跳转 `#/login?app=all&range=1h`。登录页无 setup 入口；直接打开 `#/setup` 再次落回 login。通过只读 `/api/v1/auth/me` 页面读取确认响应 `null`。这覆盖了真实 React 路由与页面经 HTTP Mock 的完整首次初始化体验，没有通过脚本或 localStorage 伪造首启状态。
- **边界：**表单值和检查回执均为合成数据，经 MSW 在本机被拦截；无真实数据库或配置中心连接，也没有 Python Console。真实 bootstrap 授权密钥、原子事务/并发锁、迁移、配置源写入、口令安全存储和服务重启后关闭 setup 尚未实现/验收。F4.20/F4.21 保持未完成。用户要求只用 Codex 内置浏览器；未调用 Chrome、Edge、CDP，也未运行 `npm run test:e2e`。
- **门禁：**新增首启用例通过；完整 `npm run check` 在仅允许受控测试绑定 `127.0.0.1` 后 exit **0**，覆盖 typecheck、format、lint、Hooks/architecture/logic/HTTP、contract、browser-tool/visual/i18n/verification、i18n、live/demo build、build-profile 与 Sites。命令不运行 E2E 浏览器脚本。已有 >500 kB chunk 和 Zod 注释警告保留。

## 2026-10-09 补充：setup 表单秘密清理的纯状态切片

- **实现：**identity model 新增不可变 `clearSetupSecrets(draft)`。清空数据库用户名/密码、全部规则源认证字段和管理员密码/确认；保留账号名、数据库/来源地址及其它非敏感设置。`useSetupFlow.clearSensitive()` 调用同一 pure policy，仍会先失效数据库/来源连接检查，再清理提示。完成回调与导航保护 discard 路径都使用该 Hook command。
- **聚焦验证：**`npm run test:logic:focused -- 'SETUP-(SECRET|COMMAND)'` **10/10 passed**。新 `SETUP-SECRET` 用例验证秘密字段无残留、非敏感上下文保留、原 draft 未变；既有 `SETUP-COMMAND` 用例继续覆盖取消后的 unknown outcome 不被误报 rollback、无写重放。
- **快门禁：**`npm run check:fast` exit 0：typecheck、Prettier、ESLint、OpenAPI contract 均通过。依新测试节奏未运行完整 logic/HTTP、浏览器 E2E 或 `check:milestone`；浏览器仅限 IAB 的约束不变。
- **边界：**当前证据是纯模型和初始化 workflow，不是已挂载 React 表单的 discard/success 页面 E2E；JavaScript 字符串清理表示从应用状态移除引用，不承诺引擎物理覆写内存。尝试启动本地 Vite 以用 IAB 补查页面时，`127.0.0.1:5196` 监听被 sandbox 拒绝（`EPERM`），故本轮未取得页面证据；没有改用外部浏览器或 CDP。F4.20/F4.21 仍未完成，Python、数据库、Nacos、Consul 未参与。

## 2026-10-09 补充：mounted setup 表单放弃路径（Codex IAB）

- **页面路径：**在授权后的合成 first-run Mock 页面填入数据库主机、用户名和密码，尝试转到 login。React 路由呈现统一离开确认；选择“放弃更改并离开”后，未初始化状态仍强制停留在 setup，重新呈现表单中的用户名和密码为空。输入均为本地合成值，未提交初始化命令；IAB accessibility tree 是字段清空的直接证据。
- **验证节奏：**只执行该功能切片的内置浏览器检查；没有运行 `check:milestone` 或完整浏览器 E2E。未调用 Chrome、Edge、CDP；Vite demo 服务随后停止。
- **剩余范围：**这证明离开确认后的 mounted UI 丢弃路径，不等于底层 JavaScript 内存物理擦除，也没有覆盖成功完成清理、字段错误全矩阵或 Python 持久化。F4.20/F4.21 保持未勾；真实服务与数据库未参与。

## 2026-10-09 补充：初始化成功后的 mounted 路由与登录状态（Codex IAB）

- **页面路径：**使用隔离的 `localhost:5196` origin 和 `VITE_CONSOLE_MOCK_BOOTSTRAP_PROFILE=first-run`。在真实 React setup 页面中通过授权、合成 PostgreSQL 连接检查、首个管理员表单、Nacos 匿名连接检查与初始化提交；完成回执后 URL 到达 `#/login?app=all&range=1h`，可见登录名/密码表单，无已登录管理页外壳。
- **隔离更正：**首次尝试复用 `127.0.0.1:5196` 时继承了旧演示 admin session，完成后跳至 overview。该观察是被污染的 origin 状态，不作为自动登录或初始化完成路径的证据；不清除旧 origin 数据，改用全新 hostname 复验。fresh-origin 页面显示登录表单。IAB storage API 不可用，因此不报告 storage 级凭证扫描结果。
- **验证范围：**当前只确认成功路径由 Mock 页面进入 login、没有自动认证；页面离开后不再渲染 setup 表单。`InitializationPage` 成功 Effect 调用 `clearSensitive()` 的代码路径另有源码证据，不能将路由跳转夸大为 JS 物理内存擦除。使用的账号/密码均为合成值，未访问 Python、数据库或真实配置中心。
- **节奏与后续：**这是初始化 feature 的局部 IAB 检查，不是完整产品 E2E；没有运行完整 E2E 或 `check:milestone`，未调用 Chrome、Edge、CDP。`localhost:5196` 当前合成 Mock bootstrap 为 initialized；新的首启验证需使用新的隔离 origin。F4.20/F4.21 仍保持未完成。

## 2026-10-09 补充：连接检查原因与显式恢复

- **实现：**setup 反馈按连接检查的稳定原因枚举区分身份验证失败、服务不可达和连接方式不支持，并提供简中/英文/日文提示；任意原始异常消息和凭证不参与文案。失败后需用户再次显式触发连接检查，成功结果才替换原失败状态。
- **定向验证：**`npm run test:logic:focused -- 'SETUP-CHECK'` **2/2 passed**，覆盖数据库 authentication failure、source unsupported → explicit retry → reachable 及 snapshot 敏感值隔离；`BOOTSTRAP-CHECK` HTTP focused **1/1 passed**，按 bootstrap authorize/CSRF 顺序验证 wire reason；`npm run check:fast`、`npm run i18n:check`（三语各 1,175 keys）通过，`npm run test:i18n-tools` **29/29 passed**。没有启动浏览器或 Python Console。
- **边界：**仅证明 workflow 和文案选择逻辑，没有 React rendered/IAB、真实网络或服务端验收；完整 E2E 留待所有实现任务之后。F4.20/F4.21 仍未完成。

## 2026-10-09 补充：初始化字段错误归属与复核回跳

- **实现：**`SetupIssue` 现在携带明确的 setup 字段归属；数据库缺项按字段分别返回、Nacos 缺失用户名/密码分别定位，端口/管理员确认/来源地址/凭证字段也具有自己的错误目标。`useSetupFlow` 保留当前步的全部问题而非只取首条；“完成初始化”复核发现前序字段无效时，回到最早责任步骤。SetupWizard 将同一问题投影为字段级 Astryx `TextField` error，并通过三语字段错误与 `role=alert` 的摘要提示用户；连接检查仍只报告第一步中发现的本地字段错误，不发出网络请求。
- **错误恢复：**字段错误不是第二份持久状态；Flow 只记录用户已尝试校验的步骤，并从最新 draft 实时重算。修复一个输入仅移除已不成立的问题，其它错误继续显示；DB/provider/auth 切换后按新分支重新求值。
- **自动化验证：**`npm run test:logic:focused -- SETUP` **15/15 passed**，新增断言覆盖数据库多缺项、管理员用户名/密码/确认、规则源凭证引用字段归属及错误对应步骤；`npm run typecheck`、`npm run format:check`、`npm run lint`、`npm run i18n:check` 均通过。新增文案已覆盖简中/英文/日文，i18n 报告每种语言 1,150 keys、静态键校验 1,012。
- **验证边界：**这是纯校验与静态/局部工程门禁证据；没有启动页面、执行 Codex IAB 或完整 E2E，也没有接入真实 Python Console/数据库/配置中心。尚无实际 rendered evidence 确认 Astryx detached status 在窄屏/长文案下的呈现；提交过程及网络 fail-once 的完整字段/清理矩阵仍开放。F4.20/F4.21 继续未完成。

## 2026-10-09 补充：初始化字段与连通失败分支定向矩阵

- **补齐：**新增 source 字段归属矩阵，逐项验证 Nacos credential-reference / direct 用户名与密码、Consul direct token、none auth 与无效 endpoint；这些本地问题均绑定当前 Sources 步骤内的明确字段。初始化连接工作流测试补上数据库与来源检查的 `connection` 失败原因，并验证它们与 authentication/unsupported 一样能由用户显式重试替换为 reachable；状态快照不含原始凭证。
- **验证：**`npm run test:logic:focused -- 'SETUP-'` **17/17 passed**；`npm run check:fast` 通过（TypeScript、Prettier、ESLint、Console OpenAPI 43 paths）。本轮前序 `npm run test:http:focused -- 'BOOTSTRAP-HTTP'` **1/1 passed**，覆盖检查接口不执行持久初始化。
- **边界：**没有页面渲染/IAB 或完整 E2E；没有真实 Python Console、数据库或配置中心。此处只关闭字段/失败逻辑矩阵，不关闭 F4.20/F4.21 整体验收。

## 2026-10-09 补充：服务端初始化验证拒绝后的安全恢复

- **协议事实：**`POST /api/v1/system/bootstrap/initialize` 的 operation receipt 仅有稳定的 `validation` / `setup-closed` / `dependency` 拒绝原因，不包含 field path 或逐字段 issue。前端据此只呈现脱敏通用拒绝信息；字段定位来自本地 setup model 校验，不推断服务端错误属于某个输入。
- **workflow 合同：**新增逻辑用例模拟已知 `validation` 拒绝，确认状态保持为 `rejected` 且 snapshot 不包含管理员密码；后续只有用户再次明确提交修正输入才发出新操作，新操作使用不同 request key，完成必须等待 operation receipt 与 bootstrap 权威状态双确认。
- **验证：**`npm run test:logic:focused -- 'SETUP-'` **18/18 passed**；`npm run check:fast` exit **0**（TypeScript、Prettier、ESLint、Console OpenAPI 43 paths）。
- **边界：**测试没有挂载 React 表单，也没有证明服务端能返回逐字段错误；未运行 IAB、Chrome/Edge/CDP 或完整 E2E，未连接真实 Python Console、数据库或配置中心。F4.20/F4.21 继续开放。

## 2026-10-09 补充：按服务端拒绝原因呈现三语恢复动作

- **状态投影：**`validation`、`setup-closed`、`dependency` 分别映射为可操作的简中/英文/日文提示；协议没有 field path，因此不显示虚假的字段错误。`result-unknown` 仍提示核查原请求并禁止重复初始化。
- **验证：**`SETUP-` 逻辑 **19/19 passed**；`tests/i18n/catalog.test.mjs` + `dynamic-callsite-coverage.test.mjs` **13/13 passed**，实际按三个 locale 的 i18next catalog 渲染投影出的原因提示，并验证三类文案不同。`npm run check:fast` 通过，`npm run i18n:check` 显示简中/英文/日文各 **1,177** 条资源。
- **边界：**无 mounted 页面/浏览器运行、无真实 Python 后端联调；完整 E2E、数据库与配置中心均未触及。F4.20/F4.21 继续开放。

## 2026-10-09 补充：初始化拒绝反馈实际 React 组件 SSR 渲染

- **覆盖：**将真实 `InitializationFeedback` 组件加载到 Vite SSR 模块图，在 React `I18nextProvider` 下分别渲染服务端 `validation`、`setup-closed`、`dependency` 拒绝快照；三种 locale 的 HTML 均含对应恢复文案，且不包含请求标识或凭证 sentinel。此前仅验证纯 key 投影和 i18next 字典，本次把覆盖推进到实际 React 组件输出。
- **验证：**`npm run test:logic:focused -- 'SETUP-'` **19/19 passed**；`node --test tests/i18n/catalog.test.mjs tests/i18n/dynamic-callsite-coverage.test.mjs` **13/13 passed**；`npx prettier --check tests/i18n/catalog.test.mjs` 通过。
- **边界：**这是 server-side static markup 验证，不执行 DOM hydration、浏览器事件、焦点、键盘或样式布局；仍需最终 IAB/E2E 与真实 Python API 验收。未调用 Chrome、Edge 或 CDP，也未连接真实数据库、Nacos、Consul。

## 2026-10-09 补充：初始化页面与字段错误状态投影 SSR

- **覆盖：**将真实 `InitializationPage` 与其实际 `SetupWizard`、`InitializationFeedback` 组合加载到 Vite SSR 模块图，在简中/英文/日文分别渲染数据库检查 pending、初始化结果未知、初始化命令失败和服务端已初始化四种快照。断言 pending 只禁用数据库检查按钮而不禁用表单；未知结果锁定向导并显示核查原操作入口；已初始化时不再渲染 setup wizard；失败状态使用稳定恢复文案，不泄漏原始异常细节、request key 或 secret sentinel。另将有多个字段问题的真实 `SetupWizard` SSR 输出渲染到三语目录，检查对应标签、字段错误和 alert summary 存在。
- **验证：**`node --test tests/i18n/catalog.test.mjs tests/i18n/dynamic-callsite-coverage.test.mjs` **16/16 passed**；`npx prettier --check tests/i18n/catalog.test.mjs` 通过。
- **边界：**SSR 使用受控 workflow snapshot，不运行 React 浏览器 Effect、hydrate、真实表单事件、CSS 布局或路由跳转；不替代 mounted/IAB 全流程和 Python Console 联调。未调用 Chrome、Edge、CDP，未访问真实数据库、Nacos 或 Consul。F4.20/F4.21 仍未完成，最终 E2E 继续留到所有实现任务收口。

## 2026-10-09 补充：一次性 bootstrap 授权 gate 的组件隔离 SSR

- **覆盖：**将实际 `BootstrapAuthorizationGate` 加载到 Vite SSR 模块图，在简中/英文/日文分别渲染服务端快照中的“需授权”“已授权”“初始化窗口已关闭”。以 protected-child sentinel 断言未授权/关闭时初始化子树不会出现，只有服务端快照确认授权后才渲染子树；未授权状态仍呈现密码型一次性授权字段。
- **验证：**`node --test tests/i18n/catalog.test.mjs tests/i18n/dynamic-callsite-coverage.test.mjs` **17/17 passed**；`npx prettier --check tests/i18n/catalog.test.mjs` 通过。
- **边界：**这是组件静态渲染和受控 workflow snapshot 测试，不执行客户端授权交互、路由跳转或 Python 服务验证；服务端每个初始化 API 的授权/事务合同仍须 B0 后端验收。没有启动浏览器、Chrome、Edge 或 CDP，也没有访问真实 DB/config center。F4.21 保持未勾，完整 E2E 继续留到所有实现任务收口。

## 2026-10-09 补充：Python 首启连通检查路由聚焦合同

- **验证：**在 Sentinel Console 包内运行 `PYTHONPATH=src .venv/bin/pytest -q tests/test_bootstrap_database_check_api.py tests/test_bootstrap_source_check_api.py`，**14 passed**。测试实例覆盖 database/source check API 的受控 checker、未授权与错误输入保护、稳定失败原因和响应安全头；结果与前端 `ConnectionCheckSchema` 的 `reachable` / `unreachable` 三原因联合一致。
- **边界：**checker 为测试替身，未通过 PostgreSQL/MySQL、Nacos、Consul 网络客户端连接外部服务；不代表生产连接超时、TLS、凭证 resolver 或真实首次初始化事务已验收。HTTPX 测试 cookie API 有 28 条 deprecation warnings，本次结果仍为通过；未访问真实数据库/配置中心，未运行浏览器或 E2E。

## 2026-10-09 补充：一次性 setup 授权覆盖 POST 到权威回读的单飞窗口

- **缺口与修复：**`createCommandResource` 在授权 POST 成功后就结束自己的 pending 窗口，但 one-time authorization 用例还必须等待强制 gate read-back。workflow 新增完整用例级互斥，在该区间拒绝第二次授权、外部 gate refresh 与 inspect，避免并发读取替换尚未确认的回执状态；读回确认或失败后才释放互斥。授权码没有进入 workflow snapshot。
- **验证：**新增受控异步 HTTP-suite 测试，先将 read-back 保持 pending，再断言 duplicate authorization/restore/inspect 均被拒绝、Port 只收到一次授权且 snapshot 不包含一次性 code，最后完成权威确认。`npm run test:http:focused -- 'IDENTITY-MOCK: first-run|BOOTSTRAP-AUTH'` **2/2 passed**；`npm run test:logic:focused -- 'SETUP-'` **19/19 passed**；`npm run check:fast` 通过（typecheck、Prettier、ESLint、43-path OpenAPI contract）。
- **边界：**该互斥保证是前端 workflow 合同，不替代 Python 服务端对一次性代码原子消费/并发授权的保证。未运行 mounted 页面/E2E、未调用 Chrome/Edge/CDP、未连接真实 Python、数据库或配置中心。F4.21 仍未完成。

## 2026-10-09 补充：数据库与规则源连接失败反馈 SSR

- **覆盖：**扩展真实 `InitializationPage` 组件树的 SSR 状态矩阵，在简中/英文/日文确认数据库认证失败与规则源不支持分别显示对应的可恢复文案；数据库失败时当前 storage 步骤的显式重试按钮仍可用。Sources 步骤下的规则源重试按钮及单飞状态由独立 `SetupWizard` SSR 用例覆盖。
- **验证：**页面聚焦 SSR `node --test --test-name-pattern='F4.20-SETUP-PAGE-RENDER|F4.20-SETUP-CHECK-RENDER' tests/i18n/catalog.test.mjs` **2/2 passed**；完整 `node --test tests/i18n/catalog.test.mjs` **17/17 passed**；setup workflow `npm run test:logic:focused -- 'SETUP-'` **20/20 passed**；`npm run check:fast` 与 `git diff --check` 通过。
- **边界：**该覆盖只验证受控快照的 React SSR HTML，不执行实际点击、网络检查、字段变化导致的取消、视觉布局或真实后端连接。未运行完整 E2E，F4.20/F4.21 继续开放。

## 2026-10-09 补充：重读 bootstrap 期间的 setup gate 保留策略

- **缺口与修复：**`App` 曾在 render 中更新 setup 授权标记，违反本项目 React render 纯度约定。现在认证 workflow 快照仅在重读期间携带最近确认且明确 setup 可用、operator 已授权的 bootstrap facts；不会将旧 authenticated identity 暴露在 checking snapshot 中。首屏未知、明确关闭/未授权及读取失败不能继承保留资格。
- **验证：**`npm run test:logic:focused -- 'F4[.]20'` **4/4 passed**；相关 authentication/expiry/logout 子集 **14/14 passed**；`npm run check:fast` 通过，包含 typecheck、format、lint 和 OpenAPI contract check。
- **边界：**只证明 workflow 与 route policy 的定向合同，不证明 React 挂载/交互或 Python bootstrap；F4.20/F4.21 保持未完成，完整 E2E 留到全部实现完成后。

## 2026-10-09 补充：服务端 setup-closed 回执对陈旧 bootstrap 的安全处理

- **回归复现：**当 initialize 返回稳定 `setup-closed`，而本地 bootstrap 仍是 `setupAvailable=true` 时，原 workflow 将拒绝保留为可重试状态，页面仍渲染 setup wizard。新增 logic 与真实 `InitializationPage` 三语 SSR 用例分别复现这个状态转换和 stale-open 页面。
- **实现：**`setup-closed` 回执转为不可写 `closed` 终态；不能继续提交、测试数据库或测试规则源，向导不再渲染，用户敏感字段被清理。该情况保留只读状态重读按钮。页面闭窗 effect 同时强制重读共享 app `AuthenticationWorkflow` 的 bootstrap/session authority，让现有路由守卫根据新的权威事实决定登录或 fail-closed recovery。
- **验证：**修复前 logic **1 failed**（仍为 `rejected`）及 stale-bootstrap SSR **1 failed**（继续渲染 wizard）；修复后 SETUP logic **22/22 passed**、setup-route revalidation logic **4/4 passed**、页面聚焦 SSR **1/1 passed**、catalog 全集 **18/18 passed**，`npm run check:fast`、`npm run i18n:check` 与 `git diff --check` 通过。
- **边界：**SSR 不运行 `clearSensitive()` / shared authentication refresh 的 React effect；auto route redirect 与 DOM 中密码清空仍需最终 Codex IAB 验证。没有运行完整 E2E、Chrome、Edge 或 CDP，没有连接真实 Python Console、数据库、Nacos 或 Consul。F4.20/F4.21/B0.2 继续开放。

## 2026-10-09 补充：外部 bootstrap 闭窗清理当前挂载的敏感草稿

- **缺口：**页面自身的初始化命令返回 `setup-closed` 时已有清理，但若另一个初始化者在当前页面挂载期间完成初始化，权威 bootstrap 会变为 `initialized=true`；向导虽不再渲染，原逻辑没有把这类事实识别为 `knownClosed`，因此没有调用 `clearSensitive()`。权威 bootstrap 显示 `setupAvailable=false` 也应停止保留仍挂载的敏感表单。
- **修复：**`InitializationPage` 通过纯 presentation policy `isSetupAuthorityClosed()` 将 bootstrap ready 且 `initialized=true` 或 `setupAvailable=false` 纳入关闭终态，但排除本页面 `submitting/checking/pending` 阶段与已确认 `ready`，避免把当前事务成功误判成外部闭窗。关闭后统一清除数据库账号/密码、规则源凭证、管理员密码/确认，并结束 dirty/离开保护；成功 `ready` 保留原完成回调，且不再渲染敏感表单。原有 `InitializationFeedback` 继续从权威 bootstrap 分辨已初始化和 setup 不可用。
- **验证：**`npm run test:logic:focused -- 'SETUP-LIFECYCLE'` **1/1 passed**；`npm run test:logic:focused -- 'SETUP-SECRET'` **2/2 passed**；`node --test tests/i18n/catalog.test.mjs` **18/18 passed**，包含已初始化 bootstrap 不渲染向导；`npm run check:fast`、`git diff --check` 通过。
- **未验证：**SSR 不执行 React effect，尚未观察 mounted 页面里闭窗事件触发后的组件内存状态清理。最终 E2E/IAB 需先填写合成数据库与管理员凭证，在页面仍挂载时切换权威 bootstrap 到 initialized/closed，并确认向导消失、离开不再要求丢弃未完成表单、应用不把秘密写入 storage/URL。没有启动 Chrome、Edge、CDP，也没有连接真实 Python/数据库/配置中心。

## 2026-10-09 补充：授权门禁权威终态清除一次性授权码

- **发现与修复：**`BootstrapAuthorizationGate` 仅在本组件提交授权成功或用户主动复核后清除一次性部署授权码。如果页面保持挂载期间，另一个操作者完成授权或关闭 setup，组件虽会立即转为受保护子树/关闭反馈，但输入值仍保留在本地 React state。现在授权门禁订阅自己的 workflow；只有 bootstrap 权威快照确认 `authorized` 或 `closed` 时，才清空输入。未确认的连接失败/服务端拒绝保留输入，允许操作者显式修正或重试。
- **验证：**`npm run test:logic:focused -- 'SETUP-'` **23/23 passed**；`npm run check:fast` 通过（typecheck、format、lint、43-path OpenAPI contract）。
- **边界：**逻辑测试不挂载该组件，SSR 也不执行 subscription effect；本轮未验证真实 DOM 输入在异步 bootstrap 状态变更后的清空。该检查留在最终 Codex IAB E2E；未运行完整 E2E、Chrome、Edge 或 CDP，未连接 Python Console、真实数据库或配置中心。F4.20/F4.21 仍未完成。

## 2026-10-10 补充：外部闭窗秘密清理的最终 mounted 验收用例

- **新增用例：**扩展 `tests/e2e/initialization.e2e.test.mjs` 与实际 `InitializationProbe`，模拟页面仍挂载时另一初始化者关闭 setup；随后模拟服务端重新报告可用，回到管理员/数据库步骤，断言密码与数据库用户名均为空，且没有原始秘密或异常信息显示。该检查用于证明终态 layout effect 已在重新呈现前清理组件 draft。
- **当前验证：**E2E 文件仅执行 `node --check` 语法检查；Dashboard `npm run check:fast`、`npm run test:logic:focused -- 'SETUP-LIFECYCLE|SETUP-SECRET'`（3 passed）及 `git diff --check` 均通过。按用户要求，本轮未启动任何浏览器，也未运行完整 E2E。
- **边界：**最终 mounted 场景尚未执行，不能据此宣称浏览器时序验收通过；Python 持久化及真实 DB/规则源也未参与。F4.20/F4.21 继续开放，场景并入最终 E2E。

## 2026-10-10 补充：F4.20 当前工作区定向复核

- **验证：**在 `components/sentinel/dashboard-prototype` 执行 `npm run test:logic:focused -- 'SETUP-LIFECYCLE|SETUP-SECRET'`，**3/3 passed**；执行 `node --test --test-name-pattern='F4.20-SETUP-LIFECYCLE|F4.20-SETUP-PAGE-RENDER' tests/i18n/catalog.test.mjs`，**1/1 passed**。
- **范围：**复核 secret 清理/分支切换/生命周期纯逻辑，以及实际 `InitializationPage` 的 open、locked、closed、failed SSR 投影。
- **边界：**SSR 不执行 React layout effect，未挂载 DOM，不能代替最终 mounted 闭窗秘密清理场景；没有运行浏览器或完整 E2E，也未访问 Python Console、数据库、Nacos 或 Consul。F4.20 继续未勾。

## 2026-10-10 补充：首启 workflow 与 Python initialization 切片复跑

- **前端命令与结果：**在 `dashboard-prototype` 执行 `npm run test:logic:focused -- 'SETUP-(COMMAND|SECRET|LIFECYCLE)'`，**13 passed**。覆盖 secret 分支清理、授权窗口终态、初始化单飞/权威确认、未知回执核查、已知拒绝后显式重提和取消/销毁边界。
- **Python 命令与结果：**在 `sentinel-console` 执行 `PYTHONPATH=src .venv/bin/pytest -q tests/test_bootstrap_initialization_api.py tests/test_bootstrap_initialization_coordinator.py tests/test_bootstrap_initialization_transaction.py tests/test_bootstrap_persistence_integration.py tests/test_first_run_http_persistence_integration.py tests/test_first_run_composition.py tests/test_first_run_deployment_configuration.py`，**32 passed**；HTTPX 输出 10 条 per-request cookie deprecation warnings。
- **边界：**两侧均为聚焦自动化证据。Python integration tests 使用本地/受控数据库与 ASGI fixtures，不证明 PostgreSQL/MySQL 真实部署、Ingress 多 worker、真实配置中心写入或跨服务浏览器 E2E。前端未运行 mounted 浏览器 secret-clear 用例或完整 E2E；未访问任何未授权服务。F4.20/F4.21/B0.2 保持未完成。

## 2026-10-11 补充：授权后的初始化 workflow 读取新鲜 bootstrap

- **缺陷：**路由 owner 先创建一次性授权和初始化两个 workflow；原 adapter 各自捕获创建时的 bootstrap snapshot。授权成功后，初始化 workflow 的首次普通读取可能继续看到旧的 `operatorAuthorized=false`，与刚确认的授权状态不一致。
- **修复：**setup identity ports 每次从共享 AuthenticationWorkflow 读取最新 resolved snapshot；强制刷新或当前事实未解析时才调用共享 `restore()`。初始化 workflow 在每个连接检查和写命令前要求 `operatorAuthorized=true`，初始化页面在相同条件满足前不渲染向导。
- **验证：**未授权时数据库/来源检查与初始化写入均零 Port 调用；一次权威授权刷新后，初始化 reader 读到新事实并可继续。`npm run test:logic:focused -- 'SETUP-'` **27 passed**；页面 SSR `F4.20-SETUP-PAGE-RENDER` **1 passed**；F4.21/setup auth/check 聚焦组 **8 passed**；typecheck、目标源码 ESLint、Prettier、diff check 通过。
- **仍未验证：**这是前端 owner/workflow 和 SSR 证据；未挂载真实浏览器，也未连接 Python、SQLite/MySQL 或 Consul。最终 IAB 和 live E2E 仍必须按全项收口后执行。

## 2026-10-11 补充：mounted 闭窗秘密清理用例补齐数据库密码

- **缺口与修正：**已有最终 `SETUP-LIFECYCLE` 浏览器用例覆盖关闭/重开后数据库用户名、Nacos 账号/密码和管理员密码被清空，但没有实际填入数据库密码。现在共享 `review()` fixture 也输入合成数据库密码；闭窗并重新开放后返回数据库步骤，明确断言密码字段为空，并把该 sentinel 纳入页面/storage 泄露断言。
- **验证：**`npm run test:logic:focused -- 'SETUP-SECRET'` **2/2 passed**；`node --check tests/e2e/initialization.e2e.test.mjs` 与 `git diff --check` 通过。未执行此浏览器 E2E（按约定留到全部实现完成后）。该文件本身不在 `format:check` 覆盖范围；直接 Prettier 检查报告历史压缩排版不符合格式，不对整文件做大规模重排。
- **边界：**新增浏览器断言尚未运行，仍需最终内置浏览器 mounted 验收；模型单测不能证明 React layout effect 时序。F4.20/F4.21 与最终 React→Python E2E 保持开放。

## 2026-10-12 补充：一次性授权结果未知时禁止重放

- **缺口与覆盖：**除“授权 POST 已成功、权威回读失败”外，补充一次性授权 POST 本身因网络结果未知而失败的路径。回归锁定：未知写入进入 `result-unknown`、提交码不进入快照、再次提交不会调用第二次授权写入；只有显式 inspection 读到 `authorized=true` 才解除未知状态。inspection 仍显示未授权时继续 fail-closed。
- **验证：**在 `dashboard-prototype` 执行 `npm run check:fast` 通过；`npm run test:http:focused -- 'BOOTSTRAP-AUTH'` **4 passed**，覆盖写入/回读之间的单飞、成功写入后的未知回读、写入本身的网络未知结果及 deployment-code wire 校验；`git diff --check` 通过。
- **边界：**该回归通过受控 Port 验证前端工作流，不证明 Python 一次性授权码原子消费、持久化/重启行为、React mounted 路由时序或最终浏览器 E2E。没有访问真实数据库、Nacos 或 Consul；F4.21 继续开放。

## 2026-10-12 补充：真实 MySQL TLS 首启 HTTP 路径复验

- **覆盖：**使用仓库的 `tools/with_disposable_e2e_dependencies.sh` 创建唯一命名、仅 loopback 暴露的 MySQL 8.4.11 与 Consul 1.21.1；仅运行 MySQL migration acceptance 中的 `test_z_full_first_run_http_path_persists_setup`。该用例经 Console ASGI HTTP 路由进行一次性 operator 授权、真实 MySQL TLS 数据库连通检查（错误密码稳定归类为 `authentication` 且不回显；有效凭证返回 `reachable`）、首次初始化与持久化、bootstrap 闭窗、操作回执恢复、`/auth/me` 仍为 `null`、重复初始化被拒绝；同时检查响应不泄露提交的凭证。
- **验证命令与结果：**从 `sentinel-console` 目录执行 `tools/with_disposable_e2e_dependencies.sh env PYTHONPATH=src .venv/bin/pytest -q tests/test_mysql_migration_acceptance.py -k test_z_full_first_run_http_path_persists_setup`，**1 passed, 19 deselected**（3.15s）。随后按脚本输出的本次精确容器名查询 `docker ps -a`，MySQL 与 Consul 均不存在，临时 TLS 文件由 wrapper 清理。另执行 setup/first-run Python 聚焦组 `PYTHONPATH=src .venv/bin/pytest -q tests/test_bootstrap_database_check_api.py tests/test_bootstrap_source_check_api.py tests/test_bootstrap_initialization_api.py tests/test_bootstrap_initialization_coordinator.py tests/test_bootstrap_initialization_transaction.py tests/test_bootstrap_persistence_integration.py tests/test_first_run_http_persistence_integration.py tests/test_first_run_composition.py tests/test_first_run_deployment_configuration.py`，**67 passed**，有 51 条 HTTPX per-request cookie deprecation warnings。Dashboard setup workflow 当前复验 `npm run test:logic:focused -- 'SETUP-'`，**27 passed**。
- **边界：**这补足了真实 MySQL/TLS 和 Python 首启 HTTP 的窄验收，不是从 React 页面发起的端到端旅程；一次性授权/表单/路由 mounted 时序、浏览器秘密清除、React→真实 Python Console 全链路仍待最终内置浏览器 E2E。没有运行完整 Dashboard E2E，没有启动 Chrome、Edge 或 CDP，也没有访问真实配置中心或持久数据库。F4.20/F4.21 不因此整体关闭。

## 2026-10-12 补充：F4.20/F4.21 setup 专属逻辑与 SSR 复验

- **验证：**在 `dashboard-prototype` 执行 `npm run test:logic:focused -- 'SETUP-|F4.20|F4.21'`，**33/33 passed**；执行 `node --test --test-name-pattern='F4.20-SETUP-CHECK-RENDER|F4.20-SETUP-PAGE-RENDER|F4.20-SETUP-FIELD-ERROR-RENDER|F4.21-BOOTSTRAP-GATE-RENDER' tests/i18n/catalog.test.mjs`，**4/4 passed**。覆盖首次初始化授权门禁、bootstrap 权威刷新/过期状态、初始化字段与秘密分支、连接检查并发/重试、命令未知结果保护，以及相应真实 React 组件 SSR 投影。
- **mounted 尝试与边界：**尝试通过独立本地 Vite 端口 `5206` 和 Codex IAB 检查真实 React mounted 行为；当前 CUA 浏览器清单为空，`createBrowserTab("iab", ...)` 返回 `Browser is not available: iab`，因此没有 mounted 证据。临时隔离 harness 已删除，本地 Vite 服务已停止。未改用 Chrome、Edge、CDP 或合成浏览器断言，也未运行完整 E2E。
- **结论：**本次没有发现可由当前逻辑/SSR 用例独立证明的新代码缺陷。离开保护的原生浏览器行为、React mounted effect 下的一次性授权码/表单秘密清理、确认后真实路由跳转，以及 React 到 Python/持久层的联调仍未验证；F4.20/F4.21 保持开放，不能据此关闭。

## 2026-10-12 补充：初始化写入前复核一次性操作员授权

- **风险与边界：**初始化 workflow 在提交入口检查了当前 bootstrap 授权快照，并在真正写入前强制刷新 bootstrap；但原逻辑刷新后只检查 `initialized` 和 `setupAvailable`，漏检 `operatorAuthorized`。若一次性操作员授权在两次读取间被撤销，仍可能把初始化写命令发送到 Port。此测试只证明前端拒绝已撤销授权，不替代 Python 服务端的授权校验/原子消费。
- **回归证据：**新增 `SETUP-AUTHORIZATION rechecks the one-use operator grant immediately before initialization`。先以已授权事实装载 workflow，再令初始化前的强制 bootstrap 刷新返回 `operatorAuthorized=false`。修复前测试失败：Port 已返回意外初始化回执（写请求已被发出）；这确认是行为缺陷而非仅补覆盖。
- **修复与验证：**强制刷新后分别处理“setup 已关闭”与“授权已撤销”；撤销授权时以 `FORBIDDEN` 拒绝且不调用 initialization Port。`npm run test:logic:focused -- 'SETUP-AUTHORIZATION|SETUP-BOOTSTRAP|SETUP-COMMAND'` **14/14 passed**；`npm run typecheck` 通过；针对两个改动文件的 `git diff --check` 通过。
- **未覆盖：**未启动浏览器、Python Console、数据库或配置中心；未运行完整 E2E。该逻辑回归不验证服务端授权撤销竞态、数据库事务或跨服务初始化行为，因此 F4.20/F4.21 仍开放。
