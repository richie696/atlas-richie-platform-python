/**
 * 规则工作台的文案。
 *
 * 中文
 * ----
 * 归属本 feature：改规则页的一个词只动这里，不进任何共享文案包
 * （`docs/PRE_CODING_REVIEW.md` 第 2 问）。
 *
 * 键以 `rules.` 前缀，避免与其他 feature 撞名——`buildDictionary` 在组装期对重复键
 * 抛错，那是刻意的：键名冲突说明消息归属没定清楚。
 *
 * ## 搬自 `ruleI18n.ts` 的 `rules.*` / `types.*` / `fields.*` / `options.*`
 *
 * 旧包是嵌套对象，键路径直接来自结构（`rules.fields.resourceName.label`）。
 * 新基座是**扁平**字典，所以：
 *
 * - 旧包本来就以 `rules.` 开头的标量键（`rules.eyebrow`、`rules.errors.*`）**保持原名**，
 *   调用点、`RULE_CATALOG_HEADERS`、`RuleIssueKey` 三处键常量一个字都不用改；
 * - 旧包里没有 `rules.` 前缀的三段（`types` / `fields` / `options`）在这里补上前缀，
 *   归属才说得清——它们本来就是规则页的文案，只是当年塞进了共享包。
 *
 * ## 译文取值：以迁移前**实际渲染文本**为准
 *
 * 旧包里所有值都经 `t()` 渲染成界面文本，所以它们本身就是权威值，本文件逐字照搬。
 * 视觉基线 `tests/visual` 捕获的 `rules.html` 用来复核，换行、空白与单位都不改动。
 *
 * ## `options.*` 的下标键是**语义**名，不是 0/1/2
 *
 * 旧包用数组下标与协议值配对（`localizedOptions` 会在长度不匹配时抛错）。扁平字典装不下
 * 数组，于是用语义名（`rules.options.flowGrade.qps`）。配对顺序由 `useRuleCopy` 里的
 * 键清单固定，`localizedOptions` 的长度校验仍然成立。
 *
 * ## 措辞不同的概念不合并
 *
 * 同页里 `realtime.metric.blocked`（下拉「拦截率」）与 `realtime.chart.blocked`
 * （图表「请求拦截率」）是两次措辞不同的表达，看起来像同一个概念的两个键，但合并后
 * 切语言时会有一处措辞漂移，而这种差异没有任何测试能发现。本页同理：看起来相近的
 * 键只要措辞不同就分开写。
 */
import type { LocaleBundle } from "../../../core/i18n/types";

