# F5.2 国际化动态键与语言切换验收记录

日期：2026-10-08  
范围：动态翻译键的静态审计改进、locale-aware 数字回归、规则草稿语言切换与 URL/协议/草稿稳定性。  
结论：部分通过；F5.2 保持未完成。

## 下一切片测试设计：动态 key 编译期闭合

| 风险 | 证据 / 测试 | 通过条件 |
|---|---|---|
| 调用方把任意字符串传给 `t()`，静态扫描漏掉变量来源 | i18next `CustomTypeOptions.resources` 由英文 JSON bundle 类型组成；`ParseKeys<"translation">` 通过 shared translation contract 供展示映射使用；全工程 `typecheck` | 所有 `t()` key 必须属于实际 JSON key 联合；有效动态 producer 返回类型需收窄，不能用 `string` 或 `as` 绕过 |
| 类型声明未真正拒绝未定义 key | typecheck 纳入的负向类型 probe，使用 `@ts-expect-error` | 明确不存在的 key 必须报错；若未报错则 unused directive 使门禁失败 |
| 动态 producer 返回的某个真实 key 未进入任一语言资源或插值丢失 | `I18N-DYNAMIC-IDENTITY`、`I18N-DYNAMIC-RULE-COPY`、`I18N-DYNAMIC-PRESENTATION`、`I18N-DYNAMIC-DEPLOYMENT-PRESENTATION`；`dynamic-callsite-coverage.test.mjs` 守护 AST 未解析调用到 producer 测试 ID 的逐项映射 | 真实 producer 输出在 zh-CN/en-US/ja-JP 都能渲染；无原始 key、空译文或未解析插值；三语键/插值一致；新增/改动动态调用必须更新映射 |
| language switch 修改业务状态或 URL | IAB 页面验收 | 三语往返后业务标识、协议枚举、未保存草稿与 URL 保持原值；只在 IAB 中执行 |

设计约束：JSON 仍是唯一译文事实源；新增的 `.d.ts` 只从现有 JSON 导入类型，不复制键值；不以移除 unresolved 日志、allow-list 或 `as string` 达到表面清零。GoF 决策表已评估，无适用模式：该切片是类型边界和校验门禁，不引入对象协作/创建结构。

## 实施

- `dashboard-prototype/tests/i18n/source-keys.mjs` 静态解析本地常量别名、条件/逻辑表达式、本地有限 map，以及通过相对路径导入的有限导出翻译 map。
- `dashboard-prototype/tests/i18n/source-keys.test.mjs` 覆盖有限本地 map、别名、导入 map、枚举计算属性映射，以及未知变量调用仍被显式报告。
- `dashboard-prototype/tests/i18n/keycheck.mjs` 建立源码导出 map 索引并按导入来源解析动态调用；不将无法解析的调用静默放行。
- `dashboard-prototype/tests/logic/observation.test.mjs` 覆盖 `formatMetricReading` 在 `en-US` 与 `de-DE` 下的数字分组差异，并断言原协议数值保持不变。
- 总览应用表 QPS 格式函数现在接收当前 i18next locale，不再硬编码 `zh-CN`；实例健康状态的 fallback 标签改为 `HealthLevel` 穷尽映射，删除未受检的字符串拼键。
- 实例矩阵 QPS 格式同样改为使用当前 i18next locale；账号目录最后登录时间按 locale 格式化，但显式使用 UTC 并显示 `UTC`，不再隐式依赖浏览器所在时区。
- `tests/i18n/catalog.test.mjs` 增加真实 i18next 实例对每个 locale 的全部非复数资源键/插值渲染测试；三语复数分支仍由既有 0/1/2 实际渲染测试独立覆盖。
- `tests/logic/observation.test.mjs` 增加总览/实例 QPS locale、UTC 账号时间格式与实例状态映射的回归测试。
- 同一逻辑测试现在直接调用权限过滤后的真实导航、角色展示、应用健康标签、实例健康标签和 CPU/内存压力标签映射，并通过真实 i18next 实例在三语目录中逐一渲染，覆盖这组产生器的实际输出，而不是复制一份键清单。

## Codex 内置浏览器步骤与观察

1. 仅在本机 Vite demo profile 打开 `http://127.0.0.1:4189/#rules`，选择本地演示环境和 `binding-app-one`。
2. 创建未保存的流控草稿，将资源名临时改成 `POST /api/i18n-check`。
3. 依次切换 `English`、`简体中文`、`日本語`：界面标签与说明变化，URL 保持 `#/rules?env=test-env&app=app-one&range=1h&binding=binding-app-one`；资源名、未保存状态和配置预览内容保持，wire 枚举 `grade=1`、`strategy=0` 未改变。
4. 点击“丢弃本地修改”并确认，界面回到原始 `POST /api/orders` 示例值。没有保存草稿、发布规则或访问真实配置中心/数据库。
5. 另在本机 `http://127.0.0.1:4190/#overview` 以 synthetic viewer 打开总览，切换 `简体中文 → English → 日本語 → 简体中文`。文案与日期格式随 locale 变化，URL 查询参数与业务身份保持不变，并恢复初始中文；没有执行业务写入。当前 demo QPS 都低于千位分组阈值，故千位分隔差异由自动化 locale 测试证明，不声称在此数据下肉眼可见。
6. 在 Codex 内置浏览器打开本机 `/#applications`，切换至 English 与日本語，确认导航/页面文案和日期顺序变化；`test-env`、`app-one`、`instance-1` 等业务标识不翻译，实例上报时间继续标为 UTC。当前 QPS 样例均小于 1,000，千位分组仍由单元测试验证。

