# 文档中心设计与维护

文档中心服务第一次部署的运维、新接入应用的开发者、日常巡检的查看者和修改规则的管理员。目标是帮助用户完成任务并验证结果；正文不充当运行时能力、身份或协议的权威来源。

## 阅读路径与功能价值

| 路径 | 用户的问题 | 内容与可获得结果 |
| --- | --- | --- |
| 认识系统 | 功能太多，不知道从哪开始 | 功能全景、界面地图、规则与观测概念、术语表 |
| 界面详解 | 知道功能，但不知道点哪里 | 逐页逐模块的总览、应用与实例、规则、监控与故障、系统管理 |
| 首次部署 | 安装后还要准备什么 | 依赖、CLI、一次性初始化、来源与绑定、账号与权限 |
| 接入服务 | 官方 SDK 接上后为什么没有图表 | Java/Go/Rust 原生规则、Reporter、mTLS、三层验证 |
| 观察与诊断 | 指标是什么意思，空图如何排查 | 指标语义、Prometheus、加载观察、日常巡检与事件 |
| 规则治理 | 应该选什么规则、阈值多大 | 首条规则、五类规则、字段单位、压测/SLO、版本与回退 |
| 高级与参考 | 哪些是标准，兼容到哪里 | 成熟接口与项目契约分列、身份、故障与恢复、运维、问答 |

每个阶段下的文章数量不固定，但阶段顺序固定：读者总是先建立概念，再部署，再接入，最后才治理规则和查参考。

## 新手可用性契约

文档中心是给**第一次接触 Sentinel 的人**用的，不是给已经熟悉 Sentinel 的人用的。这一节是本设计的核心约束，不是可选建议。

### 旧版为什么不合格

2026-10 之前的正文只有 18 篇，每篇 250 到 870 字，全部是高密度的专业短文：每句话同时塞三到四个「不能推断」的警告。实测结果是：读者知道产品**不能**做什么，却不知道**怎么做**。具体表现为——

- schema 早就支持 `steps`（分步）、`code`（示例）、`note`（提示），18 篇里 `steps` 用了 0 次、`note` 用了 0 次、`code` 只有 3 处；
- 产品有 12 条路由、6 个系统管理标签、规则工作台的多个面板，正文一处都没提「点哪里」；
- binding、profile、enrollment、last-known-good、加载观察、成员指纹这些词反复出现，从不解释；
- 常见的坑——Java 的 `NACOS_SERVER_ADDR` 含端口而 Go 拆成两个变量、Java 用 PKCS#12 而 Go/Rust 用 PEM、规则轮询一秒才生效、三个 demo 的 `/rules` 返回格式不同——全部要靠读者自己踩。

### 现在的硬约束

1. **每篇至少含一个可执行元素**：Markdown 正文至少含操作步骤、代码块或表格之一。纯散文文章不允许存在；由 `tests/logic/documentation.test.mjs` 检查。
2. **每篇给出验证方法**：读完能知道自己做对了没有，而不是「你觉得成功了」。
3. **参考类内容用表格**：字段名、单位、取值范围、枚举编码、常见填错——这类内容用散文写必然退化成一句塞四个警告。表格使用 GitHub Flavored Markdown。
4. **风险点单独成提示**：用 Markdown 引用块承载「这个别搞错」，不要埋在段落中间。
5. **术语先定义再使用**：反复出现的词进术语表，正文第一次出现时给出简短解释。
6. **三语结构完全一致**：不只是文章数和章节数一致，而是每一节有没有操作步骤、代码块和表格都必须一致。少一条步骤就是少一步可照做的动作。逐项比对：标题层级序列、每个列表的条目数、每个表格的行列数、引用块数量、代码块数量与语言。代码块内容三语逐字一致；**Mermaid 图除外**——图内标签文字是正文，按语言翻译，图的拓扑（节点、连线、`classDef`/`class` 声明）必须逐字不变。
7. **插图三语各一套**：截图是界面，界面随语言变化。一篇插图不能跨语言复用，正文里的图路径必须指向本语言的目录，且图注与 alt 文本都要翻译。

