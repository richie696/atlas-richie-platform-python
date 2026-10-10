# R-DASHBOARD-F4.15 事件深链与失效恢复验收

日期：2026-10-08  
范围：React Dashboard 本地 demo HTTP/MSW 与 Codex 内置浏览器。不是 Python Console、生产 Reporter、真实权限服务或生产事件源验收。

## 验收结果

- [x] F4.14 验收记录覆盖事件到实例、规则版本/发布回执、实时监控的精确身份与 UTC 时间窗传递；本切片回归确认这些导航参数继续由 URL 持有。
- [x] 在故障时间线显式选中 `incident-resource-pressure` 后，将事件级别改为“警告”：URL 删除 `event` 参数，已选证据消失，结果没有自动选中第一条警告事件。
- [x] 使用 `severity=warning&category=resource` 深链展示筛选空态，同时保留全范围统计，并提示用户显式选择事件。
- [x] 打开 `event=missing-event` 深链时，详情显示对象不存在/已移除；不保留之前的证据，也不以另一个事件响应替代目标。
- [x] 自动化逻辑覆盖 partial/unavailable evidence、缺失或错误事件/关联、读取中断后 stale、权威 404 清除旧值、权限撤销清除数据与拒绝迟到响应。

## 内置浏览器证据

只使用 Codex In-app Browser，访问本机 `127.0.0.1:5183` 的 Vite demo/MSW，没有连接真实后端。

1. 无 event 的故障页先显示“请选择一个具体事件查看证据；不会自动替换为首条记录”。
2. 选择 `incident-resource-pressure` 后事件证据显示正确事件 ID 与结构化事实；切换为警告过滤后 URL 的 `event` 参数被清除，证据面板卸载，并显示 4 条警告记录中的未选择状态。
3. `severity=warning&category=resource` 返回 0 条匹配记录，页面显示筛选空状态和全范围统计文案，无事件证据残留。
4. `event=missing-event` 的直接深链返回明确的“选定对象不存在或已移除”反馈；没有显示先前事件证据或默认选择其它事件。

一次从实时监控直接切换到故障页时，页面显示泛化读取失败；刷新后正常加载。该瞬态原因未确认，记录为未解释的本地浏览器观察，不据此归因产品缺陷或声称已修复根因。

## 自动化与范围边界

- `npm run test:logic`：242/242 passed；其中 incident lifecycle 覆盖 evidence partial/unavailable、404/410 同键清理、stale 与 session 权限撤销/迟到响应。
- 上轮 `npm run check` 通过并包含 HTTP 86/86、contract/build/i18n/architecture 等门禁；本切片只更新验收文档，无运行时代码变更。
- partial transport 与权限撤销的**页面视觉态**未在 IAB 中人为注入；它们有领域/生命周期自动化和共用 `QueryView` 映射，但不宣称 IAB 已直接观察。`npm run test:e2e` 未运行，因为它使用 CDP 并启动外部浏览器。
- Python Console incident/evidence API、Reporter 生产事件流、后端授权撤销及跨服务 E2E 仍未验收。F4.15 只关闭本地前端切片，不代表最终 E2E 总目标完成。
