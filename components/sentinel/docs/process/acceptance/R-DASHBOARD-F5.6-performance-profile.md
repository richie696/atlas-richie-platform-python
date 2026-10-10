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