扩写后的规模：7 组 29 篇；2026-10-24 补充协议与托管发布边界后共 135 节。

## UI 与交互

- 控制台主导航、登录页和初始化向导提供文档入口。向导指南在新窗口打开以保留当前输入。文档是公开静态内容，未初始化、未登录或依赖不可用时仍可通过文档路由阅读，不开放受保护的业务接口。
- 左侧按学习阶段组织目录，组标题下显示该阶段的一句话说明。右侧展示标题、摘要、阅读前提、学习结果、章节、代码例与前后篇。章节导航聚焦标题；外部参考明确新窗口。
- 全文搜索覆盖标题、说明、正文、提示、代码**和表格单元格**。参考类内容大多在表格里，表格不入索引会让已写明的字段值搜不到。
- 文档中心使用短路由 `#/docs`；文章通过 `#/docs?view=capacity` 深链分享，搜索通过 `q` 参数恢复。旧链接 `#/documentation` 继续解析到文档中心；新链接由应用统一生成短地址。
- 手机/窄屏将目录放到内容上方；桌面目录粘性定位；文章限宽，代码块独立横向滚动。表格横向滚动，单元格文字允许换行（字段说明常常很长）。所有样式消费已有 Sentinel token。
- 文档 locale 与界面一致；切换时保留稳定文章 ID。语言控件由 app 路由装配后注入，文档 feature 不依赖 app 内部实现。加载失败给出重试，不静默混用其他语言。

## 内容职责与事实来源

页面能力、搜索策略、导航树和正文分别由 `features/documentation/ui`、`model`、`content/tree.ts` 与 `content/<locale>/<article-id>.md` 维护。`tree.ts` 是各语言共用的稳定目录树：每个分组声明稳定 ID 和文章 ID 顺序，文章标题、摘要、阅读前提、学习结果及章节正文来自对应语言目录中的同名 Markdown 文件。这样翻译正文不会改变左侧树结构，新增或移动文章时只需同步调整树和三种语言的 Markdown 文件。正文按 locale 延迟加载，以 Markdown 渲染；原始 HTML 不启用。界面短文案归集中管理的 `messages/<locale>/documentation.json`。

| 主题 | 核对来源 |
| --- | --- |
| 首次启动 | `sentinel-console/src/atlas_richie/sentinel_console/docs/quickstart.md` 与 Console README |
| CLI 命令 | `sentinel-console/src/atlas_richie/sentinel_console/cli.py` 的 argparse 定义 |
| Java / Go / Rust | `demos/*/README.md` 与其源码中的真实默认值 |
| 语言互通范围 | `docs/protocol/SENTINEL-FLOW-RUNTIME-PROFILE-V1.md` 与 Console 的 profile 校验器 |
| 指标语义 | Metrics V2 冻结决策及当前查询/Reporter 实现 |
| 规则字段与单位 | `docs/RULE_REFERENCE.md`、`docs/Dashboard页面能力与接口设计.md` 与 Console 的 `rule_snapshots.py` 枚举 |
| 加载、回执、envelope、事件 | 现有独立版本化协议正文与实现 |
| Managed envelope 生产合同 | `../../foundation/contracts/src/atlas_richie/contracts/rules/managed_publication/v1/managed_publication.py`（相对 Sentinel 组件目录）；三字段绑定比对由 Console 的 `infrastructure/rule_set_snapshot_reader.py` 消费该合同后执行 |
| 页面入口与操作 | 当前 feature UI、HTTP adapter、后端契约 |
| 插图 | `scripts/capture-doc-figures.mjs` 抓取的 `public/docs/figures/<locale>/*.png` 与 `manifest.json` |

相对路径均以 Sentinel 组件目录为起点。现有协议套件继续主管字段和语义，文档中心只面向用户解释，不创建另一份 wire 定义。官方资料以文内外部参考补充，不能把官方 SDK 的全部能力当作当前 profile 已实现能力。

### 插图素材管线