export const RULES_COPY = {
  "zh-CN": {
    // ── 页头 ──
    "rules.eyebrow": "POLICY / RULES",
    "rules.title": "规则工作台",
    "rules.description": "用五类 Sentinel 规则字段配置保护策略；每次编辑都预览完整配置快照。",
    "rules.sourceOfTruth": "配置中心是唯一规则事实源",
    "rules.headline": "五类 Sentinel 兼容规则 · 配置中心是唯一规则事实源",
    "rules.headlineDetail":
      "原型以 FlowRule、DegradeRule、SystemRule、AuthorityRule、ParamFlowRule 的字段组织表单。",
    "rules.editSample": "编辑示例草稿",

    // ── 规则清单 ──
    "rules.catalog": "规则清单",
    "rules.catalogDetail": "{count} 条示例规则 · 按来源与版本追踪",
    "rules.search": "搜索资源或策略",
    "rules.noMatchingRule": "没有匹配当前筛选条件的规则",
    "rules.allTypes": "全部类型",
    "rules.resourceAndType": "资源 / 类型",
    "rules.policy": "策略",
    "rules.threshold": "阈值",
    "rules.source": "来源",
    "rules.status": "状态",
    "rules.active": "生效中",

    // ── 检视器 ──
    "rules.details": "规则详情与兼容格式",
    "rules.draft": "规则草稿 · 本地模拟",
    "rules.detailDescription": "所选规则的配置来源与生效边界",
    "rules.draftDescription": "草稿不会写入 Nacos 或 Consul",
    "rules.resource": "规则资源",
    "rules.provider": "配置中心",
    "rules.baseline": "基准版本",
    "rules.scope": "生效范围",
    "rules.compatibilityType": "兼容规则类型",
    "rules.scopeExample": "{scope} · 生效情况为示例",
    "rules.configuration": "{type}配置",
    "rules.editDraft": "编辑草稿",
    "rules.configPreview": "配置中心内容预览",
    "rules.jsonArray": "{name} · JSON 数组",
    "rules.validate": "校验草稿（不发布）",
    "rules.validationPassed":
      "Sentinel 兼容字段校验通过；生产发布还需校验基准版本、生成完整快照差异、写回配置中心并确认实例生效。",
    "rules.notProduction":
      "原型只校验本地草稿；真实发布必须将完整规则集写回 Nacos 或 Consul、回读并确认实例实际加载。",

    // ── 表单动作与说明 ──
    "rules.addException": "添加例外值",
    "rules.remove": "移除",
    "rules.systemDisabled": "留空会序列化为 -1，即 Sentinel 的不生效语义。",
    "rules.paramCompatibility":
      "classType / object 是 Sentinel Java 格式中的参数例外表达；跨语言运行时必须由目标 codec 明确验证，不能把它误认为通用类型系统。",

    // ── 校验问题（键与 `rulePolicy` 的 `RuleIssueKey` 一一对应）──
    "rules.errors.resourceRequired": "资源名称不能为空。",
    "rules.errors.countPositive": "阈值必须大于 0。",
    "rules.errors.referenceRequired": "链路或关联策略必须提供关联资源。",
    "rules.errors.degradePositive": "熔断阈值与熔断时长必须大于 0。",
    "rules.errors.slowRatio": "慢调用比例必须在 0 到 1 之间。",
    "rules.errors.parameterIndex": "参数索引必须是大于等于 0 的整数。",
    "rules.errors.originsRequired": "调用来源列表至少需要一个来源。",
    "rules.errors.systemEnabled": "至少启用一项系统保护阈值。",

    // ── 筛选条 ──
    "rules.filters.environment": "环境",
    "rules.filters.production": "生产环境 (PROD)",
    "rules.filters.application": "应用",
    "rules.filters.allApplications": "全部应用",
    "rules.filters.sample": "示例采样 · 14:32:18",

    // ── 生效范围（键是 `RULE_SCOPE` 的协议值）──
    "rules.scopes.application": "应用",
    "rules.scopes.resource": "资源",

    // ── 版本与生效计划 ──
    "rules.versions.title": "版本与生效计划",
    "rules.versions.subtitle": "完整规则集快照；活动结束后回退到指定日常版本",
    "rules.versions.active": "当前生效",
    "rules.versions.scheduled": "已计划",
    "rules.versions.superseded": "已归档",
    "rules.versions.publishedAt": "发布时间",
    "rules.versions.effectiveWindow": "生效窗口",
    "rules.versions.returnTo": "结束后回退",
    "rules.versions.plannedWindow": "计划窗口",
    "rules.versions.noEnd": "持续生效",
    "rules.versions.timeZone": "Asia/Shanghai",
    "rules.versions.createVersion": "查看版本固化说明（演示）",
    "rules.versions.immutable": "版本一经创建不可修改；如需调整，基于该版本新建草稿。",
    "rules.versions.previewOnly":
      "原型不会创建版本或调度任务；正式流程先校验草稿，再固化不可变快照。",

    // ── 五类规则 ──
    "rules.types.flow.label": "流量控制",
    "rules.types.flow.description": "按 QPS、并发、调用链或关联资源控制入口流量。",
    "rules.types.degrade.label": "熔断降级",
    "rules.types.degrade.description": "按慢调用、异常比例或异常数保护下游依赖。",
    "rules.types.system.label": "系统保护",
    "rules.types.system.description": "以应用整体的入口 QPS、线程、RT、Load 或 CPU 为边界。",
    "rules.types.authority.label": "访问控制",
    "rules.types.authority.description": "按调用来源建立白名单或黑名单。",
    "rules.types.param.label": "热点参数",
    "rules.types.param.description": "仅限制同一资源中高频的特定参数值。",

    // ── 字段标签与说明 ──
    "rules.fields.resourceName.label": "资源名称",
    "rules.fields.resourceName.hint": "受保护的资源标识",
    "rules.fields.callerOrigin.label": "调用来源",
    "rules.fields.callerOrigin.hint": "default 表示不区分来源",
    "rules.fields.thresholdType.label": "阈值类型",
    "rules.fields.thresholdType.hint": "阈值的计量单位",
    "rules.fields.singleNodeThreshold.label": "单机阈值",
    "rules.fields.singleNodeThreshold.hint": "单个实例的保护阈值",
    "rules.fields.controlStrategy.label": "流控模式",
    "rules.fields.controlStrategy.hint": "直接、链路或关联",
    "rules.fields.controlBehavior.label": "流控效果",
    "rules.fields.controlBehavior.hint": "触发后的处理方式",
    "rules.fields.relatedResource.label": "关联资源",
    "rules.fields.relatedResource.hint": "链路入口或关联资源",
    "rules.fields.warmUpPeriod.label": "预热时长",
    "rules.fields.warmUpPeriod.hint": "慢启动预热时间（秒）",
    "rules.fields.maxQueueingTime.label": "最大排队时长",
    "rules.fields.maxQueueingTime.hint": "最多排队时间（毫秒）",
    "rules.fields.clusterMode.label": "集群流控",
    "rules.fields.clusterMode.hint": "开启后由集群 Token Server 决策；当前 1.0 的额度变更仍需重启。",
    "rules.fields.clusterThresholdType.label": "集群阈值类型",
    "rules.fields.clusterThresholdType.hint": "集群阈值类型编码",
    "rules.fields.localFallback.label": "本地兜底",
    "rules.fields.localFallback.hint": "Token Server 不可达时是否本地兜底",
    "rules.fields.sampleCount.label": "统计样本数",
    "rules.fields.sampleCount.hint": "统计窗口样本数",
    "rules.fields.statisticWindow.label": "统计窗口",
    "rules.fields.statisticWindow.hint": "统计窗口（毫秒）",
    "rules.fields.circuitStrategy.label": "熔断策略",
    "rules.fields.circuitStrategy.hint": "慢调用、异常比例或异常数",
    "rules.fields.circuitThreshold.label": "熔断阈值",
    "rules.fields.circuitThreshold.hint": "慢调用策略为临界 RT（毫秒）；其他策略为异常阈值",
    "rules.fields.breakDuration.label": "熔断时长",
    "rules.fields.breakDuration.hint": "熔断持续时间（秒）",
    "rules.fields.minimumRequests.label": "最小请求数",
    "rules.fields.minimumRequests.hint": "触发判断的最小请求数",
    "rules.fields.slowCallRatio.label": "慢调用比例",
    "rules.fields.slowCallRatio.hint": "范围为 0 到 1",
    "rules.fields.systemLoad.label": "系统 Load 阈值",
    "rules.fields.systemLoad.hint": "load1 触发值",
    "rules.fields.averageRt.label": "平均响应时间",
    "rules.fields.averageRt.hint": "全部入口平均 RT（毫秒）",
    "rules.fields.maximumThreads.label": "最大并发线程数",
    "rules.fields.maximumThreads.hint": "全部入口最大并发数",
    "rules.fields.entranceQps.label": "入口 QPS 阈值",
    "rules.fields.entranceQps.hint": "全部入口 QPS",
    "rules.fields.cpuUsage.label": "CPU 使用率阈值",
    "rules.fields.cpuUsage.hint": "范围为 0 到 1",
    "rules.fields.authorityMode.label": "访问控制模式",
    "rules.fields.authorityMode.hint": "选择白名单或黑名单",
    "rules.fields.originList.label": "调用来源列表",
    "rules.fields.originList.hint": "多个来源以英文逗号分隔",
    "rules.fields.parameterIndex.label": "参数索引",
    "rules.fields.parameterIndex.hint": "从 0 开始的参数位置",
    "rules.fields.statisticPeriod.label": "统计周期",
    "rules.fields.statisticPeriod.hint": "统计窗口（秒）",
    "rules.fields.parameterExceptions.label": "指定参数值例外",
    "rules.fields.parameterExceptions.hint": "为特定参数值设置独立阈值",
    "rules.fields.parameterType.label": "参数类型",
    "rules.fields.parameterType.hint": "兼容模式保留 Sentinel 类型名",
    "rules.fields.parameterValue.label": "参数值",
    "rules.fields.parameterValue.hint": "匹配的参数值",
    "rules.fields.exceptionThreshold.label": "例外阈值",
    "rules.fields.exceptionThreshold.hint": "该参数值的专用阈值",

    // ── 下拉选项标签（配对顺序见 `useRuleCopy`）──
    "rules.options.flowGrade.qps": "QPS",
    "rules.options.flowGrade.thread": "并发线程数",
    "rules.options.flowStrategy.direct": "直接",
    "rules.options.flowStrategy.chain": "链路",
    "rules.options.flowStrategy.relate": "关联",
    "rules.options.flowBehavior.reject": "直接拒绝",
    "rules.options.flowBehavior.warmUp": "慢启动",
    "rules.options.flowBehavior.queueing": "排队等待",
    "rules.options.degrade.slowRequestRatio": "慢调用比例",
    "rules.options.degrade.errorRatio": "异常比例",
    "rules.options.degrade.errorCount": "异常数",
    "rules.options.authority.white": "白名单",
    "rules.options.authority.black": "黑名单",
  },
  "en-US": {
    // ── Header ──
    "rules.eyebrow": "POLICY / RULES",
    "rules.title": "Rule workspace",
    "rules.description":
      "Configure protection policies with five Sentinel rule families and preview the complete candidate snapshot.",
    "rules.sourceOfTruth": "The configuration center is the sole source of truth",
    "rules.headline":
      "Five Sentinel-compatible rule families · configuration center is the source of truth",
    "rules.headlineDetail":
      "The prototype organizes forms around FlowRule, DegradeRule, SystemRule, AuthorityRule, and ParamFlowRule.",
    "rules.editSample": "Edit sample draft",

    // ── Rule catalog ──
    "rules.catalog": "Rule catalog",
    "rules.catalogDetail": "{count} sample rules · traced by source and version",
    "rules.search": "Search resource or policy",
    "rules.noMatchingRule": "No rule matches the current filter",
    "rules.allTypes": "All types",
    "rules.resourceAndType": "Resource / type",
    "rules.policy": "Policy",
    "rules.threshold": "Threshold",
    "rules.source": "Source",
    "rules.status": "Status",
    "rules.active": "Active",

    // ── Inspector ──
    "rules.details": "Rule details and compatible format",
    "rules.draft": "Rule draft · local simulation",
    "rules.detailDescription":
      "Configuration source and enforcement boundary of the selected rule",
    "rules.draftDescription": "The draft is not written to Nacos or Consul",
    "rules.resource": "Rule resource",
    "rules.provider": "Configuration center",
    "rules.baseline": "Baseline version",
    "rules.scope": "Scope",
    "rules.compatibilityType": "Compatible rule type",
    "rules.scopeExample": "{scope} · enforcement is sample data",
    "rules.configuration": "{type} configuration",
    "rules.editDraft": "Edit draft",
    "rules.configPreview": "Configuration-center preview",
    "rules.jsonArray": "{name} · JSON array",
    "rules.validate": "Validate draft (do not publish)",
    "rules.validationPassed":
      "Sentinel-compatible fields passed local validation. Production publishing must still validate the baseline version, complete snapshot diff, configuration-center writeback, and actual instance load.",
    "rules.notProduction":
      "The prototype validates only a local draft. Production publishing must write the complete rule set to Nacos or Consul, read it back, and confirm that instances loaded it.",

    // ── Form actions and notes ──
    "rules.addException": "Add exception value",
    "rules.remove": "Remove",
    "rules.systemDisabled": "An empty value is serialized as -1, Sentinel's disabled semantic.",
    "rules.paramCompatibility":
      "classType / object are Sentinel Java expressions for parameter exceptions. A cross-language runtime must validate them in its target codec; they are not a general-purpose type system.",

    // ── Validation issues (keys mirror `RuleIssueKey` in `rulePolicy`) ──
    "rules.errors.resourceRequired": "Resource name is required.",
    "rules.errors.countPositive": "The threshold must be greater than 0.",
    "rules.errors.referenceRequired": "A chain or related strategy requires a related resource.",
    "rules.errors.degradePositive":
      "The circuit threshold and break duration must be greater than 0.",
    "rules.errors.slowRatio": "The slow-call ratio must be between 0 and 1.",
    "rules.errors.parameterIndex": "The parameter index must be a non-negative integer.",
    "rules.errors.originsRequired": "The caller-origin list needs at least one origin.",
    "rules.errors.systemEnabled": "Enable at least one system-protection threshold.",

    // ── Filter bar ──
    "rules.filters.environment": "Environment",
    "rules.filters.production": "Production (PROD)",
    "rules.filters.application": "Application",
    "rules.filters.allApplications": "All applications",
    "rules.filters.sample": "Sampled · 14:32:18",

    // ── Scope (keys are the `RULE_SCOPE` protocol values) ──
    "rules.scopes.application": "Application",
    "rules.scopes.resource": "Resource",

    // ── Versions and activation plans ──
    "rules.versions.title": "Versions and activation plans",
    "rules.versions.subtitle":
      "Complete rule-set snapshots; return to a named baseline after the event.",
    "rules.versions.active": "Active",
    "rules.versions.scheduled": "Scheduled",
    "rules.versions.superseded": "Archived",
    "rules.versions.publishedAt": "Published",
    "rules.versions.effectiveWindow": "Effective window",
    "rules.versions.returnTo": "Restore after end",
    "rules.versions.plannedWindow": "Planned window",
    "rules.versions.noEnd": "Remains active",
    "rules.versions.timeZone": "Asia/Shanghai",
    "rules.versions.createVersion": "Preview version freeze (demo)",
    "rules.versions.immutable":
      "A version is immutable. To adjust it, create a new draft based on that version.",
    "rules.versions.previewOnly":
      "The prototype does not create versions or schedule jobs. Production validates a draft before freezing an immutable snapshot.",

    // ── The five rule families ──
    "rules.types.flow.label": "Flow control",
    "rules.types.flow.description":
      "Control entry traffic by QPS, concurrency, call chain, or related resource.",
    "rules.types.degrade.label": "Circuit breaking",
    "rules.types.degrade.description":
      "Protect downstream dependencies by slow-call, error-ratio, or error-count policy.",
    "rules.types.system.label": "System protection",
    "rules.types.system.description":
      "Protect application-wide entry traffic with QPS, threads, RT, load, or CPU boundaries.",
    "rules.types.authority.label": "Authority control",
    "rules.types.authority.description": "Allow or deny resources by caller origin.",
    "rules.types.param.label": "Hot parameter",
    "rules.types.param.description":
      "Limit high-frequency values of a parameter in one resource.",

    // ── Field labels and hints ──
    "rules.fields.resourceName.label": "Resource name",
    "rules.fields.resourceName.hint": "Protected resource identifier",
    "rules.fields.callerOrigin.label": "Caller origin",
    "rules.fields.callerOrigin.hint": "default means all origins",
    "rules.fields.thresholdType.label": "Threshold type",
    "rules.fields.thresholdType.hint": "How the threshold is measured",
    "rules.fields.singleNodeThreshold.label": "Single-node threshold",
    "rules.fields.singleNodeThreshold.hint": "Protection threshold per instance",
    "rules.fields.controlStrategy.label": "Control strategy",
    "rules.fields.controlStrategy.hint": "Direct, chain, or related",
    "rules.fields.controlBehavior.label": "Control behavior",
    "rules.fields.controlBehavior.hint": "What happens after the threshold is reached",
    "rules.fields.relatedResource.label": "Related resource",
    "rules.fields.relatedResource.hint": "Chain entry or related resource",
    "rules.fields.warmUpPeriod.label": "Warm-up period",
    "rules.fields.warmUpPeriod.hint": "Warm-up time in seconds",
    "rules.fields.maxQueueingTime.label": "Maximum queueing time",
    "rules.fields.maxQueueingTime.hint": "Maximum waiting time in milliseconds",
    "rules.fields.clusterMode.label": "Cluster flow control",
    "rules.fields.clusterMode.hint":
      "The cluster Token Server decides admission; quota changes in 1.0 still require restart.",
    "rules.fields.clusterThresholdType.label": "Cluster threshold type",
    "rules.fields.clusterThresholdType.hint": "Cluster threshold type code",
    "rules.fields.localFallback.label": "Local fallback",
    "rules.fields.localFallback.hint":
      "Use local admission when the Token Server is unavailable",
    "rules.fields.sampleCount.label": "Sample count",
    "rules.fields.sampleCount.hint": "Number of samples in the statistic window",
    "rules.fields.statisticWindow.label": "Statistic window",
    "rules.fields.statisticWindow.hint": "Statistic window in milliseconds",
    "rules.fields.circuitStrategy.label": "Circuit-breaking strategy",
    "rules.fields.circuitStrategy.hint": "Slow-call, error ratio, or error count",
    "rules.fields.circuitThreshold.label": "Circuit threshold",
    "rules.fields.circuitThreshold.hint":
      "Slow-call policy uses critical RT (ms); others use an error threshold",
    "rules.fields.breakDuration.label": "Break duration",
    "rules.fields.breakDuration.hint": "Circuit-open duration in seconds",
    "rules.fields.minimumRequests.label": "Minimum request amount",
    "rules.fields.minimumRequests.hint": "Minimum requests before evaluation",
    "rules.fields.slowCallRatio.label": "Slow-call ratio",
    "rules.fields.slowCallRatio.hint": "Range: 0 to 1",
    "rules.fields.systemLoad.label": "System load threshold",
    "rules.fields.systemLoad.hint": "load1 trigger value",
    "rules.fields.averageRt.label": "Average response time",
    "rules.fields.averageRt.hint": "Average RT for all entry traffic (ms)",
    "rules.fields.maximumThreads.label": "Maximum concurrent threads",
    "rules.fields.maximumThreads.hint":
      "Maximum concurrency for all entry traffic",
    "rules.fields.entranceQps.label": "Entry QPS threshold",
    "rules.fields.entranceQps.hint": "QPS for all entry traffic",
    "rules.fields.cpuUsage.label": "CPU usage threshold",
    "rules.fields.cpuUsage.hint": "Range: 0 to 1",
    "rules.fields.authorityMode.label": "Authority mode",
    "rules.fields.authorityMode.hint": "Choose allowlist or denylist",
    "rules.fields.originList.label": "Caller-origin list",
    "rules.fields.originList.hint": "Separate multiple origins with commas",
    "rules.fields.parameterIndex.label": "Parameter index",
    "rules.fields.parameterIndex.hint": "Zero-based parameter position",
    "rules.fields.statisticPeriod.label": "Statistic period",
    "rules.fields.statisticPeriod.hint": "Statistic window in seconds",
    "rules.fields.parameterExceptions.label": "Specific parameter exceptions",
    "rules.fields.parameterExceptions.hint":
      "Use an independent threshold for a parameter value",
    "rules.fields.parameterType.label": "Parameter type",
    "rules.fields.parameterType.hint":
      "Compatibility mode retains the Sentinel type name",
    "rules.fields.parameterValue.label": "Parameter value",
    "rules.fields.parameterValue.hint": "The matched parameter value",
    "rules.fields.exceptionThreshold.label": "Exception threshold",
    "rules.fields.exceptionThreshold.hint": "Dedicated threshold for this parameter value",

    // ── Dropdown labels (pairing order lives in `useRuleCopy`) ──
    "rules.options.flowGrade.qps": "QPS",
    "rules.options.flowGrade.thread": "Concurrent threads",
    "rules.options.flowStrategy.direct": "Direct",
    "rules.options.flowStrategy.chain": "Chain",
    "rules.options.flowStrategy.relate": "Related",
    "rules.options.flowBehavior.reject": "Reject",
    "rules.options.flowBehavior.warmUp": "Warm up",
    "rules.options.flowBehavior.queueing": "Queueing",
    "rules.options.degrade.slowRequestRatio": "Slow-call ratio",
    "rules.options.degrade.errorRatio": "Error ratio",
    "rules.options.degrade.errorCount": "Error count",
    "rules.options.authority.white": "Allowlist",
    "rules.options.authority.black": "Denylist",
  },
  "ja-JP": {
    // ── ヘッダー ──
    "rules.eyebrow": "POLICY / RULES",
    "rules.title": "ルールワークスペース",
    "rules.description":
      "5 種類の Sentinel ルールで保護ポリシーを設定し、完全な候補スナップショットを確認します。",
    "rules.sourceOfTruth": "設定センターが唯一のルール事実源です",
    "rules.headline": "5 種類の Sentinel 互換ルール · 設定センターが事実源です",
    "rules.headlineDetail":
      "このプロトタイプは FlowRule、DegradeRule、SystemRule、AuthorityRule、ParamFlowRule を中心にフォームを構成します。",
    "rules.editSample": "サンプル下書きを編集",

    // ── ルール一覧 ──
    "rules.catalog": "ルール一覧",
    "rules.catalogDetail": "{count} 件のサンプルルール · ソースとバージョンで追跡",
    "rules.search": "リソースまたはポリシーを検索",
    "rules.noMatchingRule": "現在の絞り込み条件に一致するルールはありません",
    "rules.allTypes": "すべての種類",
    "rules.resourceAndType": "リソース / 種類",
    "rules.policy": "ポリシー",
    "rules.threshold": "しきい値",
    "rules.source": "ソース",
    "rules.status": "状態",
    "rules.active": "有効",

    // ── インスペクタ ──
    "rules.details": "ルール詳細と互換形式",
    "rules.draft": "ルール下書き · ローカルシミュレーション",
    "rules.detailDescription": "選択したルールの設定ソースと適用境界",
    "rules.draftDescription": "下書きは Nacos または Consul に書き込みません",
    "rules.resource": "ルールリソース",
    "rules.provider": "設定センター",
    "rules.baseline": "基準バージョン",
    "rules.scope": "適用範囲",
    "rules.compatibilityType": "互換ルールタイプ",
    "rules.scopeExample": "{scope} · 適用状態はサンプルです",
    "rules.configuration": "{type} 設定",
    "rules.editDraft": "下書きを編集",
    "rules.configPreview": "設定センター内容プレビュー",
    "rules.jsonArray": "{name} · JSON 配列",
    "rules.validate": "下書きを検証（公開しない）",
    "rules.validationPassed":
      "Sentinel 互換フィールドのローカル検証に成功しました。本番公開では、基準バージョン、完全スナップショット差分、設定センターへの書き戻し、インスタンス実ロードを確認する必要があります。",
    "rules.notProduction":
      "このプロトタイプはローカル下書きだけを検証します。本番公開では完全なルールセットを Nacos または Consul に書き込み、読み戻し、インスタンスのロードを確認します。",

    // ── フォーム操作と注記 ──
    "rules.addException": "例外値を追加",
    "rules.remove": "削除",
    "rules.systemDisabled": "空欄は -1 としてシリアライズされ、Sentinel では無効を意味します。",
    "rules.paramCompatibility":
      "classType / object は Sentinel Java 形式のパラメータ例外表現です。クロス言語ランタイムでは対象 codec で明示的に検証する必要があり、汎用型システムではありません。",

    // ── 検証エラー（キーは `rulePolicy` の `RuleIssueKey` と一致）──
    "rules.errors.resourceRequired": "リソース名は必須です。",
    "rules.errors.countPositive": "しきい値は 0 より大きくなければなりません。",
    "rules.errors.referenceRequired": "チェーンまたは関連方式では関連リソースが必要です。",
    "rules.errors.degradePositive": "遮断しきい値と遮断時間は 0 より大きくなければなりません。",
    "rules.errors.slowRatio": "遅延呼び出し比率は 0 から 1 の範囲で指定してください。",
    "rules.errors.parameterIndex": "パラメータインデックスは 0 以上の整数でなければなりません。",
    "rules.errors.originsRequired": "呼び出し元リストには少なくとも 1 つの origin が必要です。",
    "rules.errors.systemEnabled": "少なくとも 1 つのシステム保護しきい値を有効にしてください。",

    // ── 絞り込みバー ──
    "rules.filters.environment": "環境",
    "rules.filters.production": "本番環境 (PROD)",
    "rules.filters.application": "アプリケーション",
    "rules.filters.allApplications": "すべてのアプリケーション",
    "rules.filters.sample": "サンプル取得 · 14:32:18",

    // ── 適用範囲（キーは `RULE_SCOPE` のプロトコル値）──
    "rules.scopes.application": "アプリケーション",
    "rules.scopes.resource": "リソース",

    // ── バージョンと有効化計画 ──
    "rules.versions.title": "バージョンと有効化計画",
    "rules.versions.subtitle":
      "完全なルールセットスナップショット。イベント終了後は指定した通常版へ戻します。",
    "rules.versions.active": "現在有効",
    "rules.versions.scheduled": "予定済み",
    "rules.versions.superseded": "アーカイブ済み",
    "rules.versions.publishedAt": "公開日時",
    "rules.versions.effectiveWindow": "有効期間",
    "rules.versions.returnTo": "終了後の復帰先",
    "rules.versions.plannedWindow": "予定期間",
    "rules.versions.noEnd": "継続して有効",
    "rules.versions.timeZone": "Asia/Shanghai",
    "rules.versions.createVersion": "バージョン固定をプレビュー（デモ）",
    "rules.versions.immutable":
      "バージョンは作成後に変更できません。調整する場合はそのバージョンから新しい下書きを作成します。",
    "rules.versions.previewOnly":
      "このプロトタイプはバージョンを作成せず、ジョブもスケジュールしません。本番では下書きを検証してから不変スナップショットを固定します。",

    // ── 5 種類のルール ──
    "rules.types.flow.label": "フロー制御",
    "rules.types.flow.description":
      "QPS、同時実行数、呼び出しチェーン、関連リソースで入口トラフィックを制御します。",
    "rules.types.degrade.label": "サーキットブレーカー",
    "rules.types.degrade.description":
      "遅延呼び出し、エラー比率、エラー数で下流依存を保護します。",
    "rules.types.system.label": "システム保護",
    "rules.types.system.description":
      "QPS、スレッド、RT、Load、CPU によりアプリケーション全体の入口トラフィックを保護します。",
    "rules.types.authority.label": "アクセス制御",
    "rules.types.authority.description": "呼び出し元 origin によりリソースを許可または拒否します。",
    "rules.types.param.label": "ホットパラメータ",
    "rules.types.param.description": "1 つのリソース内で頻度の高いパラメータ値を制限します。",

    // ── フィールドのラベルと説明 ──
    "rules.fields.resourceName.label": "リソース名",
    "rules.fields.resourceName.hint": "保護するリソース識別子",
    "rules.fields.callerOrigin.label": "呼び出し元",
    "rules.fields.callerOrigin.hint": "default はすべての origin を意味します",
    "rules.fields.thresholdType.label": "しきい値タイプ",
    "rules.fields.thresholdType.hint": "しきい値の計測単位",
    "rules.fields.singleNodeThreshold.label": "単一ノードしきい値",
    "rules.fields.singleNodeThreshold.hint": "インスタンスごとの保護しきい値",
    "rules.fields.controlStrategy.label": "制御方式",
    "rules.fields.controlStrategy.hint": "直接、チェーン、または関連",
    "rules.fields.controlBehavior.label": "制御効果",
    "rules.fields.controlBehavior.hint": "しきい値到達時の動作",
    "rules.fields.relatedResource.label": "関連リソース",
    "rules.fields.relatedResource.hint": "チェーン入口または関連リソース",
    "rules.fields.warmUpPeriod.label": "ウォームアップ時間",
    "rules.fields.warmUpPeriod.hint": "ウォームアップ時間（秒）",
    "rules.fields.maxQueueingTime.label": "最大待機時間",
    "rules.fields.maxQueueingTime.hint": "最大待機時間（ミリ秒）",
    "rules.fields.clusterMode.label": "クラスタフロー制御",
    "rules.fields.clusterMode.hint":
      "クラスタ Token Server が許可を決定します。1.0 のクォータ変更は再起動が必要です。",
    "rules.fields.clusterThresholdType.label": "クラスタしきい値タイプ",
    "rules.fields.clusterThresholdType.hint": "クラスタしきい値タイプコード",
    "rules.fields.localFallback.label": "ローカルフォールバック",
    "rules.fields.localFallback.hint": "Token Server が利用できない場合にローカルで許可します",
    "rules.fields.sampleCount.label": "サンプル数",
    "rules.fields.sampleCount.hint": "統計ウィンドウ内のサンプル数",
    "rules.fields.statisticWindow.label": "統計ウィンドウ",
    "rules.fields.statisticWindow.hint": "統計ウィンドウ（ミリ秒）",
    "rules.fields.circuitStrategy.label": "遮断戦略",
    "rules.fields.circuitStrategy.hint": "遅延呼び出し、エラー比率、またはエラー数",
    "rules.fields.circuitThreshold.label": "遮断しきい値",
    "rules.fields.circuitThreshold.hint": "遅延呼び出しでは臨界 RT（ms）、その他ではエラーしきい値",
    "rules.fields.breakDuration.label": "遮断時間",
    "rules.fields.breakDuration.hint": "回路を開く時間（秒）",
    "rules.fields.minimumRequests.label": "最小リクエスト数",
    "rules.fields.minimumRequests.hint": "評価前に必要な最小リクエスト数",
    "rules.fields.slowCallRatio.label": "遅延呼び出し比率",
    "rules.fields.slowCallRatio.hint": "範囲: 0 から 1",
    "rules.fields.systemLoad.label": "システム Load しきい値",
    "rules.fields.systemLoad.hint": "load1 のトリガー値",
    "rules.fields.averageRt.label": "平均応答時間",
    "rules.fields.averageRt.hint": "すべての入口トラフィックの平均 RT（ms）",
    "rules.fields.maximumThreads.label": "最大同時スレッド数",
    "rules.fields.maximumThreads.hint": "すべての入口トラフィックの最大同時実行数",
    "rules.fields.entranceQps.label": "入口 QPS しきい値",
    "rules.fields.entranceQps.hint": "すべての入口トラフィックの QPS",
    "rules.fields.cpuUsage.label": "CPU 使用率しきい値",
    "rules.fields.cpuUsage.hint": "範囲: 0 から 1",
    "rules.fields.authorityMode.label": "アクセス制御モード",
    "rules.fields.authorityMode.hint": "許可リストまたは拒否リストを選択",
    "rules.fields.originList.label": "呼び出し元リスト",
    "rules.fields.originList.hint": "複数の origin はカンマで区切ります",
    "rules.fields.parameterIndex.label": "パラメータインデックス",
    "rules.fields.parameterIndex.hint": "0 から始まるパラメータ位置",
    "rules.fields.statisticPeriod.label": "統計期間",
    "rules.fields.statisticPeriod.hint": "統計ウィンドウ（秒）",
    "rules.fields.parameterExceptions.label": "特定パラメータ値の例外",
    "rules.fields.parameterExceptions.hint": "パラメータ値に独立したしきい値を設定",
    "rules.fields.parameterType.label": "パラメータ型",
    "rules.fields.parameterType.hint": "互換モードでは Sentinel の型名を保持します",
    "rules.fields.parameterValue.label": "パラメータ値",
    "rules.fields.parameterValue.hint": "一致するパラメータ値",
    "rules.fields.exceptionThreshold.label": "例外しきい値",
    "rules.fields.exceptionThreshold.hint": "このパラメータ値専用のしきい値",

    // ── ドロップダウンのラベル（対応順序は `useRuleCopy`）──
    "rules.options.flowGrade.qps": "QPS",
    "rules.options.flowGrade.thread": "同時実行スレッド",
    "rules.options.flowStrategy.direct": "直接",
    "rules.options.flowStrategy.chain": "チェーン",
    "rules.options.flowStrategy.relate": "関連",
    "rules.options.flowBehavior.reject": "即時拒否",
    "rules.options.flowBehavior.warmUp": "ウォームアップ",
    "rules.options.flowBehavior.queueing": "待機キュー",
    "rules.options.degrade.slowRequestRatio": "遅延呼び出し比率",
    "rules.options.degrade.errorRatio": "エラー比率",
    "rules.options.degrade.errorCount": "エラー数",
    "rules.options.authority.white": "許可リスト",
    "rules.options.authority.black": "拒否リスト",
  },
} as const satisfies LocaleBundle;
