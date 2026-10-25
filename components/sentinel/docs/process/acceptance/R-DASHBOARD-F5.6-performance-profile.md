# R-DASHBOARD-F5.6 包体与运行性能验收（进行中）

## 目标

验证路由、图表与低频编辑器按需加载；记录生产/演示入口静态依赖闭包和真实交互成本；检查数据列表容量、轮询/订阅的重复与释放。不通过增大 Vite warning 阈值隐藏大入口，不把 manifest 静态依赖指标等同于完整运行时网络和用户体验。

## 现有代码证据

- `src/app/router/routes.tsx` 用 `import()` 延迟加载各 feature 路由。
- Nivo line renderer 被单独延迟加载，只有图表 renderer 挂载后才加载对应 chunk。
- setup-only endpoint/schema 由 setup 路由边界延迟装载，首屏身份读取保留独立 adapter。
- 较早生产包体画像见推进清单 §15.216–§15.217、§15.299；不同源码快照不用于计算趋势。
- 基于当前构建 sourcemap 做过模块归因：React DOM **181,664 B**、Astryx Core **143,571 B**、IntlMessageFormat **94,168 B**、Zod **92,039 B**、i18next **45,048 B**，应用源码合计约 **74,528 B**。这是被当前单一入口 chunk 收录的生成字节归属，不等同于包原始体积。

## 2026-10-10 当前源码快照构建

命令：

- `npm run build`
- `npm run build:demo`

结果：

| Profile | Entry JS | Manifest static closure | Independent-file gzip | Deferred entries |
| --- | ---: | ---: | ---: | ---: |
| Production / live-only | 756,914 B | 974,919 B | 265,263 B | 41 |
| Demo / mock-enabled | 760,469 B | 978,474 B | 266,437 B | 44 |

Nivo line chunk：**333,740 B / gzip 113,480 B**，位于延迟加载图表 chunk。两种 profile 构建均成功，但入口仍触发 Vite **500 KB** chunk warning。

## 2026-10-10 当前 vendor 边界实验

将 React runtime 和 i18n runtime 提取为共享静态 chunk；不强行把 Astryx Core 或 Zod 整包提前到首屏。实验发现把 Astryx/Zod 设为全局 vendor chunk 会将路由内依赖提前拉入静态闭包，使静态资源总量增加约 **211 KB**，因此已撤销这两条分组。

最初仅给 React/i18n 增加共享 chunk 的实验仍使 `BUILD-SETUP-LAZY` 失败。回查 source map 发现应用启动时的 `createConsoleAuthentication` 从宽泛 `identity/http.ts` 入口导入 `createIdentityHttp`，该入口同时导出 setup、账号与密码 adapter/wire/contract。已增加按能力归属的 `authenticationHttp.ts`、`setupHttp.ts`、`managementHttp.ts` 三个窄入口，并让运行时装配分别依赖对应入口；生成 OpenAPI 的宽入口保留给合同导出用途。

最终方案通过 sourcemap build 验证：

| Profile | 最大 JS chunk | Manifest static closure | Independent-file gzip | Deferred entries |
| --- | ---: | ---: | ---: | ---: |
| Production / live-only | 463,990 B | 960,941 B | 261,061 B | 41 |
| Demo / mock-enabled | 467,680 B | 964,634 B | 262,231 B | 44 |

所有 emitted JS chunk 均低于 Vite 默认 **500 KiB** warning 上限，未调整 warning 阈值；Nivo line 仍为 **333,790 B / gzip 113,520 B** 的 deferred chunk。窄化 runtime HTTP 入口后，当前源码快照的 manifest 静态闭包较本轮首个画像减少约 **14 KB**，gzip 减少约 **4 KB**；这是可测的构建产物差异，不直接宣称用户感知提速。`BUILD-SETUP-LAZY` 与新的 `BUILD-CHUNKS` 均通过。

## 尚未验收

## 尚未验收

- manifest 报告只测静态 imports 的闭包。demo 会在 React mount 前动态启动 MSW；其启动期动态 chunk 不计入上表，故 demo 的真实 mount 前下载量可能更高。
- 未测浏览器网络传输、JS parse/evaluate、首屏绘制与交互延迟。
- 未测大列表容量/滚动、连续筛选、路由切换后的重复刷新，以及关闭页面/停止轮询后的资源释放。
- 未执行浏览器或完整 E2E；未因此勾选 F5.6。