- `scripts/capture-doc-figures.mjs` 用隔离的 Edge 实例按 locale 抓取控制台页面，产物落在 `public/docs/figures/<locale>/`，并写出 `manifest.json` 记录路径、字节数与摘要。
- 抓取时固定时钟并关闭动画：**页面顶部显示的读取时间每次都不同，不固定时钟图永远不收敛**，插图会变成随时间变化的噪点图。收敛判据是连续两次截图字节一致。
- 路由参数必须用演示场景里真实存在的 id：`env=test-env`、`app=app-one`（见 `src/app/api/mockSystemScenario.ts`）。**传错应用 id 时页面不报错，只渲染空态**，插图于是变成一张没有内容的图，还比没有更糟。
- 取景按页面定制：实时监控页的主体在折叠线以下，用 `scrollTo` 滚到进程级指标区；故障分析页用 `event` 参数预选一个事件，否则右栏只有一句「请选择一个具体事件」。
- 素材通路：`public/` → Vite 静态目录 → `dist/client/` → `package-console-assets.mjs` 拷进 Console `web/assets/`。hash 路由下相对 URL `docs/figures/...` 天然适配 `SENTINEL_CONSOLE_BASE_PATH`。
- 正文用标准 Markdown 图片语法 `![alt](路径 "图注")`；渲染层把 alt 作为无障碍名称、引号里的标题作为可见图注。**alt 描述图里能看到的内容，图注说这张图回答什么问题**，两者不共用同一句话；两者都要与截图核对过，列名、模块顺序、卡片数量都不能凭印象写。

阈值示例必须标明假设、SLO、平均 RT 与 p95 的区别以及验证方法；不按语言、CPU 核数或服务名称给出固定生产值。原生规则、managed envelope、加载、发布、执行各自说明条件，未知观测不得写成零。

**只写能证实的事**。仓库里没有权威定义的东西（例如熔断 `timeWindow` 的单位），正文必须写明「文档未给出统一定义，以实际实现为准」，而不是按惯例断言。

### 2026-10-24：envelope、发布回执与配置中心访问边界

此次检查覆盖文档中心全部中/英/日正文及本文维护说明。协议与发布正文同步三语，规则首发流程、来源登记和术语表保持一致：

- Agent Reporting Envelope V1（`atlas-richie.reporting/v1`）是 Runtime Reporter → Collector 的上报基础封装；不能因此推断其他独立版本化上报协议共用该 wire 格式。
- Managed Rule Publication Envelope V1（`atlas-richie.sentinel.managed-rule-publication/v1`）沿 Console → Nacos/Consul → Runtime 传播原生规则与发布身份；不是 Reporter 事件包。Runtime 的 managed profile 显式启用，不等于 Console 读路径不能识别并验证对象形态。
- 共享生产 codec 校验字段、协议版本、载荷结构与摘要。Console 读取方随后将 `binding_id` / `rule_kind` / `profile_id` 分别与目标 binding 的 `id` / `kind` / `profile` 比对；任一不匹配即 `RuleSetSnapshotInvalid`，不得交给错误 profile 继续语义解码，不得当作成功的空规则集。codec 本身并不接收 Console binding 对象；不要把比对执行位置误写进 codec。
- Rule Publication Receipt V1 由 Runtime 产生，Collector 持久化并经 durable outbox 交给 Console 投影。已纠正旧正文「Console 告诉 Runtime 这次发布是什么」的反向表述，并区分原生规则加载观察与托管发布回执。
- 浏览器只调用 Console API。后端 provider 适配器拥有凭证解析、配置读写与独立回读；发布并发控制、outbox 与审计留在后端。已明确「直接凭证」不意味着浏览器直接连接配置中心，术语表也不再把 Reporter 的 Collector 接口写成 Console API。

定向检查：三语结构一致、两种协议标识及方向、三字段拒绝结果、Runtime 回执方向和关键字搜索可达性。此次不修改 wire、后端行为或 UI 布局，不重跑历史完整 E2E。

验证记录：`npm run test:logic:focused -- '^DOCS:'` 7/7；`npm run check:fast`、`npm run i18n:check`、`npm run build` 均通过。内置浏览器在 `#/documentation?view=protocols` 与 `view=versions` 确认新增章节、三字段表格及发布排查步骤已经渲染。构建仅有现有 Zod 注解提示，无构建失败；不将此次文档验证当作重跑后端协议或真实发布 E2E。

