# F4.13 故障分析时间窗、筛选与分页验收

日期：2026-10-08  
状态：本地 mock + Codex 内置浏览器验收通过；真实 Python/生产事件源待后续  
范围：正式 React 故障分析路由、Console HTTP mock 与 Codex 内置浏览器；不代表 Python/生产事件源验收

## 本切片设计与风险

F4.13 已有的领域模型按 `occurredAt` UTC 半开窗口过滤、允许 `receivedAt` 晚到、稳定按时间与 ID 排序，并将全范围统计与过滤/游标页分离。本切片补齐**可分享查询所有权**：严重度、事件类别、实例身份和 opaque cursor 刷新/后退后必须从 URL 恢复，不能只暂存在 React 组件状态。实例目录只能来自现有授权 Console HTTP Port；改变环境/应用/实例/级别/类别/时间窗口必须清除 cursor 与不再匹配的事件选择。

| ID           | 风险                             | 自动/手工验证               | 关键断言                                                         |
| ------------ | -------------------------------- | --------------------------- | ---------------------------------------------------------------- |
| F4.13-NAV-01 | 筛选只留在组件状态               | 逻辑测试 + IAB              | severity/category/cursor 经 hash 往返；离页路由不泄露故障筛选    |
| F4.13-NAV-02 | 非法/超长 route 值导致不安全查询 | 逻辑测试                    | 未知 severity/category 收敛为未筛选；超长 cursor 不进入 query    |
| F4.13-NAV-03 | 实例目标跨应用/环境错配          | domain/HTTP + IAB           | 实例目录按环境/应用读取；选择实例同步 appId 与 process scope；应用变化清实例 |
| F4.13-NAV-04 | 过滤/翻页破坏时间与统计口径      | domain/HTTP + IAB           | UTC window 保留；非 cursor 筛选重置 cursor/选中事件；翻页统计不变且证据选择保留 |
| F4.13-NAV-05 | 浏览器返回/刷新状态不一致        | IAB 手工                    | instance 选择刷新恢复；severity/category 后退刷新恢复（severity/category 由上一轮已验） |
| F4.13-NAV-06 | 游标数据不足以实测下一页         | HTTP + IAB                  | mock fleet 24 条事件；20+4 游标分页、返回首页、过滤清游标实际通过 |

模式评估：无 GoF 模式适用。这里只有一个已有 feature query 的可分享筛选投影；继续由 URL、既有纯模型与现有 QueryResource 持有，不增加策略/工厂/中介者对象。

## 实施记录

- 已落地：故障路由独占 `severity`、`category` 与有界 opaque `cursor` 参数；离开故障路由时这些筛选不进入其他页面；未知枚举/超长 cursor 收敛为安全默认。内置浏览器先行验证 severity/category 的 URL、后退、刷新和统计不变。
- 实例列表复用 `applications` feature 的 Console HTTP Port；instance choice 与 `(environmentId, appId, instanceId, process)` 严格绑定。实例目录出错时只禁用实例选择并显示三语说明，其它事件筛选仍可使用。
- mock 数据为 fleet 24 条（每应用 12 条），保留 app-one 原有样例身份；HTTP 测试验证 20+4 页、完整统计跨页不变、instance-1 过滤只返回该实例事实。
- 内置浏览器实际验证：实例选择 URL 持有 app/instance/process scope，统计为 6 条且条目全属该实例；全应用切换移除 instance/scope；刷新实例深链后选择与结果恢复。第二页显示 4 条、总统计保持 24；第一页显式选择事件后翻页，event 参数及右侧 evidence 保留。第二页切换 severity 后 cursor 从 URL 删除，统计保持 24、筛选结果为 8。
- 自动验证：完整 `npm run check` 通过（logic **242/242**、HTTP **86/86**、architecture **13/13**、OpenAPI 42 paths、lint/format/i18n、production/demo build、build profiles、Sites worker）。构建仍有既存初始 JS chunk 约 1.18 MB 的 500 KB 警告。
- Chrome/Edge 与 CDP `npm run test:e2e` 按用户明确要求不启动。IAB 手工场景已完成，但这不代表 Python Console/Reporter/生产事件源真实网络验收；该部分后置。