## 2026-10-12 当前工作区临时构建复验

为避免覆盖工作区已有的 Console wheel web assets，本次直接使用 Vite CLI 将 live/demo
构建输出到 `/tmp/sentinel-bundle-profile.Dzq92I`，没有运行 Sites 制品准备脚本，也没有改写
仓库内的 `dist/` 或 Console 打包目录。随后用这两个独立目录运行：

```text
SENTINEL_LIVE_BUILD_DIR=/tmp/sentinel-bundle-profile.Dzq92I/live \
SENTINEL_DEMO_BUILD_DIR=/tmp/sentinel-bundle-profile.Dzq92I/demo \
npm run test:build-profiles
```

结果 **10/10 passed**。当前源码快照静态构建报告：

| Profile | Entry JS | Manifest static closure | Independent-file gzip | Deferred entries | Max JS chunk |
| --- | ---: | ---: | ---: | ---: | ---: |
| Production / live-only | 744,959 B | 962,706 B | 262,349 B | 42 | 466,115 B |
| Demo / mock-enabled | 748,812 B | 966,559 B | 263,500 B | 45 | 469,968 B |

Nivo line renderer 为 **333,743 B / gzip 113,270 B**，仍不在首屏静态闭包。最大 chunk 仍低于
Vite 默认 500 KiB 警告线；本次构建出现的 Zod PURE 注释警告未被隐藏或改阈值。以上数据只
证明当前产物的静态切分与既有 build-profile 合同，不代表 demo mount 前动态下载、浏览器
传输/解析、首屏性能或交互延迟。

以下工作仍未做，因此 F5.6 继续不勾选：没有浏览器网络/parse/paint/interaction 测量，没做
大列表与连续筛选容量测试，也没有在浏览器确认路由切换刷新、轮询/订阅停止与资源释放。
临时报告目录保留在 `/tmp/sentinel-bundle-profile.Dzq92I` 供复核，不属于仓库制品。

## 2026-10-12 实例目录单页容量样本

实例目录正式 wire 查询将 `pageSize` 限制为 **100**，响应 `items` 同样最多 **100**；React
页面把该页作为真实 `ObservedInstanceDirectory` 输入并交给 Astryx `DataTable` 渲染。新增
`tests/verification/list-capacity.test.mjs`：验证 `pageSize=100` 被 schema 接受、101 被拒，
并对 100 个不同实例 ID 执行实际 React SSR，断言完整 100 行均在输出中。定向用例 **1/1**，
`npm run test:verification-tools` **9/9 passed**，Prettier 与 `git diff --check` 通过。

本地一次 SSR 样本输出 **103,569 HTML 字符 / 34.65 ms**。这只是 Node SSR 生成成本，用于确认
最大服务端页面没有在服务端渲染阶段漏行或失控；它不是浏览器 DOM commit/paint/滚动、用户
设备性能或交互响应时限，也没有设定不可靠的跨机器时延阈值。其他列表视图、真实后端数据
规模和浏览器端渲染/连续筛选仍需最终 IAB 性能矩阵验证，F5.6 继续不勾。

## 2026-10-12 当前工作区 sourcemap 构建归因复核

为判断仍接近 Vite chunk 警告线的最大 chunk 是否值得继续拆分，本轮在新的隔离临时目录用
live/demo 两种 profile 各执行一次带 sourcemap 的 Vite 构建，再从 manifest 报告读取静态闭包，
并统计最大 JS chunk 的 sourcemap `sourcesContent`。临时产物随后删除，未触碰仓库 `dist/`、
wheel assets 或 Sites 输出。

| Profile | 初始 JS | 静态闭包 | 独立文件 gzip | Deferred | 最大 chunk |
| --- | ---: | ---: | ---: | ---: | ---: |
| Production / live-only | 745,085 B | 962,832 B | 262,470 B | 42 | 466,140 B |
| Demo / mock-enabled | 748,938 B | 966,685 B | 263,615 B | 45 | 469,993 B |

