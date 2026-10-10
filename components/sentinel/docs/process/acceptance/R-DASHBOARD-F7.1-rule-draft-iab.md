# F7.1 规则草稿 HTTP 工作流与内置浏览器结果核查

日期：2026-10-08  
状态：部分完成；F7.1 不勾选  
范围：本地 Dashboard demo/mock、MSW/HTTP 工作流、Codex 内置浏览器；未访问 Python Console、数据库或真实配置中心

## 结果

- **旧 IAB 会话：**修改完整流控规则阈值后，配置预览正确显示 `2100`。提交“保存完整草稿”后，页面进入“尚不能确认操作结果”状态并锁住后续写操作；只使用“检查执行结果”核查原 request key，状态仍未知。没有再次提交该写命令。该旧 tab 当前仍保留锁定状态和 `2100` 本地草稿值；根因未证实，也没有重放写命令。
- **干净 IAB 会话复测：**全新 Codex 内置浏览器 tab 连接同一本地 demo，在管理员 Mock 会话中将阈值改为 `2105`；保存后收到 `draft-revision-2`，dirty 状态清除；兼容性校验通过；固化版本 `version-3`；发布后兼容性校验、配置中心写入和回读均显示已确认成功。随后读取实例回执，页面明确显示 `0 / 2` 已生效、2 个实例待加载，实例目录来源为 `synthetic-inventory`，实例 ID / incarnation 分别为 `instance-1 / incarnation-1` 与 `instance-2 / incarnation-2`，载入版本为“未上报”。这证明干净会话的草稿→版本→发布→回执展示链路可用，不代表旧操作结果已查明。
- **隔离 HTTP 集成回归：**`RULE-MOCK` 测试在真实 `ConsoleTransport → MSW HTTP handlers → ruleSet HTTP adapter` 路径上，保存修改后的候选（阈值 `2100`），再按原 request key 查询回执，确认返回同一完整候选。进一步通过真实 `createRuleDraftWorkflow + createRuleOperation + MSW HTTP` 路径保存阈值 `2300`，收到 `completed` 草稿回执，workflow 的 dirty 状态清除，保存修订与回执一致。对应测试在 `tests/http/ruleSetMock.test.mjs`。
- **当前测试运行：**沙箱内首次 `npm run test:http` 的 `HTTP-LIVE-CONTROLLED` 因禁止绑定 `127.0.0.1`（`listen EPERM`）而失败；在明确限定为本机 loopback 的权限运行中，HTTP suite 为 **95/95**。之后完整 `npm run check` 退出码 **0**，格式、lint、类型、架构、逻辑、HTTP、契约、浏览器工具单测、视觉/i18n 检查、构建及 build-profile/Sites 检查均通过。构建有初始 JS chunk 大于 500 kB 的非阻断提示。`npm run check` 没有启动浏览器；页面验证仅通过 Codex 内置浏览器完成。
- **隔离 origin 对照：**既有 IAB 标签 `http://localhost:4173` 出现页面暂时无法显示；`127.0.0.1` 标签正常呈现规则工作台。另一个隔离的 `sentinel.localhost:4173` fresh-origin 登录页对一次合成 admin 登录显示通用失败。前两种现象仅是观察，不能据此推断 host/origin、旧 session、Service Worker 或代码缓存是根因。

## 新发布回执缺口的修复测试矩阵

| 风险                                  | 验收断言                                                                                                                                     | 层级                      |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| Mock 对已知实例清单的新发布返回空回执 | 发布完整成功后，所选应用已登记的两个实例均以 `pending` 表示；expected/inventory source 来自场景权威清单；不伪造 loaded version/checksum/time | HTTP/MSW 集成 + Codex IAB |
| 新增回执污染 seed 或其他应用          | 原预置发布的 1/2 applied/pending 不变，新发布只含目标 binding/app 的实例                                                                     | HTTP/MSW 集成             |
| UI 把 publish 接受误报为实例已生效    | 新发布回执显示 0 applied / 2 pending；配置写入/回读成功与实例载入继续分开                                                                    | Codex IAB                 |

## 结论与边界

- 工作流级 Node/MSW 集成证明同一实现的隔离 HTTP 写入、回执解析、原 request key 查询和草稿状态接受正常；干净 IAB 会话补充验证了实际页面解析与展示；**不证明**旧未知操作的最终结果，也不证明 Python Console、数据库或真实配置中心集成。
- IAB 中写操作已经变成结果未知，遵守幂等安全边界，不重放该命令。手工点击“检查执行结果”仍未确认，因此这次浏览器规则保存不能算通过。
- 页面 banner 明确为示例数据。没有请求 Python 服务、关系数据库、Nacos、Consul 或任何生产资源；没有启动 Chrome、Edge、CDP，也没有运行 `npm run test:e2e`。
- F7.1 的规则草稿/版本/发布演示在干净 IAB 会话中已通过；原旧会话的未知操作仍未确认且不重放。还需继续完成 setup、login、overview、应用与实例、实时监控、故障分析、系统管理、账号/角色、改密/注销完整流程；全程仅用 Codex IAB 做页面验证。真实 Python 后端验收仍独立未完成。