业务环境名称、资源名、规则 JSON 等由 demo 服务返回或代表业务输入的数据保持原值；不因界面语言切换而翻译。这是预期的数据/文案边界。

## 验证结果

- `npm run test:i18n-tools`：**14/14 passed**。
- `npm run test:logic`：本轮 **253/253 passed**。
- `npm run i18n:check`：zh-CN / en-US / ja-JP 各 **1,147** 个键一致；静态键检查由 **731** 增至 **917**；仍报告 **43** 个动态 `t()` 调用未解析。命令通过只说明现有三语资源和已提取键有效，不表示剩余动态调用已经覆盖。
- `npm run typecheck`、`npm run format:check`、`npm run lint`：passed。
- `git diff --check`：passed。
- 最新完整 `npm run check`：新增有限动态键运行覆盖后全门禁 **exit 0**，包括 type/lint/format、architecture **14/14**、logic **253/253**、HTTP **94/94**、contract、工具/i18n、production/demo build、build-profile **2/2** 与 Sites **4/4**。仅 browser tooling unit tests 运行，不启动 E2E/CDP。
- 页面验证仅使用 Codex 内置浏览器；没有启动 Chrome、Edge 或 CDP。临时 Vite demo 仅绑定 `127.0.0.1`，验收后已停止并关闭临时标签。

## 尚未关闭的验收项

- AST 当前仍有 **17** 个变量型调用无法枚举；它们由资源派生的 i18next key 类型在全工程 `typecheck` 中约束。新增逐项映射测试把全部调用点关联到真实 producer 三语 runtime 测试 ID，并在调用集合变化时失败。该映射和 producer 测试降低了遗漏风险，但不替代页面级 locale 切换及日期/时区场景验收。
- 穷尽三语下所有插值参数和动态选项映射，确保展示结果无原始 key、缺参数或未翻译回退。
- 对活跃页面全部日期/相对时间、DST 歧义及数字展示按界面 locale 做完整测试；实例 QPS、账号 UTC 时间及事件/规则/系统观测时间已有格式函数与回归覆盖，但仍未穷尽所有活动页面或 DST 场景。协议时间仍保持 UTC/epoch 约定，不受 locale 切换改写。
- 语言切换保留草稿与 URL 已在规则编辑器确认；其他需要持有草稿的功能和路由上下文仍需按验收矩阵检查。

以上仅为 F5.2 部分证据，不代表三语国际化全面完成、Python Console 联调或 E2E 全部通过。

## 2026-10-08 第三轮补充：观测时间的 locale 展示

- **问题与修复：**内置浏览器的故障分析页在日文界面仍将事件时间显示为原始 ISO 字符串。追踪到多个故障、规则部署及系统观测组件均直接展示 `toISOString()`。新增 `shared/presentation/utcDateTime.ts`，用 `Intl.DateTimeFormat` 按当前 UI locale 格式化，固定 UTC 并显式保留 `UTC` 标识；可访问的 `<time dateTime>` 与路由/API ISO 值仍为规范 UTC，排序与业务时间不变。
- **覆盖：**故障时间线与证据、规则版本/计划/草稿/来源读数/计划选项、系统审计/连接/协议/配置源注册与检查结果使用同一展示函数。自动逻辑测试确认 zh-CN/en-US/ja-JP 格式差异、UTC 标识与原始时间事实保持不变。
- **Codex IAB：**只在本机 demo `127.0.0.1:5192` 查看故障页。日文事件时间显示 `2026/10/08 ... UTC`；切换英文后显示 `Oct 8, 2026 ... UTC`，URL 中的 `from/to` 仍是 ISO UTC。选择事件后，详情请求出现“刷新失败/无可信观察”，因此详情数据读取未验收；本轮不以此关闭详情页流程。页面只读 Mock 示例，没有向业务服务写入。
- **浏览器约束与临时服务：**未调用或启动 Chrome、Edge、CDP；Vite 临时服务已经停止。关闭 IAB 临时标签被 Browser Use URL policy 拒绝，标签留在服务停止后的本机连接错误页面；没有绕过策略。
- **验证：**`npm run typecheck`、`npm run test:logic` **255/255** 通过；之后完整 `npm run check` 执行至末尾成功，含格式、lint、架构、HTTP/contract、工具/i18n、生产/demo 构建、build-profile 与 Sites。`i18n:check` 仍为每种语言 **1,148** 个资源键、静态可校验 **1,016** 个键，透明报告 **17** 个动态调用点；完整检查不运行产品浏览器 E2E。`git diff --check` 需在本补充落盘后重新核验。
- **边界：**F5.2 仍未勾；仍需页面矩阵覆盖各活跃页面日期/DST/草稿/URL 语言往返，并解决或验证观察详情读取失败。此证据不代表 Python Console 对接、生产配置中心访问或全部 E2E 通过。

