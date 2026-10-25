# F5.6.01 Astryx locale catalogs 按需加载验收

## 目标与风险

Astryx 自带的中文、日文 ICU catalog 当前被静态导入首屏。该项只调整资源加载时机，不修改 Astryx 文案、UI primitive、locale 语义或应用 API。

| ID | 风险 | 验收证据 |
| --- | --- | --- |
| F5.6.01-R1 | 默认语言首次渲染时缺少其 Astryx 翻译 | bootstrap 在 React mount 前等待当前 locale catalog；当前 locale Provider 能解析对应 locale |
| F5.6.01-R2 | locale 切换先更新 i18next、后加载 Astryx catalog，出现短暂错误语言 | setter 在切换前 await Astryx catalog；加载失败则不改当前 locale 与本机偏好 |
| F5.6.01-R3 | 静态导入仍使非当前语言进入初始静态依赖 | production manifest 的 entry 静态依赖不包含 zh-CN / ja-JP Astryx JSON；两个 catalog 通过延迟导入保留在构建产物 |
| F5.6.01-R4 | 懒加载失败后无法重试 | failed Promise 从缓存移除；下一次加载允许重新请求 |

## 验收范围

- 自动化：真实 Vite SSR module runner 加载指定 Astryx catalog；生产构建 manifest 静态/动态依赖断言。
- 内置浏览器：仅观察本机渲染与语言切换；不启动 Chrome / Edge / CDP，不提交首次初始化。
- 非目标：本项不单独完成 F5.6；其余图表/编辑器分包、列表容量和性能测量仍需另行验收。

## 本次结果（2026-10-08）

- `changeLocale()` 先等待 Astryx catalog，再切换 i18next；应用的 locale setter 在整个转换成功后才保存本机偏好。
- `tests/i18n/catalog.test.mjs` 的真实 Vite SSR 测试覆盖选定 zh-CN 资源、en-US 内置回落、切到 ja-JP 后对应资源可用，以及失败导入允许重试；ASTRYX-I18N-LAZY 用例通过。
- `tests/build-profile.test.mjs` 的 manifest 图遍历确认 zh-CN / ja-JP JSON 可由动态依赖到达，但都不在 entry 的静态闭包中；BUILD-I18N-LAZY 通过。
- Codex 内置浏览器本机页面重载后可见完整中文 setup 首屏；未提交初始化。该首屏无语言切换控件，故本次没有声称浏览器内完成三语切换验收。没有调用 Chrome / Edge / CDP。
- 全工程 `npm run check` 退出码 **0**：Hooks **6/6**、架构 **14/14**、逻辑 **253/253**、HTTP **95/95**、浏览器工具策略 **7/7**、视觉工具 **7/7**、i18n 工具 **16/16**、验证工具 **5/5**、build profile **3/3**、Sites **4/4** 均通过。
- 最终 production manifest entry JS **830,593 B**，初始静态 closure **1,048,598 B / gzip 285,825 B**；相较 §15.83 的 **944,459 B entry JS** 少 **113,866 B（约 12.1%）**。此处比较的是 Vite manifest-linked 静态包体，不是测得的浏览器传输耗时。仍有单个 entry 超过 500 KB 的构建警告。

结论：构建分包、语言切换先加载和失败可重试的自动化契约已通过；缺真实浏览器语言切换可视验收，因此该记录为**部分完成**，不代表 F5.6 完成。
