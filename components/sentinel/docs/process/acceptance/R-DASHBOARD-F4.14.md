# R-DASHBOARD-F4.14 故障证据关联与跨页对照验收

日期：2026-10-08  
范围：React Dashboard 本地 demo HTTP/MSW 与 Codex 内置浏览器。不是 Python Console、生产 Reporter、真实指标或配置中心验收。

## 验收结果

- [x] Incident evidence 显式返回可空的 `relatedRule`：`environmentId`、`appId`、`bindingId`、`versionId`、`publicationId`。严格 wire schema 与领域谓词校验关联环境/应用必须匹配事件，publication 必须匹配事件的 publication identity，version 必须匹配有限结构化事件事实；客户端不根据文案或规则正文猜测关联。
- [x] 时间线事件仍由用户显式选中。详情分别展示发生、接收、读取时间、事件来源、发布记录标识、有限证据事实及完整度；页面声明时间相关性不是因果结论，不执行规则变更。
- [x] 当且仅当返回完整关联身份时，详情才提供规则入口。入口把 `bindingId`、`versionId`、`publicationId` 与环境、应用、事件 ID 和 UTC 窗口传至规则路由；规则页读取对应 binding、不可变 version、publication 和 receipts。
- [x] 规则 route 的 `versionId` 可直接选中版本，`publicationId` 可直接选中发布记录；刷新深链后仍恢复选中的活动版本与发布审计状态。
- [x] 指标趋势入口保留事件 ID、环境/应用/实例、scope 和精确 UTC 窗口。由事件打开的历史对照窗口为 fixed，不会随实时刷新滑动到另一个窗口。
- [x] 缺少确切目标时隐藏对应建议入口；relation 为 null 时不能声明规则视图可用。Wire/领域负例覆盖错事件、错应用、错发布身份和缺少 relation 等情况。
- [x] 事件结构化文案继续由 zh-CN/en-US/ja-JP 三语资源呈现；资源 parity 检查在全量门禁中覆盖。

## 本地内置浏览器证据

只使用 Codex In-app Browser；未启动 Chrome/Edge，也未运行会启动 CDP 浏览器的 `npm run test:e2e`。为隔离先前标签的通用读取错误，在本地 `127.0.0.1:5183` Vite 实例验证当前源码，使用合成 viewer 登录和 MSW 数据：

1. 故障时间线显示 `incident-rule-published`；显式选择后详情显示结构化规则发布事实、完整度、UTC 发生/接收/读取时间、`publication-event-flow-01`，并明确“时间相近不等于因果关系”。
2. 点击“规则工作台”进入 URL 携带 `binding=binding-app-one`、`version=version-event-flow`、`publication=publication-event-flow-01` 的规则页；对应不可变版本和发布状态被选中，页面显示配置写入/回读状态。刷新后仍选中同一版本与 publication。
3. 另选 `incident-resource-pressure` 并点击“实时监控”：URL 保留 `event=incident-resource-pressure`、`instance=instance-1`、`scope=process`、`app=app-one` 与原始 `[20:00:13.147Z,21:00:13.147Z)` 窗口；页面显示“固定历史窗口”且图表读数窗口与 URL 完全一致。

先前的 `127.0.0.1:5173` 标签在热更新后曾显示通用读取失败；原因未确认。隔离端口加载当前源码后的上述测试成功，因此不把该失败泛化为产品缺陷，也不把旧标签视作通过证据。

## 自动化验证

- `npm run typecheck`：通过。
- `npm run lint` 与 `npm run format:check`：通过。
- `npm run test:logic`：242/242 通过。
- `npm run test:http`：86/86 通过（包含隔离 `127.0.0.1` controlled endpoint；不访问外部服务）。
- `npm run contract:check`：42 paths，`draft-partial`，`pending=[]`。此状态不代表 Python Console 已实现或协议已冻结。

## 明确未验收

本记录只关闭前端功能原型的 F4.14 切片。Python incidents/evidence API、Reporter V1 到生产事件存储的投影、生产指标关联、真实规则配置源及审计 receipts 均未运行；不代表真实跨服务 E2E。F4.15、F5/F6 后端联调与总体验收仍按主清单跟进。