## 2026-10-08 第二轮补充：有限 map/iteration 的动态键审计

- `source-keys.mjs` 现在能解析有限 literal 数组/对象的 `map()` 字段文案，以及有限字符串列表在 `map()` / `for...of` 中的消费；跨文件解析只采集被选中的正式翻译字段（如 `labelKey`），不会把同一对象的 `id` / 自由业务值当成文案键。
- 增加正例与拒绝用例，覆盖本地/导入的有限展示项、字符串列表、缺字段、计算字段和非 literal 保持未解析。未通过 allow-list 隐藏任何调用。
- 静态审计从 **918** 个键 / **43** 个未解析调用改善至 **941** 个键 / **22** 个未解析调用；三语仍各 **1,148** 键且资源 parity 通过。剩余调用主要涉及函数返回 key、领域校验 issue、派生角色/规则文案，不能据此声称 F5.2 完成。
- 验证：`npm run test:i18n-tools` **21/21**、`npm run test:logic` **253/253**、最终完整 `npm run check` **exit 0**（HTTP **95/95**、architecture **14/14**、Hooks **6/6**、visual tools **7/7**、i18n tools **21/21**、verification **5/5**、build profiles **3/3**、Sites **4/4**）。完整门禁中 HTTP live-controlled 测试只启动绑定 `127.0.0.1` 的临时服务；未运行 browser E2E。
- 浏览器约束：仅通过 Codex 内置浏览器检查本地 setup 页的渲染和表单可达性；该一次性初始化页没有 locale selector，因此不提交初始化，也不把它算作三语切换验收。本轮没有启动 Chrome、Edge 或 CDP；没有访问真实 Console、数据库或配置中心。
- 生产 build profile 的 entry JS **834,343 B**、manifest 初始资源 **1,052,348 B / gzip 286,924 B**；F5.6 的包体目标仍未达到。

F5.2 仍保持未完成。剩余 22 个动态调用、各业务 key producer 的三语 runtime 关联，以及活跃页面日期/时区与草稿切换矩阵，继续按原范围验收。

## 2026-10-08 第七轮补充：Codex 内置浏览器规则草稿 locale 验收

- 仅在 Codex 内置浏览器访问本机 Vite demo `http://127.0.0.1:4173/#/rules`；没有调用 Chrome、Edge 或 CDP。页面标记为示例数据，未连接 Python 后端、数据库或配置中心。
- 选择演示环境的 `binding-app-one`，从权威快照打开未保存流控草稿；临时将资源名改为 `POST /api/orders-locale-check`，然后依次切换 English、`日本語`。导航、筛选器、规则表单与说明文案均改变语言；已选择的 app/binding、hash 查询参数、资源名、未保存状态和 JSON 预览保持不变，预览中的协议字段仍为 `grade=1`、`strategy=0`、`count=2000`。
- 切回简体中文后，通过确认对话框丢弃本次临时本地编辑；确认恢复 `POST /api/orders` 和原始 JSON，未保存草稿没有写入后台或配置源。没有操作发布、活动计划或其他持久化动作。
- 观察到环境名称 `演示环境`、配置源 `Nacos · primary`、规则资源名与版本 ID 等业务数据不随界面语言翻译，符合“本地化界面文案、保留业务标识/输入值”的边界。
- 这是本轮实际 IAB 交互验证；未再次运行工程门禁。此前最新版完整 `npm run check` exit 0 记录仍见上文；本次没有代码改动。

本轮仅关闭“规则编辑器切换中英文/日文时不丢本地表单、URL 与 wire 预览”的一个场景。其他持草稿页面、完整日期/相对时间/DST 矩阵与 16 个动态调用的逐项归属仍未完成，F5.2 保持未完成。

## 2026-10-08 Codex 内置浏览器语言与路由复核

- **浏览器约束：**只使用 Codex IAB，没有调用 Chrome、Edge 或 CDP。此前已有标签 `#/realtime` 显示“页面暂时无法显示”；新建 IAB 标签打开同一 Vite demo 后，总览和实时监控页可正常加载。该差异是观察结果，尚未查明旧标签错误原因，不据此认定服务或浏览器故障已修复。
- **切换/路由：**实时监控成功显示 Mock 指标后切换 English，导航、筛选器、指标与说明文案变为英文；URL 保持 `#/realtime?app=all&range=1h`。随后进入规则页和应用页，语言选择仍为 English；再回实时监控并切回简体中文，中文标签恢复，路由查询仍保留。页面交互只读，没有发起规则或账号写操作。
- **观察边界：**页面明确标示示例数据且未连接生产服务、配置中心。English 下环境名称仍显示 `演示环境`；这来自 Mock API 的环境实体 `name`（不是界面 label），而应用名/实例名等业务实体名称按约定不翻译。规则路由本次只观察到环境选择器，未完成规则页完整加载/配置内容验收。日期按 locale 变化的完整矩阵、其他持草稿流程与草稿 URL 保留仍未完成。
- **静态复核：**`npm run i18n:check` 通过，三语各 **1,148** 键、静态解析 **1,016** 键；仍有 **16** 个动态 `t()` 调用未静态解析。此轮无代码改动，未重跑完整门禁；IAB Mock 观察不代表 Python 后端或真实配置源联调。

