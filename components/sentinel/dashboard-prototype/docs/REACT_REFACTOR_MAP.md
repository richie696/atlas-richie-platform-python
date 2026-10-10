# Sentinel Dashboard React 当前职责地图

核对日期：2026-10-10。本文描述当前工作区的真实结构，不代表所有页面交互、Python Console、真实配置中心或最终 E2E 已完成。唯一任务顺序与勾选状态以[前后端现状与推进清单](../../docs/process/R-DASHBOARD-前后端现状与推进清单.md)为准；协议边界以[Dashboard 页面能力与接口设计](../../docs/Dashboard页面能力与接口设计.md)、[Console API 契约](../../docs/CONSOLE_API_CONTRACT.md)及生成的 OpenAPI 为准。

## 请求与页面装配链

```text
main.tsx
  ├─ resolveConsoleRuntimeConfiguration(mock | live, build profile)
  ├─ demo + mock：安装 MSW handlers 后再挂载 React
  ├─ createConsoleServices：一个 ConsoleTransport + authentication/session owners
  └─ AppProviders → App → lazy route owner → feature HTTP adapter → ConsoleTransport
                                             ↑ mock: MSW 拦截同一 HTTP 请求
                                             ↑ live: 请求配置的 Console API origin
```

- `main.tsx` 是唯一挂载与启动边界。运行配置非法或拦截器启动失败时显示启动失败，不渲染页面并发送请求；live mode 不装配 MSW。production `live-only` profile 拒绝 mock 配置并排除 mock handlers/worker，demo profile 才允许 mock。
- `app/providers/consoleServices.ts` 创建应用生命周期服务；`AppProviders` 装配 runtime、Console services、认证、导航和 Astryx providers。页面不得分支判断 mock/live，也不得自行 `fetch`。
- `app/router/routes.tsx` 按公共 feature 出口懒加载正式路由；各路由 owner 注入同一个 transport，再交给对应 feature HTTP adapter。`App.tsx` 负责访问状态门禁、壳和路由组合，不持有页面数据。
- feature HTTP adapter 在各自 `features/<feature>/api/` 中负责 endpoint/wire schema 校验、UTC/领域映射和最小 Port 实现。未知/畸形 wire 不以 `as Type` 绕过运行时验证。

## 目录职责

```text
src/
├── main.tsx                         # 运行配置、Mock 就绪与唯一挂载
├── App.tsx                          # Vite 兼容出口
├── app/
│   ├── App.tsx                      # 路由、权限门禁、全局壳组合
│   ├── api/                         # 身份与 mock handler 应用装配
│   ├── i18n/                        # i18next/react-i18next 与 JSON locale 资源
│   ├── providers/                   # Console services、认证与 UI provider 装配
│   ├── router/                      # URL、lazy route、route owner、导航边界
│   └── shell/                       # 顶栏、导航、banner、页脚、主布局
├── core/
│   ├── api/
│   │   ├── transport/               # HTTP 请求/取消/错误等横切边界
│   │   ├── protocol/                # Console 机器合同投影
│   │   ├── runtime/                 # mock/live 配置与拦截启动
│   │   └── mock/                    # 默认 fail-closed handlers
│   ├── session/                     # 会话相关基础适配
│   └── styles/                      # 唯一 SCSS 入口、结构 token、暗色皮肤
├── features/
│   ├── overview/                    # 总览摘要、连接、趋势、应用目录
│   ├── applications/                # 应用/实例目录与实例观察
│   ├── rules/                       # 规则工作区、草稿、版本、发布、计划
│   ├── realtime/                    # 实时观测与有界时间序列
│   ├── faults/                      # 故障时间线、筛选、证据
│   ├── system/                      # 配置源、连接、协议与审计
│   └── identity/                    # setup、登录、session、账号、角色、本人改密
└── shared/
    ├── api/                         # 跨 feature 的 Console HTTP transport 契约
    ├── model/                       # 观测/来源等确有多消费者的业务中性语义
    ├── state/                       # 读取资源与命令生命周期
    ├── presentation/                # 通用格式/投影
    ├── types/                       # 导航与共享类型
    └── ui/                          # Astryx adapter、共用反馈/表单/图表
```

Feature 内仅按真实职责创建 `api/`, `model/`, `application/`, `state/`, `presentation/`, `ui/`, `fixtures/` 等目录；UI 为函数组件与 Hooks。Feature 间只通过 `index.ts` 的明确公共出口协作，不深层导入对方私有实现。`app → core/shared/features`、`features → core/shared`、`shared → core`；core 与 shared 不反向依赖 feature。

## 正式路由与请求 owner

