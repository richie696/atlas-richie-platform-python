# Dashboard F4.10 — 实时监控查询与刷新所有权

状态：**正式 React 监控路径通过 IAB 实测与全量非浏览器门禁；不等于 Python/生产采集验收。**

## 范围与所有权

- `RealtimeObservationContainer` 组装目录、URL 查询条件与单个监控 owner；页面不直接发请求。
- `createRealtimeMonitor` 独占轮询、超时/取消、同查询可信快照、授权变化及 dispose 生命周期；基于已安装 `PollingStore` 禁止轮询重叠，使用 `QueryResource` 有界读取。
- `LiveMonitoringPage` 只组合过滤控件、状态条、同窗摘要/曲线及反馈。`MonitoringStatusBar` 表明暂停只停止当前浏览器读取，不停止后台采集或流控。
- 指标响应按完整 `MetricQuery` 校验后整体替换，调度器不维护第二份点列缓存。滚动窗口每次读取都解析为实际 UTC 窗口；固定窗口不漂移。保留的 stale 数据继续带原 `query.window/asOf`。
- 查询与序列受 `MAX_OBSERVATION_POINTS = 1000` 约束；空或未接入序列不会被前端制造成零值或回放帧。

## 风险与证据

| 风险 | 证据 | 结果 |
| --- | --- | --- |
| 快速 tick 导致并发读取 | `MONITOR-POLL` logic + `PollingStore` owner | 同一 owner 只有一个活跃读取；同一查询重复 start 不创建第二个轮询 |
| 暂停仍推进窗口/保留旧 frame | Codex 内置浏览器 | 暂停 6 秒后页面状态与 UTC 窗口无变化；恢复进入定时读取并重新取得最新滚动窗口 |
| 轮询失败伪造新鲜度或无限 append | `MONITOR-STALE` logic | stale 数据保留原数据/窗口/asOf；恢复替换快照；点列长度未随轮询增长 |
| 空样本被当成零流量 | 内置浏览器 + observation logic | TPS 显示“尚未接入”/无观测点，而非 0；有效指标有独立单位、来源和覆盖信息 |
| 切查询/撤权/超时/卸载后旧响应回写 | `MONITOR-OWNER`, `MONITOR-TIMEOUT`, `MONITOR-CLEANUP` logic | abort、查询身份隔离、撤权清数据、超时、StrictMode 可取消重启和 dispose 均有断言 |
| 超长区间或过密采样造成无界点数 | `validMetricQuery`, `validMetricSeries` 与 observation logic | 窗口/步长限制每序列最多 1000 个有序点；wire 与领域层都拒绝超限/乱序/越窗数据 |

## 验证（2026-10-08）

- 完整 `npm run check` 到达并通过最后的 Sites 测试阶段。覆盖 typecheck、format、lint、Hooks lint、架构 **13/13**、逻辑 **239/239**、HTTP **83/83**、Console contract、浏览器工具、视觉工具、i18n 工具与键检查、verification 工具、production/demo build、build profile **2/2**、Sites **4/4**。
- Codex 内置浏览器（IAB）在已有本地演示会话的 `#/realtime?env=test-env&app=app-one&range=1h` 实际查看页面：环境/应用/时间窗/指标/窗口方式控件，状态条，QPS 42 req/s、p95 50 ms、TPS 未接入，以及各指标图表和点数摘要均可见。点击“暂停刷新”后，等待 6 秒再读取 AX 状态没有变化；点击“恢复并读取最新窗口”后回到“正在定时读取”，窗口与读取时间更新。
- 本轮未调用 Chrome 或 Edge。`npm run test:e2e` 未运行，因为当前脚本启动 Chrome/CDP；因此本项的渲染证据来自 IAB 人工路径和自动 logic/HTTP/静态门禁，不冒称全量浏览器 E2E。
- 生产构建通过，但仍输出初始 JS chunk 大于 500 kB 与第三方 Zod 注释警告；它们未被本项隐藏或通过调高阈值消除。

## 尚未证明的边界

IAB 使用本地 demo MSW 与合成指标，不证明 Python Console、Agent Reporter、生产指标聚合或真实 HTTP 长期轮询。活动老演示 `useRealtimeSeries` / `RealtimeChartGrid` 等源文件仍留作旧路径材料，但当前正式路由只装配 `RealtimeObservationContainer`，不导入 frame 回放；旧材料的集中退役属于 F6，不把它误报成当前页面仍在执行假回放。页面首次从旧规则路由切入时本轮曾短暂显示一次通用读取失败；重新进入同一实时路由后查询成功，未能确定这个一次性现象的根因，故记录为 UI/Mock 稳定性观察，而非真实网络断线验收。