本次仅补充一组实时页 locale 切换及路由往返的 IAB 证据；F5.2 仍未完成。

## 当前完整前端门禁复跑

- 默认沙箱运行 `npm run check` 时，受控 HTTP 测试的本机监听被拒绝（`listen EPERM`）；获准后原样完整重跑，最终 **exit 0**。完整门禁包括 locale parity、静态 i18n key check、逻辑/HTTP、类型、格式、lint、构建、build-profile 与 Sites；没有执行 `npm run test:e2e`。
- `npm run i18n:check` 仍报告 **16** 个动态调用未被静态解析。绿色完整门禁只证明当前已提取的三语键、测试和构建通过，不代表动态调用清单、所有页面 locale/日期场景或后端 E2E 全部完成。

## 2026-10-08 第三轮补充：动态文案 producer 运行时关联

- 新增 `I18N-DYNAMIC-IDENTITY`：使用 Vite SSR module runner 加载真实账号/密码/初始化校验器、初始化与角色 presentation producer，并将其实际生成的错误/选项 key 交给真实 i18next 实例，在 zh-CN、en-US、ja-JP 下检查渲染结果。覆盖插值、角色与初始化规则来源选项；不复制 production key 集合充当业务映射。
- 新增 `I18N-DYNAMIC-RULE-COPY`：同样通过 Vite SSR 加载真实 `useRuleCopy()` Hook，在三种语言 provider 下捕获 Hook 输出，递归验证规则工作台动态文案无裸 `rules.*` key、无未替换插值。
- 最新验证：`npm run test:i18n-tools` **23/23**、`npm run test:logic` **253/253**、`npm run i18n:check` 通过；静态提取 **941** 个键，仍有 **22** 个动态调用未被静态解析。完整 `npm run check` **exit 0**，含 typecheck/format/lint、HTTP、contract、build、build-profile **3/3**、Sites **4/4** 等既有门禁。构建器保留其依赖注释与大 chunk 提示；生产 entry JS **834,343 B**，manifest 初始资源 **1,052,348 B / gzip 286,924 B**，因此 F5.6 不完成。
- 本轮是 source/runtime 自动化验证，不是浏览器验收；未启动 Chrome、Edge 或 CDP。此前 IAB setup 渲染记录仍只证明 setup 首屏，不证明本轮这些运行时 producer，也不补足 F5.2 页面切换矩阵。没有访问真实 Console、数据库或配置中心。
- **剩余：**22 个未静态解析调用仍须逐项归属并证明其 key producer；现有新增 runtime 测试覆盖 identity/setup/role 与规则工作台 Hook 的一部分，不等于 22 个调用全部闭合。活跃页面三语日期/时区、各持草稿页面与 URL 状态保持的人工 IAB 验收仍未穷尽。F5.2 继续保持未完成。

## 2026-10-08 第四轮补充：有限解构投影与动态键范围收缩

- 静态解析器增加两项受限推导：有限 map 输入中的对象解构字段（包括 `({ labelKey }) => t(labelKey)`）及对有限本地记录按动态枚举索引后读取固定文案字段（如 `const copy = COPY[kind]; t(copy.label)`）。只沿源码可见的有限数组/对象与字面文案字段推导；未知函数返回、计算字段、动态输入保持未解析。
- 正例覆盖 map 解构、本地 finite record lookup；负例覆盖动态数组来源和计算字段，确保这类调用不会被误判为可证明。
- 静态检查从 **941 / 22** 推进至 **1,015 个键 / 17 个未解析调用**；locale catalog 仍为三语各 **1,148** 键。`npm run test:i18n-tools` **26/26 passed**，`npm run i18n:check` 通过，完整 `npm run check` **exit 0**。production entry **834,343 B**、manifest 初始闭包 **1,052,348 B / gzip 286,924 B**；大 chunk 警告仍存在，F5.6 未完成。
- 这轮仅改变静态审计和测试，没有改 UI；未启动 Chrome、Edge、CDP，也未访问真实 Console/数据库/配置中心。F5.2 仍需处理余下 17 个动态调用，并完成活跃页面语言、日期/时区、草稿与 URL 保持矩阵，故继续不勾选。

## 2026-10-08 第五轮补充：导航、健康与身份反馈 producer