## 验证范围

定向测试覆盖多语言文章身份/章节一致、**三语完整结构一致**、目录覆盖、全文搜索（含表格单元格）、空结果、**每篇至少一个可执行元素**、**表格矩形性**、**插图存在性与三语图集一致**和深链恢复；沿用类型、lint、i18n 与构建门禁。浏览器检查覆盖公开入口、文章/搜索/前后篇、语言切换与窄屏，和真实规则发布/指标接入验收分开记录。

文档中心不在视觉基线的覆盖范围内——视觉基线只覆盖总览、应用与实例、规则、实时监控、故障分析、系统管理和角色绑定七类页面。文档正文改动不会触发像素回归；页面结构改动（新增渲染能力）由类型检查和逻辑测试覆盖。

## 2026-10-25：Markdown 化后的门禁修复与第二轮扩写

### 修掉两处被 Markdown 化打断的门禁

1. **DOCS 逻辑测试从未真正执行。** `tests/logic/run.mjs` 用 esbuild 把 TS 打成 ESM 再交给 `node:test`；`yaml` 只发 CommonJS，其 `dist/compose/composer.js` 里的 `require('process')` 在 ESM 产物里落到 esbuild 的 `__require` 兜底，直接抛 `Dynamic require of "process" is not supported`。异常发生在模块加载阶段，整个 `documentation.test.mjs` 被静默跳过——**门禁显示全绿，实际一条断言都没跑**。修法是给 esbuild 加 `alias`，把 `yaml` 指向它的 browser 发行版：这既绕开了 CJS 依赖，**也正是 Vite 客户端实际解析到的那一份**（`yaml` 的 `exports` 在 browser 条件下落到 `browser/index.js`），测试与运行时分歧从此消除。
2. **`format:check` 全量失败。** 正文改成 Markdown 后，`src/features/documentation/content/**/*.md` 从未进入 Prettier 的检查范围却仍在 `src` 下，被 `format:check` 判为不合规；连同 Markdown 化前遗留的两个 TSX 文件共 78 处。

### 新增内容线

| 内容线 | 落点 |
| --- | --- |
| 逐页面功能讲解 + 截图 | 新增第 7 组「界面详解」5 篇：`screen-overview` / `screen-applications` / `screen-rules` / `screen-observation` / `screen-system` |
| 指标解读（高/低代表什么） | `metrics.md` 新增一节：三个有阈值依据的指标、四个无方向定义的指标、主机级四条指标、三步读法 |
| 规则协议结构 | `rule-fields.md` 由「两层字段名」改为「三层字段名」，补配置中心 payload 层与 Go profile 字段表 |
| 阈值与场景选型 | `rule-types.md` 新增每类规则的场景与后果；`capacity.md` 新增阈值推导、接口并发取法与分场景初始值取法 |

### 同步更正的事实错误

- 系统管理是 **7 个标签**（末位为 `settings`），原文写成六个。
- 规则 profile 是 **4 个**：`sentinel-python-v1` 支持全部五类规则且是新建绑定的默认 profile，Java/Go/Rust 只支持 Flow 子集。原文只列了后三个。
- 规则字段是**三层命名**：SDK API 层（snake_case）/ Console wire 层（camelCase）/ 配置中心 payload 层（按 profile 分叉）。原文按两层写，并断言「界面填什么写进配置中心就是什么」——这句只对 Java 与 Rust 成立。
- `ui-map.md` 补齐「哪些状态不进地址」清单：总览的搜索与分页、账号列表筛选分页、审计筛选、角色页目录筛选分页、规则的 `range`/`from`/`to` 刷新即丢失。

### 本轮验证边界

逻辑门禁新增三语结构逐项比对与插图存在性检查；插图由 `scripts/capture-doc-figures.mjs` 在隔离 Edge 中按 locale 抓取并固定时钟收敛。浏览器实测覆盖三语渲染与插图显示。未重跑真实规则发布与指标接入 E2E。
