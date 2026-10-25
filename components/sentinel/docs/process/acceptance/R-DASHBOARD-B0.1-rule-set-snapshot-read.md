# B0.1 规则权威快照读取 API 首切片验收

日期：2026-10-09  
状态：**Consul/Nacos 规则读取适配器已接入；新 Console 的 React live 页已通过内置浏览器定向复验**

## 实现

- 依据 `readRuleSetSnapshot` 合同增加 `GET /api/v1/rulesets/{bindingId}/snapshot`。
- 以 frozen/slots dataclass 和有限 `IntEnum` 建模 Sentinel 五类完整规则值；包括阈值编码、正/非负有限数、warm-up/排队、cluster window、熔断阈值、系统禁用标记、authority caller 去重、参数例外去重与 100 项上限。
- Snapshot 固定绑定身份、nullable version/source revision、checksum、UTC aware `asOf` 和最多 1,000 条完整规则；record ID 唯一，规则 kind 必须与绑定 kind 相同。
- 只读 `RuleSetSnapshotReader` Port 与 `ReadRuleSetSnapshot` 用例校验精确 bindingId。Route 负责 session、路径输入与稳定错误映射；缺少 authority 时返回 503，不伪造空快照。
- Serializer 将内部 typed DTO 映射为 OpenAPI camelCase 五类联合结构，不包含凭证或原始 provider connection options。

## 验证

- Snapshot/绑定目录及 Incident timeline、Fleet overview 定向 API 套件 **32 passed**。包括 admin/view、匿名/Session authority 故障、五类规则序列化、binding mismatch、规则类别/数量/重复 identity/毫秒精度不变量、invalid input 与 404/429/503。
- Console 源码/测试 `compileall`、新增及相关 Python 文件 88 列检查、React `npm run contract:check`（42 paths）、`git diff --check` 均通过。

## 边界

该切片不包含草稿、版本、候选校验/发布命令，也不执行完整浏览器 E2E；后者保留到里程碑。

## 2026-10-15：生产读取适配器与 Consul 定向验收

- 新增 `RegisteredRuleSetSnapshotReader`，从 SQL binding 与 publication target 读取精确目标，再通过已登记凭证解析器和部署允许的 provider target policy 读取规则；为 Consul/Nacos 复用已有只读 provider reader，不改变已冻结 HTTP 合同。
- 空目标返回带确定性 checksum 的空快照；已有目标严格解析为绑定规则类型的完整原生数组。显式 managed binding 解包已冻结的 managed publication envelope，并校验 binding、rule kind、profile。无效数据、目标不一致或权威源不可用统一 fail closed，不回退到其他 binding，也不泄漏原始配置。
- First-run SQL composition 在配置了规则发布 provider 时自动装配 reader；也保留显式注入端口。候选规则解析复用同一严格 value codec，避免读取与写入验证出现两套语义。
- 定向回归：**77 passed, 6 skipped**，覆盖 snapshot reader/API、候选校验/diff、first-run composition、Consul/Nacos reader 与发布 worker；`ruff --select F,I` 与 `git diff --check` 通过。
- 临时 Consul 1.21.1：验证精确 key 不存在时生成空快照；对隔离验收 key 写入单条合成原生规则后读回 **1 条**，取得 provider `ModifyIndex` 与 checksum；随后删除该 key 并确认 404。未使用生产配置源。
- 使用同一真实 Consul provider reader，经 ASGI snapshot route 请求，得到 **HTTP 200**、`records=[]`、`sourceRevision=null` 的空快照。
- 内置浏览器中的既有 Console 进程仍显示“规则数据读取失败”。该进程启动早于本次改动，未自动加载新组合；本轮未重启由 disposable wrapper 管理的 Console，以免中断会负责清理临时 MySQL/Consul 的验收进程。因此 **React→当前运行 Console 的 mounted live 页面复验仍未通过/未完成**；不能据 ASGI/provider 验收宣称浏览器闭环完成。后续需在受控重启或新的隔离运行实例加载此代码后，于 Codex IAB 重试同一 binding。

## 2026-10-15：更新 Console live 页与观测空态定向复验

- 在隔离当前代码 Console（8212）和 live-only React 构建（5204）上，用 Codex 内置浏览器复验相同 Consul binding。规则页读到精确 binding/target；权威快照为空时显示空规则事实并保留草稿、版本、发布与计划工作区，不出现指标读取错误。
- 系统页独立显示连接探测和登记配置中心；应用页、实时监控页、故障页保留自身筛选和内容。实时监控无当前窗口样本时显示陈旧质量、破折号和空图，不伪造零值；故障页呈现权威空事件集。
- 概览和实时监控的读取状态提示现位于标题下方；失败时仍保留六张指标卡与六个空图表。当前 live Console 的 Fleet overview 请求实际返回 **503**，因此页面诚实显示一次读取失败，而没有把未实现/不可用的后端伪装成“成功但无数据”。FleetOverviewReader composition 仍需后续实现。
- 环境筛选器由 `GET /api/v1/observation/catalog` 提供；SQL reader 从未撤销、epoch 已建立且收到 Metrics V2 Reporter 上报的绑定投影环境/应用。它不是 Nacos/Consul 的配置项。规则页环境则来自独立 rule-binding-scope API。
- **验证：**TypeScript、定向 Prettier、live-only production build、概览挂载空态测试通过。实时监控挂载测试约 64 秒仍未完成并被中止，未记为通过。内置浏览器确认页面行为；未调用 Chrome/Edge。
- **边界/进度：**仅关闭规则权威快照 React→live 定向复验和观测空态布局切片；FleetOverviewReader、完整 T07.1 页面/权限/凭证/发布回执矩阵及 T00.3/T07.2 仍未完成。阶段 **M7**；已完成 **19/22**；未完成：**T00.3、T07.1、T07.2**。