- 新增 `I18N-DYNAMIC-PRESENTATION`，通过 Vite SSR 加载正式的导航、实例状态、账号管理反馈和登录反馈 producer。测试遍历管理员/查看者导航、实例健康/CPU/内存状态、账号命令与权限反馈、登录可用性/会话/拒绝结果，在三语真实 i18next 实例中验证输出键存在、不会泄露 key 或未解析插值。
- `npm run test:i18n-tools` **27/27 passed**；前一轮已有的有限 map/解构解析维持静态键 **1,015**、未解析调用 **17**。完整 `npm run check` 在加入此用例后再次 **exit 0**，HTTP **95/95**、architecture **14/14**、Hooks **6/6**、i18n tools **27/27**、verification **5/5**、build profiles **3/3**、Sites **4/4**；production entry **834,343 B**、初始闭包 **1,052,348 B / gzip 286,924 B**。
- 动态调用剩余清单中，绝大部分已有真实 producer 的三语输出覆盖；`RuleCatalogPanel` 的 `detailLabel` 属于 props 输入，目前源码内没有调用方，仍需决定是否删除无消费者组件或为未来消费者建立真实调用验收。17 个静态未解析不能简单视为已闭合；页面语言切换、日期/时区和持草稿 URL 的人工 IAB 矩阵也仍待完成，故 F5.2 不勾选。
- 此轮没有 UI 变化，不需页面浏览器验证；未启动 Chrome、Edge、CDP，也未访问真实 Console/数据库/配置中心。

## 2026-10-08 第六轮补充：移除固定副标题的动态翻译 prop

- 源码搜索确认 `RuleCatalogPanel` 没有任何 import/JSX 调用方，`detailLabel` prop 也只有定义和本组件消费；实际资源中该副标题唯一文案就是 `rules.catalogDetail`。移除这个未使用的 `detailLabel` prop，让组件自己通过固定 key 翻译副标题，避免调用方错误传任意/缺失 key，也不再为固定文案保留动态翻译入口。
- 验证：`npm run test:i18n-tools` **27/27**、`npm run i18n:check`、`npm run typecheck`、`npm run lint`、`git diff --check` 均通过。静态提取由 **1,015** 增至 **1,016** 键，未解析调用由 **17** 降至 **16**。改动后完整 `npm run check` 再次 **exit 0**，含 HTTP **95/95**、logic **253/253**、production/demo build、build profiles **3/3**、Sites **4/4**。
- 此改动没有页面视觉/交互变化；未启动 Chrome、Edge、CDP，也未访问真实 Console、数据库或配置中心。F5.2 余下 16 个动态调用与页面级语言/日期/时区/草稿矩阵仍未完成。

## 2026-10-08 第八轮补充：总览三语切换 IAB 验收

- 按用户要求仅使用 Codex 内置浏览器；启动仅绑定 `127.0.0.1:5191` 的本地 Vite demo，以 mock `viewer`（合成测试口令）登录。未启动 Chrome、Edge 或 CDP，也没有连接 Python 服务、数据库或真实配置中心。
- 在总览页面观察 `简体中文 → English → 日本語 → 简体中文`：导航、页面标题、筛选器、表格/图表辅助文案与状态提示随语言切换；URL 始终保持 `#/overview?app=all&range=1h`。日期显示按 locale 改变（英文使用 `10/8/26, 1:01:06 PM` 格式，日文使用 `2026/10/08 13:01:06`），时间仍显式标注 UTC；`test-env`、`演示环境`、`app-one` 等业务标识/实体名保持原值，符合“界面文案本地化、业务数据不翻译”的约定。
- 最后恢复简体中文；无草稿、账号、规则或配置源写操作。画面已在当前验收轮次通过 IAB 捕获。
- 自动化复核：`npm run test:i18n-tools` **27/27 passed**，`npm run typecheck` 与 `git diff --check` 均通过；`npm run i18n:check` 三语各 **1,148** 键、静态检查 **1,016** 键，并仍报告 **17** 个动态 `t()` 调用未静态解析。运行时测试覆盖了当前正式的 identity/setup/role、rule-copy、navigation/instance-status/account/login feedback producer 的三语输出，但尚未建立“17 个调用逐项 → 测试场景”的可审计关联，不能宣称该动态清单全闭合。
- 本轮只关闭总览页三语切换、日期 locale、业务标识稳定及 URL 保持这一条 IAB 场景。其他页面日期/时区/DST、持草稿页面的切换矩阵，以及动态调用逐项归属仍待完成；F5.2 继续保持未完成。

## 2026-10-08 第九轮补充：资源派生的 i18next 动态键类型门禁

- 新增 `src/app/i18n/resourceKeys.ts`：将英文 9 份 JSON bundle 作为 i18next 单一 translation namespace 的类型源；`src/app/i18n/i18next.d.ts` 将其注册为 `CustomTypeOptions.resources` 并启用 `strictKeyChecks`。`src/shared/types/translation.ts` 通过 i18next 官方导出的 `ParseKeys<"translation">` 提供有限 `TranslationKey`，避免 shared 反向依赖 app，也不复制 JSON 键。
- 动态 key producer / 展示映射中的 `string` 被收窄为 `TranslationKey`，覆盖导航、状态、角色、setup、规则、故障、观测与系统管理等展示键；继续使用原生 `useTranslation().t()`，不包装替代 i18next。
- 新增 `tests/e2e/probes/I18nTranslationTypeProbe.tsx`：有效 JSON 键通过；故意不存在的 `missing.namespace.key` 由 `@ts-expect-error` 证明会被拒绝。`npm run typecheck` 通过；所有工程内 `t()` 动态 key 也必须满足资源派生的类型契约。
- `keycheck.mjs` 提示现区分 AST 枚举与 TypeScript 类型约束；AST 仍只报告它能证明的字面键，不将动态项伪称为 AST 已穷尽。producer 三语输出仍需 runtime 测试证明。
- `npm run test:i18n-tools` **27/27**、`npm run lint` 通过、`npm run test:architecture` **16/16** 通过。`npm run i18n:check`：三语各 **1,148** 键，AST 静态提取 **1,016** 个键，并列出 **17** 个 AST 不可枚举的动态调用；三语 parity 通过。完整 `npm run check` 在允许本机 loopback HTTP 测试监听后 **exit 0**，覆盖类型检查、格式、lint、架构/逻辑/HTTP/协议/工具/i18n 检查、生产与 demo 构建及构建配置测试；最终 `git diff --check` 通过。
- 无 UI 变更；此轮未调用外部浏览器或 CDP。此前规则草稿与总览 IAB 记录不变。本轮没有连接 Python Console、数据库或真实配置中心。

