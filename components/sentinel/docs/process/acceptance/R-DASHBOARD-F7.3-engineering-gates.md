# R-DASHBOARD-F7.3 前端工程门禁验收记录

## 目的与边界

本记录汇总 F7.3 的 non-E2E 前端工程门禁。它不替代完整浏览器 E2E、Codex IAB 最终交互、视觉像素验收或正式容量测试，也不验证真实 Python Console、数据库、Nacos/Consul 或部署环境。

## package scripts 与本轮选择

| 门禁类别 | package script | 本轮 |
| --- | --- | --- |
| 类型/格式/lint/OpenAPI | `check:fast` | 已执行 |
| Hook/副作用专项 lint | `test:lint` | 已执行 |
| 纯业务逻辑 | `test:logic` | 已执行 |
| Console HTTP 与 Mock/live loopback adapter | `test:http` | 已执行；仅既有受控 loopback 测试 |
| 源码依赖/样式/映射/feature 边界 | `test:architecture` | 已执行 |
| i18n producer/render/key/interpolation | `test:i18n-tools`、`i18n:check` | 已执行；第一次发现一个 SSR test double 缺失方法，owner 修复后整套复验通过 |
| 静态验证工具 | `verify`（`--static-only`） | 已执行 |
| verification utilities | `test:verification-tools` | 已执行；含小规模 Node SSR 100 行目录样本，不是正式容量基准 |
| live/demo 产物 | `build`、`build:demo`、`test:build-profiles` | 已执行 |
| Sites 资源/回退检查 | `test:sites` | 已执行 |
| 浏览器工具、截图/像素比较 | `test:browser-tools`、`test:visual-tools` | 未执行：本轮明确不启动浏览器、不跑像素截图 |
| 完整 Dashboard 浏览器 E2E | `test:e2e` | 未执行：按计划留到最终验收 |

## 2026-10-12 执行结果

- `npm run check:fast`：通过，约 **10.3s**；包括 `typecheck`、`format:check`、`lint`、`contract:check`。OpenAPI 检查为 **43 paths / draft-partial**。
- `npm run test:lint`：**6/6 passed**，约 **0.7s**。
- `npm run test:logic`：**348/348 passed**，约 **2.8s**。
- `npm run test:http`：**188/188 passed**，约 **3.8s**。
- `npm run test:architecture`：**25/25 passed**，约 **1.0s**。
- `npm run test:i18n-tools`：owner 修复 SSR test double 后 **45/45 passed**，约 **3.7s**。首次执行的唯一失败是 `F5.3-OWN-PASSWORD-COMMAND-FEEDBACK` fixture 缺少 `getRetryAfterMs()`；owner 补为 `getRetryAfterMs: () => 0` 后复跑全套通过。生产 UI/workflow 未在本轮修改。
- `npm run i18n:check`：通过；三语各 **1159** 条消息，**963** 个静态可枚举 key。报告的 **20** 个动态 `t()` 调用依靠 JSON 派生 TypeScript key 类型与 runtime producer tests 覆盖。
- `npm run verify`：static-only 通过，约 **10.5s**；pixel comparison 未请求。
- `npm run test:verification-tools`：**11/11 passed**，约 **3.0s**。其中 100 行 SSR 目录测量为 39.67ms，仅为工具自带 bounded sample。
- `npm run build`：通过，约 **4.9s**；live-only 输出生成。上游 Zod 两条 Rollup 注释位置 warning，不影响产物。
- `npm run build:demo`：通过，约 **5.3s**；demo 输出生成，同样有上游 Zod 注释位置 warning。
- `npm run test:build-profiles`：**10/10 passed**，约 **0.4s**。
- `npm run test:sites`：**4/4 passed**，约 **0.2s**。
- **失败闭环：**发现并复现上述 test double 缺口后，由 identity/password owner 修改专属测试 fixture；本轮随后重新执行完整 `test:i18n-tools` 并确认 **45/45 passed**。没有更改该 owner 的 Identity 页面或 catalog 测试文件。

## 尚未关闭的 F7.3 边界

- 未执行 `test:browser-tools`、`test:visual-tools`、完整 `test:e2e`；没有浏览器/IAB mounted 证据、截图比较或正式性能/容量报告。
- 未用本轮静态/构建结果证明 wheel 安装后 UI、真实 Python 后端、持久层或生产反向代理运行。
- 因此本记录仅证明列明的 non-E2E 工程门禁结果，不关闭 F7.3。