最大 chunk 的 source-map 原始模块内容主要归属为 Astryx Core **608,208 B**、Zod **约 386 KB**、
应用源码 **198,616 B**、RxJS **59,124 B** 和 React Framework **39,680 B**。这是构建后 sourcemap
中被归入该 chunk 的未压缩模块源码字节合计，不是 minified chunk 的精确可节省字节；模块共享、
压缩和 treeshaking 会改变最终体积。输出的最大 JS chunk 仍低于 Vite 默认 500 KiB 上限，未改
warning 阈值；Zod pure-annotation 警告仍原样保留。

这次归因没有找到可以仅靠 `manualChunks` 安全移走的大块：Zod runtime schema 参与正式 HTTP
响应验证，Astryx Selector 由正式页面与全局 Header 共用。强行拆 vendor 可能把路由依赖提前到
启动闭包，或改变组件加载体验；因此本轮不为满足数字而改变公共依赖边界。F5.6 仍缺浏览器真实
传输/parse/paint/interaction、mounted 列表交互容量与 React StrictMode 订阅释放证据，保持未勾。

## 2026-10-12 Codex IAB StrictMode 监控 owner 生命周期窄验

为避开本仓库现有基于 CDP 的浏览器 runner，本轮仅使用 Codex 内置浏览器，在独立
`127.0.0.1:5205` Vite 实例挂载真实 `RealtimeMonitoringProbe`、真实 `LiveMonitoringPage` 和
真实 `createRealtimeMonitor`，React 外层启用 `StrictMode`。指标 Port 使用 probe 提供的合成数据，
不是 HTTP mock/真实 Python 服务。临时 probe 页面在验收后删除，IAB tab 关闭，Vite 进程停止。

在轮询运行时捕获到 **12 次读取**、`maxActiveRequests=1`、`activeMonitorSubscriptions=2` 且
`maxMonitorSubscriptions=2`；这表明 StrictMode effect replay 后只有该页面预期的两条外部快照
订阅，没有累积重复订阅，读取没有并发重叠。点击卸载后立即捕获 `activeMonitorSubscriptions=0`
及 `mode=stopped`；再等待 **1,300 ms** 后，读取仍为 **48 → 48**、活动请求保持 **0**、订阅保持
**0**。这证明该挂载样本卸载后没有继续触发 polling，monitor owner 的页面生命周期清理有效。

**边界：**这是单次内置浏览器、合成 Port 的 mounted StrictMode 生命周期窄验，不覆盖真实 HTTP
请求/浏览器网络瀑布、实际服务响应、后台 tab 节流、长时间运行或所有路由切换组合；也不是
浏览器首屏/交互耗时基线或全量 E2E。没有发现可据此修复的生命周期缺陷，因此未改生产实现。
F5.6 仍保持开放，待后续性能矩阵补浏览器传输/交互与其他页面容量证据。

## 2026-10-12 React query Hook mounted 生命周期窄合同

新增 `dashboard-prototype/tests/verification/query-resource-mounted-lifecycle.test.mjs`，使用
React 19 官方 `act` / `createRoot` / `StrictMode` 和 test-only `happy-dom` DOM 环境挂载正式
`QueryLifecycleProbe`，它实际调用生产 `useQueryResource` 与 `useExternalSnapshot`，底层使用正式
`createQueryResource`。用例观察 StrictMode effect replay 后 listener 恰为 1、首个 pending read
已取消且 replay read 仍活动；切换 session/query 后不重复订阅、旧读取取消；root unmount 后
listener 归零、活动读取被 abort；之后释放忽略 abort 的迟到 Promise 也不能把已卸载 owner 从 idle
重新填充。没有修改生产 Hook/resource 源码，也没有使用 IAB、浏览器 E2E、Chrome、Edge 或 CDP。

定向用例 **1/1 passed**，`npm run test:verification-tools` **12/12 passed**，`npm run typecheck`
通过。该测试证明 React mounted lifecycle 在 DOM shim 下符合订阅/取消契约；不等于真实浏览器
传输、浏览器长时内存分析、路由页交互/图表容量或生产 HTTP 验收。真实浏览器网络/parse/paint/
interaction 性能、其他页面 mounted 容量仍开放，因此 F5.6 不勾选。