类型门禁已关闭“动态调用可传入任意不存在的 key”这一风险；F5.2 仍未完成：需要补齐 17 个动态调用点到 producer/runtime 用例的可审计映射，以及活跃页面日期/时区/DST、持草稿页与 URL 的语言切换矩阵。
- 本轮只运行自动化 HTTP/构建工具测试，没有启动任何浏览器，也没有运行真实页面 E2E；单独在默认沙箱中重跑 `npm run test:http` 时，99/101 通过，余下两个 loopback listener 用例因 `listen EPERM` 失败。该环境限制由上面的获准全量 `npm run check` 覆盖验证，不能据此称页面 E2E 已通过。

## 2026-10-09 补充：共享 UTC locale formatter

- 将 `formatUtcInstant` / `formatUtcDateTime` 作为共享展示入口，显式固定 UTC 时区；页面可以指定 compact/default 样式，且可避免重复添加时区标记。账号登录时间、实例目录、依赖探测和观测上下文复用同一实现。
- focused logic **2/2 passed**：覆盖 zh-CN / en-US / ja-JP、UTC 标记与不带标记投影、跨 DST 日期附近的 exact instant 不变；`npm run check:fast` 通过。
- 未运行浏览器 E2E。F5.2 仍未完成；活跃页面 locale switching 的实际显示、日期/时区/DST 表单行为、草稿和 URL 状态保持矩阵仍待最终 IAB 验收。

## 2026-10-08 第五轮补充：故障证据详情三语往返

- **复测与更正：**在新的本机 IAB origin `127.0.0.1:5194` 中重新登录合成 demo 账号，故障列表与所选 `incident-resource-pressure` 证据均成功从 Mock HTTP 读回。上一轮 `127.0.0.1:5192` 的详情读取失败没有稳定复现；现将其保留为一次性失败观察，不再作为当前阻塞。
- **语言矩阵：**在同一已选事件和已加载证据上执行简体中文 → 日本語 → English → 简体中文。发生时间、服务端接收时间、证据时间和读取时间分别按各语言格式显示，且显式标注 UTC；选中事件 `incident-resource-pressure`、业务标识、证据数量和 URL 中的 `env/app/range/from/to/event` 在切换期间保持不变，最终恢复中文。
- **范围：**这验证故障页的读取成功状态下的三语时间/标签及 URL/选择稳定性。仅使用 Codex 内置浏览器与本机 Mock demo，未调用 Chrome、Edge、CDP；未访问 Python Console、数据库、Nacos/Consul 或生产服务。Vite 已停止；临时 IAB 标签关闭被 Browser Use URL policy 拒绝，因此当前留在本机连接错误页。
- **结论：**故障详情读取子项现有一次成功三语往返验收并已更正前一轮失败结论；仍不足以关闭 F5.2。活跃页面的全面日期/DST/相对时间和持有草稿页面的 URL/状态语言矩阵仍待验。

## 2026-10-08 第十轮补充：动态调用点到真实 producer 测试逐项映射

- `tests/i18n/dynamic-callsite-coverage.test.mjs` 读取 `i18n:check` 的 AST 未解析调用清单，与 17 个文件/表达式/producer 测试 ID manifest 做精确集合比较；调用新增、删除或改写而未更新映射时测试失败，并校验每个测试 ID 确实存在于 catalog runtime suite。
- 把 RulePublicationPanel 内的发布阶段 label producer 移至 `presentation/deploymentLabels.ts`，UI 仍消费同一投影；新增 `I18N-DYNAMIC-DEPLOYMENT-PRESENTATION`，调用真实 producer 并用真实 i18next 在 zh-CN / en-US / ja-JP 检查 3 个字段标签。
- 17 个动态调用归属于实际三语 producer runtime suite：导航/实例状态/登录与账号反馈 → `I18N-DYNAMIC-PRESENTATION`；账号/密码/setup/角色/来源选项 → `I18N-DYNAMIC-IDENTITY`；规则工作台 → `I18N-DYNAMIC-RULE-COPY`；发布阶段标签 → `I18N-DYNAMIC-DEPLOYMENT-PRESENTATION`。
- 验证：`npm run test:i18n-tools` **29/29 passed**；其中动态调用点映射和四类 producer runtime suite 全过。`npm run typecheck` 通过；`i18n:check` 仍报告 **17** 个 AST 无法枚举调用（三语各 1,148 键、静态提取 1,016），这是保留的可见审计结果，不是 allow-list 清零。代码与测试变更后的完整 `npm run check` **exit 0**，最终 `git diff --check` 通过。
- 此轮将纯 presentation 投影从 UI 文件移到 feature-owned presentation 模块，无预期视觉差异；未启动浏览器，故本轮没有 IAB 像素/页面验收。F5.2 的动态 producer 映射子项已有可执行守护；页面级日期/时区/DST、其他持草稿页与 URL locale 矩阵仍未完成，F5.2 继续未勾。