| 路由                | 当前正式页面/owner                 | 数据路径                                      | 尚未由此证明                             |
| ------------------- | ---------------------------------- | --------------------------------------------- | ---------------------------------------- |
| `#/overview`        | `FleetOverviewContainer`           | catalog + fleet HTTP                          | Python 真实观测、全页交互/像素矩阵       |
| `#/applications`    | `ApplicationsObservationContainer` | catalog + instance HTTP                       | 真实 Agent inventory 与进程观测          |
| `#/rules`           | `RuleConsoleContainer`             | ruleset HTTP；写命令经 feature workflow       | 真实 Nacos/Consul 持久写回与多实例生效   |
| `#/realtime`        | `RealtimeObservationContainer`     | catalog + metrics HTTP                        | 真实历史/实时采集和流恢复                |
| `#/faults`          | `IncidentObservationContainer`     | catalog + incidents/evidence HTTP             | 真实故障事件源与跨服务证据               |
| `#/system`          | `ConsoleSystemRoute`               | source registration + system observation HTTP | Python Secret、健康探测、数据库审计      |
| `#/accounts`        | `ConsoleAccountsRoute`             | identity HTTP                                 | 数据库持久化与并发保护                   |
| `#/roles`           | `ConsoleRolesRoute`                | identity HTTP                                 | 多会话角色变更真实撤权                   |
| `#/change-password` | `ConsoleOwnPasswordRoute`          | identity HTTP                                 | 真实密码存储/会话失效策略                |
| `#/login`           | `ConsoleLoginRoute`                | identity HTTP + server-confirmed session      | 生产认证限速、部署 cookie/CSRF 配置      |
| `#/setup`           | `SetupRouteOwner`                  | bootstrap/init HTTP workflow                  | 隔离数据库 schema 初始化与一次性关闭窗口 |

## Mock、live 与合同边界

- Mock 在 HTTP 边界通过 MSW 拦截；mock 与 live 共用同一个 feature HTTP adapter 和 application workflow，不注入 fixture gateway。
- production `live-only` 构建已通过产物扫描排除 mock handler/worker/旧 gateway 标记；demo 构建显式保留 mock。当前 bundle 仍有 >500 KB chunk 告警，不能靠调大阈值视为解决。
- 页面和 feature 自有 demo fixtures 仍是构造 Mock 的输入；不可直接从 UI 或正式业务 model 导入。跨 feature 的演示场景由 `app/api/` 明确组装；它只服务 Mock 请求，不可充当生产目录。
- 当前 Console OpenAPI 生成结果为 43 paths、`draft-partial`、`pending=[]`。这是机器合同生成状态，不代表业务协议已签字冻结或 Python 已实现；有界字符串同时声明标准 `maxLength` 与 Console 的 UTF-16 code-unit 扩展。
- 旧 `FixtureGateway`、同步页面出口与未挂载 gateway 雏形已从正式源代码退役；前端也不再实现 Nacos/Consul 直连/差异适配。配置中心地址、凭证、兼容 profile 和规则写回归 Python Console 所有。
- 仓库现有 `sentinel-dashboard` 是 Starlette/Jinja 的 per-process 内嵌诊断服务，不等于本 React 管理控制面的独立 Python Console；两者不可因名称相似而复用其页面需求、身份范围或 API 合同。

## 当前证据与未完成边界

近期静态前端验证见推进清单 §15.471、§15.474–§15.475：`check:fast`、OpenAPI contract check 和架构测试通过；定向 i18n 与 HTTP 结果分别记录在对应条目。这里不把分段证据合并声称为完整 milestone 或 E2E。Mock/受控 transport 结果不是 Python 或真实依赖验收。

尚未达到最终目标的内容包括：

- F4 页面级完整交互与所有状态/失败/键盘/视觉矩阵仍须对照用户功能设计逐项验收；Mock handler 对命令的持久化状态和跨页面一致性仍需核对。
- Mock scenario 仍是合成数据；需要继续保持跨页面 ID、统计、分页与下钻一致，并由 Python 权威 catalog 替代 live 数据源。
- OpenAPI 当前仍为 `draft-partial`；43 paths 和 adapter 测试不能替代逐页动作的合同冻结。
- Python Console 的独立落点、schema/迁移、初始化、安全凭据存储、身份/账号/审计、规则版本/发布/计划、观测查询与 wheel 静态资产尚未完成真实验收。
- 完整 E2E 与最终像素矩阵尚未执行，按用户决定留到全部实现任务收口后；最终页面验收使用 Codex 内置浏览器，不调用 Chrome、Edge 或 CDP。
- 不连接用户真实数据库或真实 Nacos/Consul；只有在最终验收需要且范围受控时才使用隔离、可销毁的测试资源，并记录重启/断网/冲突/撤权结果。

通用 React 目录、文件与 SCSS 约定遵循 `richie696-react-library/docs/REACT_ENGINEERING_STANDARD.md`、`REACT_CODING_STANDARD.md`、`REACT_PROJECT_SKELETON.md`；本文件只维护 Sentinel 当前落点。不要将此处事实复制成另一份并行任务清单。
