# F6.4.12 身份 Mock 场景归属与 handler 隔离

## 验收目标

将账号、合成登录口令、first-run local-storage 键和一次性故障配置集中到 app-owned 身份场景。Identity 与 Account Management feature 通过显式参数消费场景；每次创建的 MSW handler 集合拥有独立的临时状态，避免模块导入时创建共享可变数据。HTTP wire 和 Mock 页面行为保持不变。

## 验收矩阵

| 风险 | 验证层 | 断言 |
| --- | --- | --- |
| app 组合层依赖 feature 私有 scenario 文件/读取账号 seed | 静态架构 | 账号 seed 的唯一事实位于 `src/app/api/mockIdentityScenario.ts`；feature 不导入 app；app 不从 feature 深层读取 seed |
| Identity 与账号目录起始身份不一致 | HTTP Mock | 登录、`/auth/me` 与管理员账号列表引用同一 scenario 账号 ID/角色/用户名/状态 |
| mock handler 跨 server/test 泄漏状态 | HTTP Mock | 两次独立 factory 创建的 handler 状态相互隔离；初始化幂等操作、账号 mutation、revision 不跨 factory 泄漏 |
| 密码被保存或出现在账号响应/事件 | HTTP Mock | 登录仍接受唯一合成口令；账号创建密码不进入 seed、状态、操作历史或响应 |
| first-run probe 场景键重复 | Source assertion + IAB | E2E probe 与 handlers 消费相同 app-owned storage key/failure mode；first-run 页面仍可进入和恢复 |
| 用户路径退化 | Codex IAB | 仅内置浏览器 Mock 会话：登录、账号目录只读/管理员路径及初始化入口可正常呈现；不调用 Chrome/Edge/CDP |

## 设计与模式评估

- 所有权：app 拥有 immutable 演示事实和 Mock profile 参数；Identity/Account feature 拥有各自 handler 的请求校验、wire 响应及模拟状态转移；每个 handler factory 实例单独拥有临时 Map、revision、操作幂等记录和 fingerprint key。
- 依赖方向：app 装配将场景传给 feature mock entry；feature 只依赖其公开输入类型，不读取 app 文件。自动化测试直接导入 app scenario 并显式构造 handler。
- GoF 23 模式评估：不引入 GoF 模式。这里不需要根据运行时选择同一抽象的多个产品、装配兼容对象族或构造多阶段复杂对象；显式参数注入与闭包封装局部状态足够。handler 创建函数只是明确输入的普通构造函数，不是 Factory Method/Abstract Factory 扩展点。
- 安全：仅 synthetic local Mock；不得保存真实凭据。账号密码只在一次请求校验中使用；状态与操作历史不复制密码。

## 实施与验证记录（2026-10-08）

- **实现：**新增 app-owned `src/app/api/mockIdentityScenario.ts`，唯一持有 demo 账号、合成登录口令、setup 存储键与一次性故障值。Identity feature `mock` public entry 暴露输入契约和 handler constructors；identity/account handler 不反向导入 app。将初始化 operation map、HMAC fingerprint key、账号目录/revision/sequence/幂等 operation map 移入对应 factory 闭包；重新创建 handler 即获得独立状态。删除 feature 内旧 `identityMockScenario.ts`，规则/系统测试与 first-run probe 改为引用 app scenario。
- **自动验证：**`typecheck`、`format:check`、`lint`、Hooks lint、architecture **13/13**、logic 全套通过；HTTP **94/94**（包含身份—账号目录一致性、凭据不泄漏和 handler factory 状态隔离）；`contract:check`、demo build 通过。初次受限 HTTP 执行只有现存 controlled-loopback listener 报 `EPERM`；经授权仅对 `127.0.0.1` 开放本机测试监听后复跑通过。Demo build 仍提示约 **1.19 MB** 初始 JS chunk。
- **Codex IAB：**仅通过内置浏览器在本机 `?mode=mock` 登录合成 admin，系统管理页展示账号维护目录 `admin` 和 `viewer`，管理员操作入口可见。没有调用 Chrome、Edge、CDP；未运行 `npm run test:e2e`。该冒烟只证明页面通过 Mock HTTP 可呈现，不是完整浏览器 E2E。
- **安全/边界：**只使用合成本地演示口令；未连接 Python Console、数据库、Nacos、Consul 或 Collector，无真实认证/持久化证据；账号密码仍是写入时短暂数据，不存入 scenario 或 handler 状态。

**状态：本子切片完成；F6.4 整项仍未完成。**