## 2026-10-10 补充：身份页面重构后的动态调用归属修正

- 当前源码中的登录表单错误文案调用由 `LoginEntryPage` 迁入 `components/LoginSurface.tsx`；逐调用点 manifest 曾保留旧路径，并使 `I18N-DYNAMIC-CALLSITE-COVERAGE` 失败。现将动态调用归属更新到实际消费者 `LoginSurface`，沿用 `I18N-DYNAMIC-IDENTITY` producer suite；该 suite 从真实 `validateLoginCredentials` 生成问题，再交由真实 i18next 三语 catalog 渲染。
- `npm run test:i18n-tools` **36/36 passed**；`npm run i18n:check` 通过，三语各 **1,183** keys，静态可枚举 **1,028**，22 个未静态枚举的调用均存在精确文件/表达式/producer 测试映射。`npm run check:fast` 通过。
- 这是调用清单与 producer 映射维护，不是登录表单 mounted 浏览器校验，也不关闭其它页面语言切换/日期/草稿 URL 矩阵；未运行完整 E2E，F5.2 继续未完成。

## 2026-10-10 补充：动态调用必须绑定真实 producer 模块

- **发现：**`I18N-DYNAMIC-CALLSITE-COVERAGE` 原先验证 AST 动态调用集合与 manifest 一致，并仅断言 manifest 指定的 test ID 存在。该断言不能发现“调用点被错误地映射到一个无关但存在的 runtime suite”。
- **改进：**每项 manifest 现在同时记录源文件、`t()` 表达式、命名 runtime suite 与实际 key producer 模块。覆盖门禁按 suite 边界提取 `catalog.test.mjs` 中该测试的代码块，并要求其中显式 `ssrLoadModule()` 对应 producer；动态集合仍直接取自 `i18n:check` 输出，新增/删除/改写调用未维护 manifest 会失败。22 个当前动态调用分别指向 navigation、instance status、identity/setup validator/presentation、realtime read copy、rule copy 或 publication-label producer。
- **验证：**`npm run test:i18n-tools` **36/36 passed**；`npm run i18n:check` 显示三语各 **1,220** 条消息、**1,065** 个 AST 静态键和 **22** 个保留动态调用，parity 通过；`npm run check:fast` 通过（TypeScript、Prettier、ESLint、OpenAPI contract）。没有将动态调用移出报告、减少 manifest、或引入 allow-all。
- **边界：**该门禁证明调用点登记指向包含对应 producer module 的真实三语 runtime suite，不等于各页面组件已 mounted，也不证明动态交互视觉行为。语言切换下其他持草稿页面/URL、日期/时区/DST 的完整 Codex IAB 矩阵仍留到最终 E2E；F5.2 不勾选。本轮没有启动 Chrome、Edge、CDP，也未连接 Python Console、数据库或配置中心。

## 2026-10-12 补充：当前 locale 资源与动态调用覆盖复核

- **当前源码实测：**`npm run i18n:check` 显示 zh-CN / en-US / ja-JP 各 **1,156** 条消息、**962** 个静态可校验键和 **20** 个 AST 无法枚举的动态调用；资源 parity、插值与静态键检查通过。`I18N-DYNAMIC-CALLSITE-COVERAGE` 当前从 AST 输出取集合并逐项验证 producer runtime suite，避免历史记录中 17/22 调用数被误当作当前值。
- **验证：**`npm run test:i18n-tools -- --test-name-pattern='I18N-PLURAL|DYNAMIC-CALLSITE|LOCALE'` 实际运行 **45 passed**；覆盖 catalog 全量渲染、三语复数、动态 producer/runtime 映射；`npm run test:logic:focused -- 'LOCALE|F5\\.2'` **11 passed**，覆盖 UTC/DST、数字格式、业务观测值稳定及 schedule locale 投影。
- **边界：**本轮未改动 UI，也未启动浏览器；自动化测试不证明每个活跃页面的 mounted 语言切换、页面草稿/URL/session 稳定性或视觉排版。相关 IAB 页面矩阵按计划留最终验收，F5.2 继续未完成。

## 2026-10-12 补充：当前工作树最终自动化复验与挂载态余项

