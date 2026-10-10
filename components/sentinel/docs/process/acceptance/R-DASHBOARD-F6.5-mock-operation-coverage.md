# F6.5 Console operation 到 MSW handler 全覆盖

日期：2026-10-09  
状态：F6.5 完成；F6 后续任务与 Python Console 集成仍开放

## 实现与合同

- `APP_CONSOLE_MOCK_HANDLERS` 是显式 demo app assembly 使用的 feature handler 集合；Node HTTP 测试和浏览器 demo 共用 feature-owned handler factories。Node 使用 `setupServer`，浏览器使用 `setupWorker`；handler 本身不依赖专属 Node interceptor。
- `tests/http/mockOperationCoverage.test.mjs` 从 `CONSOLE_OPERATIONS` 读取 method/path，将 OpenAPI `{parameter}` 归一化为 MSW `:parameter` 后与注册 handlers 的运行时 `info.method/info.path` 对照。新增协议 operation 如果没有对应 handler 会直接失败。
- handlers 按 Console method/path/query/body 校验请求，返回对应 wire response、canonical status 与 request/csrf headers；未匹配的 Console API 通过独立 terminal handler fail closed，不透传真实网络。

## 验证

- `npm run test:http:focused -- 'MOCK-OPERATION-COVERAGE'`：**1/1 passed**。
- `npm run test:http`：**104/104 passed**，包含每个 feature 的实际 HTTP adapter / MSW 行为、错误矩阵、请求取消和本地 loopback transport；loopback 仅绑定 `127.0.0.1`，不连接外网或生产 endpoint。
- `npm run check:fast`：exit **0**，TypeScript、Prettier、ESLint 与 Console OpenAPI 42 paths 一致性通过；新增 MJS 测试单独运行 Prettier 检查通过。
- Codex 内置浏览器打开 `http://127.0.0.1:4173/#faults`，确认 demo route 经 feature HTTP mock 加载事件 timeline。没有运行完整页面 E2E。

## 边界

本验收证明前端 Mock 注册覆盖和当前 Node/browser handler 复用路径，不证明 Python Console 有对应完整实现、部署、数据库或真实配置中心交互。Mock 状态的复位、数据筛选/分页完整性与生产模式隔离按 F6.6–F6.8 单独验收。
