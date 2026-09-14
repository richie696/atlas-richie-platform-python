export const DASHBOARD_LOCALES = Object.freeze([
  { code: "zh-CN", label: "简体中文" },
  { code: "en-US", label: "English" },
  { code: "ja-JP", label: "日本語" },
]);

const field = (label, hint) => Object.freeze({ label, hint });

const MESSAGES = Object.freeze({
  "zh-CN": {
    shell: {
      language: "界面语言",
      navigation: [
        "总览",
        "应用与实例",
        "规则",
        "实时监控",
        "故障分析",
        "系统管理",
      ],
      prototype: "设计原型",
      online: "浏览器在线",
      offline: "浏览器离线 · 仅本地演示",
      demo: "交互设计原型",
      demoNotice:
        "全部指标、应用、规则与连接状态均为示例数据；未连接生产服务或配置中心。",
    },
    rules: {
      eyebrow: "POLICY / RULES",
      title: "规则工作台",
      description:
        "用五类 Sentinel 规则字段配置保护策略；每次编辑都预览完整配置快照。",
      sourceOfTruth: "配置中心是唯一规则事实源",
      headline: "五类 Sentinel 兼容规则 · 配置中心是唯一规则事实源",
      headlineDetail:
        "原型以 FlowRule、DegradeRule、SystemRule、AuthorityRule、ParamFlowRule 的字段组织表单。",
      editSample: "编辑示例草稿",
      catalog: "规则清单",
      catalogDetail: "{count} 条示例规则 · 按来源与版本追踪",
      search: "搜索资源或策略",
      allTypes: "全部类型",
      resourceAndType: "资源 / 类型",
      policy: "策略",
      threshold: "阈值",
      source: "来源",
      status: "状态",
      active: "生效中",
      details: "规则详情与兼容格式",
      draft: "规则草稿 · 本地模拟",
      detailDescription: "所选规则的配置来源与生效边界",
      draftDescription: "草稿不会写入 Nacos 或 Consul",
      resource: "规则资源",
      provider: "配置中心",
      baseline: "基准版本",
      scope: "生效范围",
      compatibilityType: "兼容规则类型",
      scopeExample: "{scope} · 生效情况为示例",
      configuration: "{type}配置",
      editDraft: "编辑草稿",
      configPreview: "配置中心内容预览",
      jsonArray: "{name} · JSON 数组",
      validate: "校验草稿（不发布）",
      validationPassed:
        "Sentinel 兼容字段校验通过；生产发布还需校验基准版本、生成完整快照差异、写回配置中心并确认实例生效。",
      notProduction:
        "原型只校验本地草稿；真实发布必须将完整规则集写回 Nacos 或 Consul、回读并确认实例实际加载。",
      addException: "添加例外值",
      remove: "移除",
      systemDisabled: "留空会序列化为 -1，即 Sentinel 的不生效语义。",
      paramCompatibility:
        "classType / object 是 Sentinel Java 格式中的参数例外表达；跨语言运行时必须由目标 codec 明确验证，不能把它误认为通用类型系统。",
      errors: {
        resourceRequired: "资源名称不能为空。",
        countPositive: "阈值必须大于 0。",
        referenceRequired: "链路或关联策略必须提供关联资源。",
        degradePositive: "熔断阈值与熔断时长必须大于 0。",
        slowRatio: "慢调用比例必须在 0 到 1 之间。",
        parameterIndex: "参数索引必须是大于等于 0 的整数。",
        originsRequired: "调用来源列表至少需要一个来源。",
        systemEnabled: "至少启用一项系统保护阈值。",
      },
      filters: {
        environment: "环境",
        production: "生产环境 (PROD)",
        application: "应用",
        allApplications: "全部应用",
        sample: "示例采样 · 14:32:18",
      },
      scopes: { 应用: "应用", 资源: "资源" },
      versions: {
        title: "版本与生效计划",
        subtitle: "完整规则集快照；活动结束后回退到指定日常版本",
        active: "当前生效",
        scheduled: "已计划",
        superseded: "已归档",
        publishedAt: "发布时间",
        effectiveWindow: "生效窗口",
        returnTo: "结束后回退",
        plannedWindow: "计划窗口",
        noEnd: "持续生效",
        timeZone: "Asia/Shanghai",
        createVersion: "查看版本固化说明（演示）",
        immutable: "版本一经创建不可修改；如需调整，基于该版本新建草稿。",
        previewOnly:
          "原型不会创建版本或调度任务；正式流程先校验草稿，再固化不可变快照。",
      },
    },
    types: {
      flow: {
        label: "流量控制",
        description: "按 QPS、并发、调用链或关联资源控制入口流量。",
      },
      degrade: {
        label: "熔断降级",
        description: "按慢调用、异常比例或异常数保护下游依赖。",
      },
      system: {
        label: "系统保护",
        description: "以应用整体的入口 QPS、线程、RT、Load 或 CPU 为边界。",
      },
      authority: {
        label: "访问控制",
        description: "按调用来源建立白名单或黑名单。",
      },
      param: {
        label: "热点参数",
        description: "仅限制同一资源中高频的特定参数值。",
      },
    },
    fields: {
      resourceName: field("资源名称", "受保护的资源标识"),
      callerOrigin: field("调用来源", "default 表示不区分来源"),
      thresholdType: field("阈值类型", "阈值的计量单位"),
      singleNodeThreshold: field("单机阈值", "单个实例的保护阈值"),
      controlStrategy: field("流控模式", "直接、链路或关联"),
      controlBehavior: field("流控效果", "触发后的处理方式"),
      relatedResource: field("关联资源", "链路入口或关联资源"),
      warmUpPeriod: field("预热时长", "慢启动预热时间（秒）"),
      maxQueueingTime: field("最大排队时长", "最多排队时间（毫秒）"),
      clusterMode: field(
        "集群流控",
        "开启后由集群 Token Server 决策；当前 1.0 的额度变更仍需重启。",
      ),
      clusterThresholdType: field("集群阈值类型", "集群阈值类型编码"),
      localFallback: field("本地兜底", "Token Server 不可达时是否本地兜底"),
      sampleCount: field("统计样本数", "统计窗口样本数"),
      statisticWindow: field("统计窗口", "统计窗口（毫秒）"),
      circuitStrategy: field("熔断策略", "慢调用、异常比例或异常数"),
      circuitThreshold: field(
        "熔断阈值",
        "慢调用策略为临界 RT（毫秒）；其他策略为异常阈值",
      ),
      breakDuration: field("熔断时长", "熔断持续时间（秒）"),
      minimumRequests: field("最小请求数", "触发判断的最小请求数"),
      slowCallRatio: field("慢调用比例", "范围为 0 到 1"),
      systemLoad: field("系统 Load 阈值", "load1 触发值"),
      averageRt: field("平均响应时间", "全部入口平均 RT（毫秒）"),
      maximumThreads: field("最大并发线程数", "全部入口最大并发数"),
      entranceQps: field("入口 QPS 阈值", "全部入口 QPS"),
      cpuUsage: field("CPU 使用率阈值", "范围为 0 到 1"),
      authorityMode: field("访问控制模式", "选择白名单或黑名单"),
      originList: field("调用来源列表", "多个来源以英文逗号分隔"),
      parameterIndex: field("参数索引", "从 0 开始的参数位置"),
      statisticPeriod: field("统计周期", "统计窗口（秒）"),
      parameterExceptions: field("指定参数值例外", "为特定参数值设置独立阈值"),
      parameterType: field("参数类型", "兼容模式保留 Sentinel 类型名"),
      parameterValue: field("参数值", "匹配的参数值"),
      exceptionThreshold: field("例外阈值", "该参数值的专用阈值"),
    },
    options: {
      flowGrade: ["QPS", "并发线程数"],
      flowStrategy: ["直接", "链路", "关联"],
      flowBehavior: ["直接拒绝", "慢启动", "排队等待"],
      degrade: ["慢调用比例", "异常比例", "异常数"],
      authority: ["白名单", "黑名单"],
    },
  },
  "en-US": {
    shell: {
      language: "Language",
      navigation: [
        "Overview",
        "Applications & instances",
        "Rules",
        "Live monitoring",
        "Fault analysis",
        "System",
      ],
      prototype: "Design prototype",
      online: "Browser online",
      offline: "Browser offline · local demo only",
      demo: "Interactive design prototype",
      demoNotice:
        "All metrics, applications, rules, and connection states are sample data; no production service or configuration center is connected.",
    },
    rules: {
      eyebrow: "POLICY / RULES",
      title: "Rule workspace",
      description:
        "Configure protection policies with five Sentinel rule families and preview the complete candidate snapshot.",
      sourceOfTruth: "The configuration center is the sole source of truth",
      headline:
        "Five Sentinel-compatible rule families · configuration center is the source of truth",
      headlineDetail:
        "The prototype organizes forms around FlowRule, DegradeRule, SystemRule, AuthorityRule, and ParamFlowRule.",
      editSample: "Edit sample draft",
      catalog: "Rule catalog",
      catalogDetail: "{count} sample rules · traced by source and version",
      search: "Search resource or policy",
      allTypes: "All types",
      resourceAndType: "Resource / type",
      policy: "Policy",
      threshold: "Threshold",
      source: "Source",
      status: "Status",
      active: "Active",
      details: "Rule details and compatible format",
      draft: "Rule draft · local simulation",
      detailDescription:
        "Configuration source and enforcement boundary of the selected rule",
      draftDescription: "The draft is not written to Nacos or Consul",
      resource: "Rule resource",
      provider: "Configuration center",
      baseline: "Baseline version",
      scope: "Scope",
      compatibilityType: "Compatible rule type",
      scopeExample: "{scope} · enforcement is sample data",
      configuration: "{type} configuration",
      editDraft: "Edit draft",
      configPreview: "Configuration-center preview",
      jsonArray: "{name} · JSON array",
      validate: "Validate draft (do not publish)",
      validationPassed:
        "Sentinel-compatible fields passed local validation. Production publishing must still validate the baseline version, complete snapshot diff, configuration-center writeback, and actual instance load.",
      notProduction:
        "The prototype validates only a local draft. Production publishing must write the complete rule set to Nacos or Consul, read it back, and confirm that instances loaded it.",
      addException: "Add exception value",
      remove: "Remove",
      systemDisabled:
        "An empty value is serialized as -1, Sentinel's disabled semantic.",
      paramCompatibility:
        "classType / object are Sentinel Java expressions for parameter exceptions. A cross-language runtime must validate them in its target codec; they are not a general-purpose type system.",
      errors: {
        resourceRequired: "Resource name is required.",
        countPositive: "The threshold must be greater than 0.",
        referenceRequired:
          "A chain or related strategy requires a related resource.",
        degradePositive:
          "The circuit threshold and break duration must be greater than 0.",
        slowRatio: "The slow-call ratio must be between 0 and 1.",
        parameterIndex: "The parameter index must be a non-negative integer.",
        originsRequired: "The caller-origin list needs at least one origin.",
        systemEnabled: "Enable at least one system-protection threshold.",
      },
      filters: {
        environment: "Environment",
        production: "Production (PROD)",
        application: "Application",
        allApplications: "All applications",
        sample: "Sampled · 14:32:18",
      },
      scopes: { 应用: "Application", 资源: "Resource" },
      versions: {
        title: "Versions and activation plans",
        subtitle:
          "Complete rule-set snapshots; return to a named baseline after the event.",
        active: "Active",
        scheduled: "Scheduled",
        superseded: "Archived",
        publishedAt: "Published",
        effectiveWindow: "Effective window",
        returnTo: "Restore after end",
        plannedWindow: "Planned window",
        noEnd: "Remains active",
        timeZone: "Asia/Shanghai",
        createVersion: "Preview version freeze (demo)",
        immutable:
          "A version is immutable. To adjust it, create a new draft based on that version.",
        previewOnly:
          "The prototype does not create versions or schedule jobs. Production validates a draft before freezing an immutable snapshot.",
      },
    },
    types: {
      flow: {
        label: "Flow control",
        description:
          "Control entry traffic by QPS, concurrency, call chain, or related resource.",
      },
      degrade: {
        label: "Circuit breaking",
        description:
          "Protect downstream dependencies by slow-call, error-ratio, or error-count policy.",
      },
      system: {
        label: "System protection",
        description:
          "Protect application-wide entry traffic with QPS, threads, RT, load, or CPU boundaries.",
      },
      authority: {
        label: "Authority control",
        description: "Allow or deny resources by caller origin.",
      },
      param: {
        label: "Hot parameter",
        description:
          "Limit high-frequency values of a parameter in one resource.",
      },
    },
    fields: {
      resourceName: field("Resource name", "Protected resource identifier"),
      callerOrigin: field("Caller origin", "default means all origins"),
      thresholdType: field("Threshold type", "How the threshold is measured"),
      singleNodeThreshold: field(
        "Single-node threshold",
        "Protection threshold per instance",
      ),
      controlStrategy: field("Control strategy", "Direct, chain, or related"),
      controlBehavior: field(
        "Control behavior",
        "What happens after the threshold is reached",
      ),
      relatedResource: field(
        "Related resource",
        "Chain entry or related resource",
      ),
      warmUpPeriod: field("Warm-up period", "Warm-up time in seconds"),
      maxQueueingTime: field(
        "Maximum queueing time",
        "Maximum waiting time in milliseconds",
      ),
      clusterMode: field(
        "Cluster flow control",
        "The cluster Token Server decides admission; quota changes in 1.0 still require restart.",
      ),
      clusterThresholdType: field(
        "Cluster threshold type",
        "Cluster threshold type code",
      ),
      localFallback: field(
        "Local fallback",
        "Use local admission when the Token Server is unavailable",
      ),
      sampleCount: field(
        "Sample count",
        "Number of samples in the statistic window",
      ),
      statisticWindow: field(
        "Statistic window",
        "Statistic window in milliseconds",
      ),
      circuitStrategy: field(
        "Circuit-breaking strategy",
        "Slow-call, error ratio, or error count",
      ),
      circuitThreshold: field(
        "Circuit threshold",
        "Slow-call policy uses critical RT (ms); others use an error threshold",
      ),
      breakDuration: field(
        "Break duration",
        "Circuit-open duration in seconds",
      ),
      minimumRequests: field(
        "Minimum request amount",
        "Minimum requests before evaluation",
      ),
      slowCallRatio: field("Slow-call ratio", "Range: 0 to 1"),
      systemLoad: field("System load threshold", "load1 trigger value"),
      averageRt: field(
        "Average response time",
        "Average RT for all entry traffic (ms)",
      ),
      maximumThreads: field(
        "Maximum concurrent threads",
        "Maximum concurrency for all entry traffic",
      ),
      entranceQps: field("Entry QPS threshold", "QPS for all entry traffic"),
      cpuUsage: field("CPU usage threshold", "Range: 0 to 1"),
      authorityMode: field("Authority mode", "Choose allowlist or denylist"),
      originList: field(
        "Caller-origin list",
        "Separate multiple origins with commas",
      ),
      parameterIndex: field("Parameter index", "Zero-based parameter position"),
      statisticPeriod: field("Statistic period", "Statistic window in seconds"),
      parameterExceptions: field(
        "Specific parameter exceptions",
        "Use an independent threshold for a parameter value",
      ),
      parameterType: field(
        "Parameter type",
        "Compatibility mode retains the Sentinel type name",
      ),
      parameterValue: field("Parameter value", "The matched parameter value"),
      exceptionThreshold: field(
        "Exception threshold",
        "Dedicated threshold for this parameter value",
      ),
    },
    options: {
      flowGrade: ["QPS", "Concurrent threads"],
      flowStrategy: ["Direct", "Chain", "Related"],
      flowBehavior: ["Reject", "Warm up", "Queueing"],
      degrade: ["Slow-call ratio", "Error ratio", "Error count"],
      authority: ["Allowlist", "Denylist"],
    },
  },
  "ja-JP": {
    shell: {
      language: "表示言語",
      navigation: [
        "概要",
        "アプリケーションとインスタンス",
        "ルール",
        "リアルタイム監視",
        "障害分析",
        "システム",
      ],
      prototype: "デザインプロトタイプ",
      online: "ブラウザ接続中",
      offline: "ブラウザオフライン · ローカルデモのみ",
      demo: "インタラクティブデザインプロトタイプ",
      demoNotice:
        "すべてのメトリクス、アプリケーション、ルール、接続状態はサンプルデータです。本番サービスおよび設定センターには接続していません。",
    },
    rules: {
      eyebrow: "POLICY / RULES",
      title: "ルールワークスペース",
      description:
        "5 種類の Sentinel ルールで保護ポリシーを設定し、完全な候補スナップショットを確認します。",
      sourceOfTruth: "設定センターが唯一のルール事実源です",
      headline: "5 種類の Sentinel 互換ルール · 設定センターが事実源です",
      headlineDetail:
        "このプロトタイプは FlowRule、DegradeRule、SystemRule、AuthorityRule、ParamFlowRule を中心にフォームを構成します。",
      editSample: "サンプル下書きを編集",
      catalog: "ルール一覧",
      catalogDetail: "{count} 件のサンプルルール · ソースとバージョンで追跡",
      search: "リソースまたはポリシーを検索",
      allTypes: "すべての種類",
      resourceAndType: "リソース / 種類",
      policy: "ポリシー",
      threshold: "しきい値",
      source: "ソース",
      status: "状態",
      active: "有効",
      details: "ルール詳細と互換形式",
      draft: "ルール下書き · ローカルシミュレーション",
      detailDescription: "選択したルールの設定ソースと適用境界",
      draftDescription: "下書きは Nacos または Consul に書き込みません",
      resource: "ルールリソース",
      provider: "設定センター",
      baseline: "基準バージョン",
      scope: "適用範囲",
      compatibilityType: "互換ルールタイプ",
      scopeExample: "{scope} · 適用状態はサンプルです",
      configuration: "{type} 設定",
      editDraft: "下書きを編集",
      configPreview: "設定センター内容プレビュー",
      jsonArray: "{name} · JSON 配列",
      validate: "下書きを検証（公開しない）",
      validationPassed:
        "Sentinel 互換フィールドのローカル検証に成功しました。本番公開では、基準バージョン、完全スナップショット差分、設定センターへの書き戻し、インスタンス実ロードを確認する必要があります。",
      notProduction:
        "このプロトタイプはローカル下書きだけを検証します。本番公開では完全なルールセットを Nacos または Consul に書き込み、読み戻し、インスタンスのロードを確認します。",
      addException: "例外値を追加",
      remove: "削除",
      systemDisabled:
        "空欄は -1 としてシリアライズされ、Sentinel では無効を意味します。",
      paramCompatibility:
        "classType / object は Sentinel Java 形式のパラメータ例外表現です。クロス言語ランタイムでは対象 codec で明示的に検証する必要があり、汎用型システムではありません。",
      errors: {
        resourceRequired: "リソース名は必須です。",
        countPositive: "しきい値は 0 より大きくなければなりません。",
        referenceRequired: "チェーンまたは関連方式では関連リソースが必要です。",
        degradePositive:
          "遮断しきい値と遮断時間は 0 より大きくなければなりません。",
        slowRatio: "遅延呼び出し比率は 0 から 1 の範囲で指定してください。",
        parameterIndex:
          "パラメータインデックスは 0 以上の整数でなければなりません。",
        originsRequired:
          "呼び出し元リストには少なくとも 1 つの origin が必要です。",
        systemEnabled:
          "少なくとも 1 つのシステム保護しきい値を有効にしてください。",
      },
      filters: {
        environment: "環境",
        production: "本番環境 (PROD)",
        application: "アプリケーション",
        allApplications: "すべてのアプリケーション",
        sample: "サンプル取得 · 14:32:18",
      },
      scopes: { 应用: "アプリケーション", 资源: "リソース" },
      versions: {
        title: "バージョンと有効化計画",
        subtitle:
          "完全なルールセットスナップショット。イベント終了後は指定した通常版へ戻します。",
        active: "現在有効",
        scheduled: "予定済み",
        superseded: "アーカイブ済み",
        publishedAt: "公開日時",
        effectiveWindow: "有効期間",
        returnTo: "終了後の復帰先",
        plannedWindow: "予定期間",
        noEnd: "継続して有効",
        timeZone: "Asia/Shanghai",
        createVersion: "バージョン固定をプレビュー（デモ）",
        immutable:
          "バージョンは作成後に変更できません。調整する場合はそのバージョンから新しい下書きを作成します。",
        previewOnly:
          "このプロトタイプはバージョンを作成せず、ジョブもスケジュールしません。本番では下書きを検証してから不変スナップショットを固定します。",
      },
    },
    types: {
      flow: {
        label: "フロー制御",
        description:
          "QPS、同時実行数、呼び出しチェーン、関連リソースで入口トラフィックを制御します。",
      },
      degrade: {
        label: "サーキットブレーカー",
        description:
          "遅延呼び出し、エラー比率、エラー数で下流依存を保護します。",
      },
      system: {
        label: "システム保護",
        description:
          "QPS、スレッド、RT、Load、CPU によりアプリケーション全体の入口トラフィックを保護します。",
      },
      authority: {
        label: "アクセス制御",
        description: "呼び出し元 origin によりリソースを許可または拒否します。",
      },
      param: {
        label: "ホットパラメータ",
        description: "1 つのリソース内で頻度の高いパラメータ値を制限します。",
      },
    },
    fields: {
      resourceName: field("リソース名", "保護するリソース識別子"),
      callerOrigin: field(
        "呼び出し元",
        "default はすべての origin を意味します",
      ),
      thresholdType: field("しきい値タイプ", "しきい値の計測単位"),
      singleNodeThreshold: field(
        "単一ノードしきい値",
        "インスタンスごとの保護しきい値",
      ),
      controlStrategy: field("制御方式", "直接、チェーン、または関連"),
      controlBehavior: field("制御効果", "しきい値到達時の動作"),
      relatedResource: field("関連リソース", "チェーン入口または関連リソース"),
      warmUpPeriod: field("ウォームアップ時間", "ウォームアップ時間（秒）"),
      maxQueueingTime: field("最大待機時間", "最大待機時間（ミリ秒）"),
      clusterMode: field(
        "クラスタフロー制御",
        "クラスタ Token Server が許可を決定します。1.0 のクォータ変更は再起動が必要です。",
      ),
      clusterThresholdType: field(
        "クラスタしきい値タイプ",
        "クラスタしきい値タイプコード",
      ),
      localFallback: field(
        "ローカルフォールバック",
        "Token Server が利用できない場合にローカルで許可します",
      ),
      sampleCount: field("サンプル数", "統計ウィンドウ内のサンプル数"),
      statisticWindow: field("統計ウィンドウ", "統計ウィンドウ（ミリ秒）"),
      circuitStrategy: field(
        "遮断戦略",
        "遅延呼び出し、エラー比率、またはエラー数",
      ),
      circuitThreshold: field(
        "遮断しきい値",
        "遅延呼び出しでは臨界 RT（ms）、その他ではエラーしきい値",
      ),
      breakDuration: field("遮断時間", "回路を開く時間（秒）"),
      minimumRequests: field(
        "最小リクエスト数",
        "評価前に必要な最小リクエスト数",
      ),
      slowCallRatio: field("遅延呼び出し比率", "範囲: 0 から 1"),
      systemLoad: field("システム Load しきい値", "load1 のトリガー値"),
      averageRt: field(
        "平均応答時間",
        "すべての入口トラフィックの平均 RT（ms）",
      ),
      maximumThreads: field(
        "最大同時スレッド数",
        "すべての入口トラフィックの最大同時実行数",
      ),
      entranceQps: field("入口 QPS しきい値", "すべての入口トラフィックの QPS"),
      cpuUsage: field("CPU 使用率しきい値", "範囲: 0 から 1"),
      authorityMode: field(
        "アクセス制御モード",
        "許可リストまたは拒否リストを選択",
      ),
      originList: field(
        "呼び出し元リスト",
        "複数の origin はカンマで区切ります",
      ),
      parameterIndex: field(
        "パラメータインデックス",
        "0 から始まるパラメータ位置",
      ),
      statisticPeriod: field("統計期間", "統計ウィンドウ（秒）"),
      parameterExceptions: field(
        "特定パラメータ値の例外",
        "パラメータ値に独立したしきい値を設定",
      ),
      parameterType: field(
        "パラメータ型",
        "互換モードでは Sentinel の型名を保持します",
      ),
      parameterValue: field("パラメータ値", "一致するパラメータ値"),
      exceptionThreshold: field(
        "例外しきい値",
        "このパラメータ値専用のしきい値",
      ),
    },
    options: {
      flowGrade: ["QPS", "同時実行スレッド"],
      flowStrategy: ["直接", "チェーン", "関連"],
      flowBehavior: ["即時拒否", "ウォームアップ", "待機キュー"],
      degrade: ["遅延呼び出し比率", "エラー比率", "エラー数"],
      authority: ["許可リスト", "拒否リスト"],
    },
  },
});

function resolve(messages, path) {
  return path.split(".").reduce((value, key) => value?.[key], messages);
}

export function createRuleTranslator(locale: string) {
  const messages = MESSAGES[locale] ?? MESSAGES["zh-CN"];
  return (path: string, replacements: Record<string, string | number> = {}) => {
    const value = resolve(messages, path);
    if (typeof value !== "string") return path;
    return Object.entries(replacements).reduce(
      (text, [key, replacement]) => text.replaceAll(`{${key}}`, String(replacement)),
      value,
    );
  };
}

export function ruleMessages(locale: string) {
  return MESSAGES[locale] ?? MESSAGES["zh-CN"];
}