- **当前资源事实：**在本轮工作树执行 `npm run i18n:check`，zh-CN / en-US / ja-JP 各 **1,156** 条消息，**962** 个 AST 静态键通过；剩余 **20** 个无法由 AST 枚举的动态 `t()` 调用仍明确列出。动态调用有 JSON 派生的 TypeScript key 限制，并由 `I18N-DYNAMIC-CALLSITE-COVERAGE` 逐项关联到实际 producer runtime suite；不能把 AST 不可枚举描述成静态键已解析，也不能视为无运行覆盖。
- **资源与 producer 自动化：**`npm run test:i18n-tools` **45/45 passed**。实际覆盖三语 JSON key/插值 parity、完整 catalog 渲染、plural 0/1/many 分支、20 个调用点到 producer 测试的映射，以及 identity/setup/role、规则文案、发布字段、导航/状态/反馈等 producer 的真实三语输出。`npm run i18n:audit -- --summary` 为 **0 view / 0 model 命中**。
- **Intl 与 locale 状态：**`npm run test:logic:focused -- 'LOCALE|F5\\.2|SCHEDULE-LOCALE|Intl number|UTC formatting|chart timestamp'` **4/4 passed**；`npm run test:logic:focused -- 'I18N-|F5\\.2|SCHEDULE'` **10/10 passed**。两组都在默认宿主时区执行；再以 `env TZ=America/Los_Angeles` 重跑第一条命令，**4/4 passed**。用例覆盖三语数字呈现且 wire 数值不变、UTC instant 在宿主时区跨日期边界仍稳定、图表缺省时区为 UTC、规则排期重复 DST 时刻的 occurrence 值/协议时间保持稳定，以及 locale switch 并发、失败和恢复语义。以上为 Node/纯逻辑证据，不证明浏览器 ICU 一致性或页面挂载行为。
- **静态工程门禁：**`npm run typecheck`、`npm run format:check` 均通过。源码检索确认产品日期显示均经共享 UTC formatter，图表日期标签显式采用传入时区或默认 `UTC`；`ruleActivation` 的 `Intl.DateTimeFormat` 用于固定 `en-US` Gregorian/Latin 数字的规则输入解析，不用于本地化 UI 文案。
- **本轮边界：**没有改动产品源码或翻译 JSON；没有运行完整 E2E、Chrome、Edge、CDP，也没有访问 Python Console、数据库或配置中心。主推进清单由任务协调者维护，本记录不替代勾选。
- **仍须最终 Codex IAB 挂载验收的场景：**(1) 登录凭证草稿及偏好切换（§15.903）；(2) 初始化数据库连接字段与管理员敏感密码草稿（§15.805）；(3) 账号创建对话框和角色变更草稿/回读，含刷新后草稿恢复（§15.804 与本轮 F4.29 记录）；(4) 本人改密敏感字段（§15.807）；(5) 配置源登记草稿（§15.586）；(6) 规则排期 DST occurrence、发布理由、取消理由草稿（§15.845–§15.847），以及已保存规则草稿/URL/wire 状态（§15.358）的当前挂载实现。每项须在语言往返后检查页面仍有正确草稿/owner、URL 和协议值不变、无意外写操作；该清单留待最终 IAB E2E 节点一次性执行，不在本轮抢跑完整 E2E。
- **结论：**本轮收口了可自动化复验的 F5.2 静态资源、动态 producer 与 Intl/locale 逻辑切片；F5.2 整项仍不勾，原因是上述挂载态场景尚未运行，而非上述自动化失败。

## 2026-10-12 F5.2 当前工作树窄门禁复验

- **Catalog / dynamic producer：**`npm run test:i18n-tools` **45/45 passed**，重新覆盖三语资源键、插值占位符与 plural 分支，完整 catalog 的真实 i18next 渲染，以及当前 20 个 AST 动态 `t()` 调用到对应实际 producer runtime suite 的一一映射。`npm run i18n:check` 通过，三语各 **1,156** 条消息、**962** 个静态键，20 个动态调用仍明示并由 producer 测试覆盖；没有用放宽 AST 或隐藏调用清单来制造绿色结果。
- **Locale / Intl：**默认宿主时区下 `npm run test:logic:focused -- 'LOCALE|F5\\.2|SCHEDULE-LOCALE|Intl number|UTC formatting|chart timestamp'` **4/4 passed**；在 `TZ=America/Los_Angeles` 下同一聚焦集合也 **4/4 passed**。另运行 `npm run test:logic:focused -- 'I18N-|F5\\.2|SCHEDULE'`，**10/10 passed**，覆盖三语数值分组/精度、UTC 日期边界、图表 UTC 标签、规则排期 DST occurrence、locale 切换并发/失败/恢复及未保存计划字段边界；协议 timestamp/wire 值保持断言通过。
- **静态审计/工程门禁：**`npm run i18n:audit -- --summary` 报告 view **0** / model **0**；`npm run typecheck` 与 `npm run format:check` 均通过。
- **边界：**本轮只运行了 i18n/Intl 自动化和静态门禁；未改产品源码、翻译资源或协议值，未运行页面 E2E，也未启动浏览器。自动测试不替代最终 Codex IAB 挂载态矩阵：登录凭证、初始化敏感字段、账号创建/角色草稿、本人改密、来源登记和规则发布/取消/排期草稿在语言往返后的 DOM、URL、wire 值与无意外写入，仍待最终验收。F5.2 整项不因此关闭。
