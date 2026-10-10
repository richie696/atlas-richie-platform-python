# F5.6.02 Astryx runtime Theme provider 与首屏容量验收

日期：2026-10-08  
状态：**局部完成；F5.6 保持未完成**

## 范围

确认预构建 Astryx theme 下是否仍需在首屏挂载运行时 `Theme` provider，并记录 production/demo 初始静态闭包。不得通过调高 Vite chunk warning、只拆文件但仍同步加载或隐藏 build report 来宣称容量达标。

## 变更

- 移除 `AstryxProvider` 对 `@astryxdesign/core/theme` 的运行时 `Theme` 和 `@astryxdesign/theme-neutral/built` 对象导入；保留 Astryx 国际化 Provider、预构建 neutral theme CSS、Astryx core CSS 和 Sentinel 自有 ChartThemeProvider。
- 将固定的 `data-theme="dark"`、`data-astryx-theme="neutral"` 放在 HTML 根元素，保证预构建 CSS 首帧即可按主题属性生效，不等待 React effect。
- Sentinel 当前只有深色皮肤，没有 theme 切换 UI；所有页面的可用组件均走静态预构建主题。此实现不改变 UI 组件或业务状态，也没有创建额外兼容层。

## 验证证据

- `npm run typecheck`、`npm run build`：通过。
- 完整 `npm run check`：退出成功。Hooks 6/6、architecture 14/14、HTTP 99/99、build profiles 3/3、Sites 4/4，以及 logic、contract、browser-tool/visual/i18n/verification 等门禁全部通过。该命令**不运行 `npm run test:e2e`**。
- production entry JS：**756,914 B**；manifest 初始闭包 **974,919 B / gzip 265,049 B**。
- demo entry JS：**760,664 B**；manifest 初始闭包 **978,669 B / gzip 266,317 B**。
- 对比改动前 production **830,593 B**、demo **834,343 B**，两个入口各减少 **73,679 B**（约 8.9% / 8.8%）。两个 entry 仍大于 500 KB，构建警告保留，F5.6 不勾选。
- source map attribution 将剩余 production entry 中约 **493,944 B** 映射到 `zod/v4/core/doc.js`；这是生成后 source-map segment 的归属估算，不应解释为该源文件本身大小。接下来需审查是否采用 `zod/mini` 及其函数式校验 API，或以其它经验证的方式降低 schema runtime；不得假定简单 alias 不会改变 schema 语义。
- Codex 内置浏览器 IAB 查看了本地实时监控页：主题、shell、筛选控件、图表和指标卡均完成渲染。页面同时呈现已有 Mock 刷新失败/last-good 状态；本轮未取得该请求错误根因证据，因此不把该状态归因于主题变更，也不算实时数据功能验收。

## 浏览器与环境边界

- 只使用 Codex 内置浏览器；未启动或调用 Chrome、Edge、CDP，也未运行 E2E 浏览器脚本。
- `npm run check` 在受限沙箱第一次因两个测试无法绑定 `127.0.0.1`（`listen EPERM`）中断；随后按本机隔离测试范围重跑完整门禁通过。
- 未访问 Python Console、真实数据库、Nacos、Consul 或外部服务。没有提交、发布或更改用户账号/凭证。

## 结论

该优化移除了不需要的 Astryx runtime theme compiler 并保持当前深色 UI 的 IAB 渲染；初始 JS 减少约 74 KB。但 entry 仍超出 500 KB，剩余主要归因于 Zod full runtime。图表/编辑器实际交互 chunk 和列表容量/性能证据仍待补，**F5.6 继续未完成**。
