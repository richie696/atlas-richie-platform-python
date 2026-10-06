/**
 * 身份与初始化 feature 的文案（登录、账户维护、角色绑定、修改密码、系统初始化）。
 *
 * 中文
 * ----
 * ## zh 取值来源
 *
 * 视图层的 zh 值取自 `/tmp/sen-baseline/perm1/*.html` 的**实际渲染文本**，不是源码
 * 字面量；读模型层的 zh 值是字符串常量，不经 JSX 规范化，直接取自 `model/`。
 * 跨行 JSX 的换行会渲染成一个空格，照抄源码会丢空格导致 DOM 不等价。
 *
 * ## 键名里的两个易混点
 *
 * - `account.*` / `password.*` / `setup.*` 开头的那一组是**校验消息**，键名沿用
 *   `ui/identityCopy.ts` 的原样（它的注释明确要求「消息键保持不变」）。它们与
 *   同前缀的界面文案是两套东西，判据是后者的区块名。
 * - 修改密码页用 `changePassword.*` 而不是 `password.*`：后者已经是校验消息的
 *   命名空间，页面文案挤进去会让「界面上这一句话从哪来」无法分辨。
 * - 初始化页的**步骤区块**用 `setup.stage.*`，而 `setup.step.*` 是 model 里
 *   四个步骤条目的 `label` / `description`。两者都叫 step 但不是一回事。
 */
import type { LocaleBundle } from "../../../core/i18n/types";

export const IDENTITY_COPY = {
  "zh-CN": {
    // 登录
    "login.title": "登录控制台",
    "login.description":
      "登录后查看实例运行状态、流量趋势和规则版本。演示账号：admin（可查看指标并编辑规则）、viewer（仅可查看）。",
    "login.field.username": "登录名",
    "login.field.password": "密码",
    "login.submit": "登录",

    // 账户维护
    "accounts.intro.title": "账户维护",
    "accounts.intro.description":
      "维护登录身份、状态与角色入口。密码只在后端保存，页面不展示或回显任何凭证。",
    "accounts.action.create": "新增账号",
    "accounts.panel.title": "账号列表",
    "accounts.panel.subtitle": "内置管理员不可删除；停用账号会立即拒绝新的登录请求。",
    "accounts.head.username": "账号",
    "accounts.head.role": "角色",
    "accounts.head.status": "状态",
    "accounts.head.lastLogin": "最近登录",
    "accounts.head.type": "类型",
    "accounts.head.actions": "操作",
    "accounts.type.builtInAdmin": "内置管理员账号",
    "accounts.type.normal": "普通账号",
    "accounts.type.builtIn": "内置账号",
    "accounts.status.active": "启用",
    "accounts.status.disabled": "已停用",
    "accounts.action.bindRole": "角色绑定",
    "accounts.action.changePassword": "修改密码",
    "accounts.action.disable": "停用",
    "accounts.action.enable": "启用",
    "accounts.notice.created": "账号已加入演示列表；真实环境需由后台 API 创建并审计。",
    "accounts.notice.statusChanged": "状态变更仅作用于当前演示页面，未写入服务端。",

    // 新增账号对话框
    "accountDialog.title": "新增账号",
    "accountDialog.subtitle": "创建时设置初始登录密码；服务端只保存密码哈希，页面不会回显凭证。",
    "accountDialog.action.cancel": "取消",
    "accountDialog.action.create": "创建账号",
    "accountDialog.field.username": "账号名",
    "accountDialog.field.password": "密码",
    "accountDialog.field.role": "角色",
    "accountDialog.passwordHint": "密码至少 12 位；仅提交给后台保存哈希，页面不会保存或回显凭证。",

    // 角色绑定
    "roles.intro.title": "角色绑定",
    "roles.intro.description": "角色是唯一授权入口：admin 可维护规则，view 只能查看指标和事件。",
    "roles.action.back": "返回账户维护",
    "roles.accountPanel.title": "选择账号",
    "roles.accountPanel.subtitle": "一个账号当前只绑定一个角色，避免权限组合产生歧义。",
    "roles.field.account": "账号",
    "roles.bindingPanel.title": "绑定角色",
    "roles.bindingPanel.subtitle": "修改后需要后端记录操作者、原因与生效时间。",
    "roles.field.binding": "绑定角色",
    "roles.warning": "前端选择只改变演示状态；服务端必须在每次请求重新校验权限。",
    "roles.role.admin.title": "管理员",
    "roles.role.admin.description": "查看全部运行数据，并创建、修改、发布和回滚流控规则。",
    "roles.role.view.title": "查看者",
    "roles.role.view.description": "查看总览、实例、监控和故障分析，不具备任何编辑能力。",

    // 修改密码
    "changePassword.intro.title": "修改密码",
    "changePassword.intro.description":
      "为账号 {username} 设置新的登录密码。密码只提交给后端校验，不进入 URL、日志或浏览器存储。",
    "changePassword.action.back": "返回账户维护",
    "changePassword.panel.title": "更新登录密码",
    "changePassword.panel.subtitle": "建议使用密码管理器生成唯一密码；修改成功后可使其它会话失效。",
    "changePassword.field.current": "当前密码",
    "changePassword.field.next": "新密码",
    "changePassword.field.nextHint": "至少 12 位；不要使用账号名或环境名称。",
    "changePassword.field.confirm": "确认新密码",
    "changePassword.submit": "保存新密码",
    "changePassword.success": "演示校验通过；真实环境将调用修改密码 API，不会在页面保存密码。",

    // 系统初始化
    "setup.intro.title": "初始化控制面",
    "setup.intro.description": "先建立本系统的持久化基础，再创建内置管理员并登记规则配置中心。",
    "setup.stepsLabel": "初始化步骤",
    "setup.stage.database.title": "配置系统数据库",
    "setup.stage.database.description":
      "账户、角色、审计、草稿、规则版本与发布计划需要关系数据库；活动规则仍不直接写入数据库。",
    "setup.field.database": "系统数据库",
    "setup.field.host": "主机",
    "setup.field.port": "端口",
    "setup.field.databaseName": "数据库名",
    "setup.field.username": "用户名",
    "setup.field.password": "密码",
    "setup.sqliteNote": "SQLite 数据文件会保存在服务端的受控数据目录中；浏览器不会保存数据库内容。",
    "setup.action.testConnection": "测试连接并准备数据结构",
    "setup.stage.admin.title": "创建内置管理员",
    "setup.stage.admin.description": "该账号是首个 admin；系统不会生成、展示或保留任何默认密码。",
    "setup.field.adminUsername": "账号名",
    "setup.field.adminPassword": "管理员密码",
    "setup.field.adminConfirm": "确认管理员密码",
    "setup.stage.source.title": "登记规则配置中心",
    "setup.stage.source.description": "选择本次部署的首个规则来源；稍后可在系统管理中补充另一个来源。",
    "setup.field.ruleSource": "规则来源",
    "setup.field.serviceAddress": "服务地址",
    "setup.field.namespace": "命名空间 / 数据中心",
    "setup.field.authenticationMode": "认证方式",
    "setup.field.credentialReference": "部署凭证引用",
    "setup.placeholder.nacos": "例如：secret://sentinel/nacos-prod",
    "setup.placeholder.consul": "例如：secret://sentinel/consul-prod",
    "setup.credentialReferenceHint":
      "填写密钥管理系统、Kubernetes Secret 或部署配置中的引用地址；不要填写密码、Token 或私钥。",
    "setup.directNote":
      "适用于受控内网。凭证只会通过 TLS 写入式提交给后台；浏览器不会保存、回显或再次读取它。",
    "setup.field.nacosUsername": "Nacos 用户名",
    "setup.field.nacosPassword": "Nacos 密码",
    "setup.field.consulToken": "Consul ACL Token",
    "setup.noneNote":
      "将以匿名方式连接 {source}。请仅在网络隔离、访问控制与 TLS 已由部署环境保障时使用。",
    "setup.stage.finish.title": "确认并完成",
    "setup.stage.finish.description": "完成后，系统写入初始化状态、创建内置管理员并开放登录与控制台 API。",
    "setup.summary.databaseLabel": "系统存储",
    "setup.summary.databaseProduction": "{label}（生产可用）",
    "setup.summary.databaseLocal": "{label}（本地开发）",
    "setup.summary.adminLabel": "内置账号",
    "setup.summary.adminValue": "{username} · admin",
    "setup.summary.ruleSource": "规则来源",
    "setup.warning":
      "初始化是一次性受保护操作。生产环境必须由部署侧提供启动密钥或受管密钥，服务端不得以明文文件保存数据库口令。",
    "setup.action.back": "上一步",
    "setup.action.finish": "完成初始化",
    "setup.action.next": "下一步",
    "setup.info.connectionTested":
      "演示连接检查通过；真实服务会建立连接、执行迁移并返回 requestId。",

    // 初始化选项（读模型层：产品常量，此处只放语言键）
    "setup.option.postgres.description": "生产环境支持，用于可靠的控制面持久化。",
    "setup.option.mysql.description": "生产环境支持，要求 MySQL 8.0+；MariaDB 需作为独立兼容项评估。",
    "setup.option.sqlite.description": "仅限本地体验或单机开发，不作为生产集群存储。",
    "setup.option.nacos.description": "管理服务通过受控写回流程发布完整规则快照。",
    "setup.option.consul.description": "与 Nacos 同为规则事实来源，不作为账户或审计存储。",
    "setup.option.credentialReference.label": "使用部署凭证引用",
    "setup.option.credentialReference.description":
      "由密钥管理系统、Kubernetes Secret 或部署配置向服务端提供凭证。",
    "setup.option.direct.label": "在控制台填写凭证",
    "setup.option.direct.description":
      "适用于受控内网；凭证仅写入式提交给后台，不会在页面再次展示。",
    "setup.option.none.label": "不启用认证",
    "setup.option.none.description":
      "仅用于已隔离且明确允许匿名访问的配置中心；仍建议启用 TLS。",
    "setup.step.database.label": "系统存储",
    "setup.step.database.description": "验证数据库连接并创建控制面数据结构。",
    "setup.step.admin.label": "内置管理员",
    "setup.step.admin.description": "创建唯一的首个 admin；系统不提供默认密码。",
    "setup.step.source.label": "规则来源",
    "setup.step.source.description": "登记 Nacos 或 Consul，规则仍由配置中心权威持有。",
    "setup.step.finish.label": "完成初始化",
    "setup.step.finish.description": "记录初始化结果，开放登录与控制台 API。",

    // 校验消息（键名沿用 ui/identityCopy.ts 原样）
    "account.credentialsRequired": "请填写账号名和密码。",
    "account.passwordTooShort": "密码至少 {min} 位，并应包含多种字符类型。",
    "account.loginRequired": "请输入登录名和密码。",
    "password.tooShort": "新密码至少 {min} 位，并应包含多种字符类型。",
    "password.mismatch": "两次输入的新密码不一致。",
    "setup.adminRequired": "请填写管理员信息，并设置至少 {min} 位的密码。",
    "setup.adminPasswordMismatch": "两次输入的管理员密码不一致。",
    "setup.credentialReferenceRequired":
      "请填写部署凭证引用，或选择直接填写凭证 / 不启用认证。",
    "setup.nacosCredentialsRequired": "请填写 Nacos 用户名和密码。",
    "setup.consulTokenRequired": "请填写 Consul ACL Token。",
  },
  "en-US": {
    "login.title": "Sign in to the console",
    "login.description":
      "After signing in you can review instance status, traffic trends and rule versions. Demo accounts: admin (view metrics and edit rules), viewer (read-only).",
    "login.field.username": "Username",
    "login.field.password": "Password",
    "login.submit": "Sign in",

    "accounts.intro.title": "Account maintenance",
    "accounts.intro.description":
      "Maintain sign-in identities, status and role entry points. Passwords are only kept on the server; this page never displays or echoes credentials.",
    "accounts.action.create": "Add account",
    "accounts.panel.title": "Account list",
    "accounts.panel.subtitle":
      "The built-in administrator cannot be deleted; disabling an account immediately rejects new sign-in requests.",
    "accounts.head.username": "Account",
    "accounts.head.role": "Role",
    "accounts.head.status": "Status",
    "accounts.head.lastLogin": "Last sign-in",
    "accounts.head.type": "Type",
    "accounts.head.actions": "Actions",
    "accounts.type.builtInAdmin": "Built-in administrator account",
    "accounts.type.normal": "Regular account",
    "accounts.type.builtIn": "Built-in",
    "accounts.status.active": "Active",
    "accounts.status.disabled": "Disabled",
    "accounts.action.bindRole": "Bind role",
    "accounts.action.changePassword": "Change password",
    "accounts.action.disable": "Disable",
    "accounts.action.enable": "Enable",
    "accounts.notice.created":
      "The account was added to the demo list; a real environment creates and audits it through a backend API.",
    "accounts.notice.statusChanged":
      "The status change only affects the current demo page and was not written to the server.",

    "accountDialog.title": "Add account",
    "accountDialog.subtitle":
      "Set the initial password on creation; the server only stores the password hash and the page never echoes credentials.",
    "accountDialog.action.cancel": "Cancel",
    "accountDialog.action.create": "Create account",
    "accountDialog.field.username": "Username",
    "accountDialog.field.password": "Password",
    "accountDialog.field.role": "Role",
    "accountDialog.passwordHint":
      "At least 12 characters; submitted to the backend which stores only the hash, never saved or echoed on this page.",

    "roles.intro.title": "Role binding",
    "roles.intro.description":
      "Roles are the only authorization entry point: admin can maintain rules, view can only read metrics and events.",
    "roles.action.back": "Back to account maintenance",
    "roles.accountPanel.title": "Select an account",
    "roles.accountPanel.subtitle":
      "An account is bound to exactly one role at a time, which avoids ambiguity from permission combinations.",
    "roles.field.account": "Account",
    "roles.bindingPanel.title": "Bind a role",
    "roles.bindingPanel.subtitle":
      "After the change the backend must record the operator, the reason and the effective time.",
    "roles.field.binding": "Bound role",
    "roles.warning":
      "The front-end selection only changes demo state; the server must re-validate permissions on every request.",
    "roles.role.admin.title": "Administrator",
    "roles.role.admin.description":
      "View all runtime data, and create, modify, publish and roll back flow-control rules.",
    "roles.role.view.title": "Viewer",
    "roles.role.view.description":
      "View the overview, instances, monitoring and incident analysis; no editing capability at all.",

    "changePassword.intro.title": "Change password",
    "changePassword.intro.description":
      "Set a new sign-in password for account {username}. The password is only submitted to the backend for validation and never enters the URL, logs or browser storage.",
    "changePassword.action.back": "Back to account maintenance",
    "changePassword.panel.title": "Update sign-in password",
    "changePassword.panel.subtitle":
      "Use a password manager to generate a unique password; after the change other sessions can be invalidated.",
    "changePassword.field.current": "Current password",
    "changePassword.field.next": "New password",
    "changePassword.field.nextHint":
      "At least 12 characters; do not reuse the account name or an environment name.",
    "changePassword.field.confirm": "Confirm new password",
    "changePassword.submit": "Save new password",
    "changePassword.success":
      "Demo validation passed; a real environment calls the change-password API and never stores the password on the page.",

    "setup.intro.title": "Initialize the control plane",
    "setup.intro.description":
      "First establish this system's persistence foundation, then create the built-in administrator and register the rule config center.",
    "setup.stepsLabel": "Initialization steps",
    "setup.stage.database.title": "Configure the system database",
    "setup.stage.database.description":
      "Accounts, roles, audit, drafts, rule versions and release plans need a relational database; active rules are still not written to it directly.",
    "setup.field.database": "System database",
    "setup.field.host": "Host",
    "setup.field.port": "Port",
    "setup.field.databaseName": "Database name",
    "setup.field.username": "Username",
    "setup.field.password": "Password",
    "setup.sqliteNote":
      "The SQLite data file is stored in the server's controlled data directory; the browser never stores database content.",
    "setup.action.testConnection": "Test connection and prepare schema",
    "setup.stage.admin.title": "Create the built-in administrator",
    "setup.stage.admin.description":
      "This account is the first admin; the system does not generate, display or retain any default password.",
    "setup.field.adminUsername": "Username",
    "setup.field.adminPassword": "Administrator password",
    "setup.field.adminConfirm": "Confirm administrator password",
    "setup.stage.source.title": "Register the rule config center",
    "setup.stage.source.description":
      "Choose the first rule source for this deployment; another source can be added later under system management.",
    "setup.field.ruleSource": "Rule source",
    "setup.field.serviceAddress": "Service address",
    "setup.field.namespace": "Namespace / datacenter",
    "setup.field.authenticationMode": "Authentication mode",
    "setup.field.credentialReference": "Deployment credential reference",
    "setup.placeholder.nacos": "e.g. secret://sentinel/nacos-prod",
    "setup.placeholder.consul": "e.g. secret://sentinel/consul-prod",
    "setup.credentialReferenceHint":
      "Enter a reference from a secret manager, Kubernetes Secret or deployment config; do not enter passwords, tokens or private keys.",
    "setup.directNote":
      "For controlled intranets. Credentials are submitted write-only to the backend over TLS; the browser never stores, echoes or re-reads them.",
    "setup.field.nacosUsername": "Nacos username",
    "setup.field.nacosPassword": "Nacos password",
    "setup.field.consulToken": "Consul ACL token",
    "setup.noneNote":
      "{source} will be connected anonymously. Use this only when network isolation, access control and TLS are already guaranteed by the deployment environment.",
    "setup.stage.finish.title": "Confirm and finish",
    "setup.stage.finish.description":
      "When finished, the system records the initialization state, creates the built-in administrator and opens sign-in and the console API.",
    "setup.summary.databaseLabel": "System storage",
    "setup.summary.databaseProduction": "{label} (production ready)",
    "setup.summary.databaseLocal": "{label} (local development)",
    "setup.summary.adminLabel": "Built-in account",
    "setup.summary.adminValue": "{username} · admin",
    "setup.summary.ruleSource": "Rule source",
    "setup.warning":
      "Initialization is a one-time protected operation. Production must supply a bootstrap key or a managed secret; the server must never store the database password as a plaintext file.",
    "setup.action.back": "Previous",
    "setup.action.finish": "Finish initialization",
    "setup.action.next": "Next",
    "setup.info.connectionTested":
      "Demo connection check passed; a real service establishes the connection, runs migrations and returns a requestId.",

    "setup.option.postgres.description": "Production ready, for reliable control-plane persistence.",
    "setup.option.mysql.description":
      "Production ready, requires MySQL 8.0+; MariaDB must be evaluated as a separate compatibility item.",
    "setup.option.sqlite.description":
      "Local experience or single-machine development only; not for production cluster storage.",
    "setup.option.nacos.description":
      "The management service publishes complete rule snapshots through a controlled write-back flow.",
    "setup.option.consul.description":
      "Like Nacos, an authoritative rule source; not used for account or audit storage.",
    "setup.option.credentialReference.label": "Use a deployment credential reference",
    "setup.option.credentialReference.description":
      "A secret manager, Kubernetes Secret or deployment config provides the credentials to the server.",
    "setup.option.direct.label": "Enter credentials in the console",
    "setup.option.direct.description":
      "For controlled intranets; credentials are submitted write-only to the backend and never shown on the page again.",
    "setup.option.none.label": "Disable authentication",
    "setup.option.none.description":
      "Only for config centers that are isolated and explicitly allow anonymous access; TLS is still recommended.",

    "setup.step.database.label": "System storage",
    "setup.step.database.description":
      "Verify the database connection and create the control-plane schema.",
    "setup.step.admin.label": "Built-in administrator",
    "setup.step.admin.description":
      "Create the single first admin; the system provides no default password.",
    "setup.step.source.label": "Rule source",
    "setup.step.source.description":
      "Register Nacos or Consul; rules remain authoritatively held by the config center.",
    "setup.step.finish.label": "Finish initialization",
    "setup.step.finish.description":
      "Record the initialization result and open sign-in and the console API.",

    "account.credentialsRequired": "Enter a username and a password.",
    "account.passwordTooShort":
      "The password needs at least {min} characters and several character classes.",
    "account.loginRequired": "Enter a username and a password.",
    "password.tooShort":
      "The new password needs at least {min} characters and several character classes.",
    "password.mismatch": "The two new passwords do not match.",
    "setup.adminRequired":
      "Enter the administrator details and set a password of at least {min} characters.",
    "setup.adminPasswordMismatch": "The two administrator passwords do not match.",
    "setup.credentialReferenceRequired":
      "Enter a deployment credential reference, or choose to enter credentials directly / disable authentication.",
    "setup.nacosCredentialsRequired": "Enter the Nacos username and password.",
    "setup.consulTokenRequired": "Enter the Consul ACL token.",
  },
  "ja-JP": {
    "login.title": "コンソールにログイン",
    "login.description":
      "ログインするとインスタンスの状態、トラフィックの推移、ルールバージョンを確認できます。デモアカウント：admin（指標閲覧とルール編集）、viewer（閲覧のみ）。",
    "login.field.username": "ログイン名",
    "login.field.password": "パスワード",
    "login.submit": "ログイン",

    "accounts.intro.title": "アカウント管理",
    "accounts.intro.description":
      "ログインの身元、状態、ロールの入口を管理します。パスワードはサーバー側だけに保存され、この画面は資格情報を表示もエコーもしません。",
    "accounts.action.create": "アカウントを追加",
    "accounts.panel.title": "アカウント一覧",
    "accounts.panel.subtitle":
      "組み込みの管理者アカウントは削除できません。無効化したアカウントは新しいログイン要求を直ちに拒否します。",
    "accounts.head.username": "アカウント",
    "accounts.head.role": "ロール",
    "accounts.head.status": "状態",
    "accounts.head.lastLogin": "最終ログイン",
    "accounts.head.type": "種別",
    "accounts.head.actions": "操作",
    "accounts.type.builtInAdmin": "組み込み管理者アカウント",
    "accounts.type.normal": "通常アカウント",
    "accounts.type.builtIn": "組み込み",
    "accounts.status.active": "有効",
    "accounts.status.disabled": "無効",
    "accounts.action.bindRole": "ロール割り当て",
    "accounts.action.changePassword": "パスワード変更",
    "accounts.action.disable": "無効化",
    "accounts.action.enable": "有効化",
    "accounts.notice.created":
      "アカウントをデモ一覧に追加しました。実環境ではバックエンド API が作成し監査します。",
    "accounts.notice.statusChanged":
      "状態の変更は現在のデモ画面にのみ反映され、サーバーには書き込まれていません。",

    "accountDialog.title": "アカウントの新規作成",
    "accountDialog.subtitle":
      "作成時に初期パスワードを設定します。サーバーはハッシュのみを保存し、この画面が資格情報をエコーすることはありません。",
    "accountDialog.action.cancel": "キャンセル",
    "accountDialog.action.create": "アカウントを作成",
    "accountDialog.field.username": "アカウント名",
    "accountDialog.field.password": "パスワード",
    "accountDialog.field.role": "ロール",
    "accountDialog.passwordHint":
      "12 文字以上。バックエンドにハッシュとしてのみ送信され、この画面には保存もエコーもされません。",

    "roles.intro.title": "ロール割り当て",
    "roles.intro.description":
      "ロールが唯一の認可の入口です：admin はルールを保守でき、view は指標とイベントを読むことしかできません。",
    "roles.action.back": "アカウント管理へ戻る",
    "roles.accountPanel.title": "アカウントを選択",
    "roles.accountPanel.subtitle":
      "1 つのアカウントに同時に割り当てられるロールは 1 つだけとし、権限の組み合わせによる曖昧さを避けます。",
    "roles.field.account": "アカウント",
    "roles.bindingPanel.title": "ロールを割り当てる",
    "roles.bindingPanel.subtitle":
      "変更後はバックエンドが実行者、理由、有効時刻を記録する必要があります。",
    "roles.field.binding": "割り当てるロール",
    "roles.warning":
      "フロントエンドでの選択はデモ状態を変えるだけです。サーバーはリクエストごとに権限を再検証しなければなりません。",
    "roles.role.admin.title": "管理者",
    "roles.role.admin.description":
      "すべての稼働データを確認し、流量制御ルールの作成・変更・公開・ロールバックを行えます。",
    "roles.role.view.title": "閲覧者",
    "roles.role.view.description":
      "概要、インスタンス、監視、障害分析を参照できますが、編集機能は一切ありません。",

    "changePassword.intro.title": "パスワードの変更",
    "changePassword.intro.description":
      "アカウント {username} の新しいログインパスワードを設定します。パスワードはバックエンドの検証にのみ送信され、URL・ログ・ブラウザストレージには入りません。",
    "changePassword.action.back": "アカウント管理へ戻る",
    "changePassword.panel.title": "ログインパスワードの更新",
    "changePassword.panel.subtitle":
      "パスワードマネージャーで一意なパスワードを生成してください。変更すると他のセッションを無効化できます。",
    "changePassword.field.current": "現在のパスワード",
    "changePassword.field.next": "新しいパスワード",
    "changePassword.field.nextHint":
      "12 文字以上。アカウント名や環境名は使わないでください。",
    "changePassword.field.confirm": "新しいパスワード（確認）",
    "changePassword.submit": "新しいパスワードを保存",
    "changePassword.success":
      "デモの検証に合格しました。実環境ではパスワード変更 API を呼び出し、この画面には保存しません。",

    "setup.intro.title": "コントロールプレーンの初期化",
    "setup.intro.description":
      "まず本システムの永続化の基盤を作り、次に組み込み管理者を作成してルールの設定センターを登録します。",
    "setup.stepsLabel": "初期化ステップ",
    "setup.stage.database.title": "システムデータベースの設定",
    "setup.stage.database.description":
      "アカウント、ロール、監査、下書き、ルールバージョン、公開計画にはリレーショナルデータベースが必要です。有効なルールは依然として直接書き込まれません。",
    "setup.field.database": "システムデータベース",
    "setup.field.host": "ホスト",
    "setup.field.port": "ポート",
    "setup.field.databaseName": "データベース名",
    "setup.field.username": "ユーザー名",
    "setup.field.password": "パスワード",
    "setup.sqliteNote":
      "SQLite のデータファイルはサーバーの管理下にあるデータディレクトリに保存されます。ブラウザがデータベースの内容を保存することはありません。",
    "setup.action.testConnection": "接続をテストしデータ構造を準備",
    "setup.stage.admin.title": "組み込み管理者の作成",
    "setup.stage.admin.description":
      "このアカウントが最初の admin です。システムが既定のパスワードを生成・表示・保持することはありません。",
    "setup.field.adminUsername": "アカウント名",
    "setup.field.adminPassword": "管理者パスワード",
    "setup.field.adminConfirm": "管理者パスワード（確認）",
    "setup.stage.source.title": "ルールの設定センターの登録",
    "setup.stage.source.description":
      "このデプロイで最初に使うルールソースを選択します。別のソースは後でシステム管理から追加できます。",
    "setup.field.ruleSource": "ルールソース",
    "setup.field.serviceAddress": "サービスアドレス",
    "setup.field.namespace": "名前空間 / データセンター",
    "setup.field.authenticationMode": "認証方式",
    "setup.field.credentialReference": "デプロイ時の資格情報参照",
    "setup.placeholder.nacos": "例：secret://sentinel/nacos-prod",
    "setup.placeholder.consul": "例：secret://sentinel/consul-prod",
    "setup.credentialReferenceHint":
      "シークレット管理、Kubernetes Secret、デプロイ設定の参照先を入力してください。パスワード・トークン・秘密鍵は入力しないでください。",
    "setup.directNote":
      "管理されたイントラネット向けです。資格情報は TLS 経由で書き込みのみバックエンドに送信され、ブラウザは保存・エコー・再取得を行いません。",
    "setup.field.nacosUsername": "Nacos ユーザー名",
    "setup.field.nacosPassword": "Nacos パスワード",
    "setup.field.consulToken": "Consul ACL トークン",
    "setup.noneNote":
      "{source} に匿名で接続します。ネットワーク分離・アクセス制御・TLS がデプロイ環境で担保されている場合のみ使用してください。",
    "setup.stage.finish.title": "確認して完了",
    "setup.stage.finish.description":
      "完了後、システムが初期化状態を記録し、組み込み管理者を作成してログインとコンソール API を開放します。",
    "setup.summary.databaseLabel": "システムストレージ",
    "setup.summary.databaseProduction": "{label}（本番利用可能）",
    "setup.summary.databaseLocal": "{label}（ローカル開発）",
    "setup.summary.adminLabel": "組み込みアカウント",
    "setup.summary.adminValue": "{username} · admin",
    "setup.summary.ruleSource": "ルールソース",
    "setup.warning":
      "初期化は一度きりの保護された操作です。本番環境ではブートストラップ鍵または管理下のシークレットをデプロイ側から提供し、サーバーがデータベースのパスワードを平文ファイルで保存してはいけません。",
    "setup.action.back": "前へ",
    "setup.action.finish": "初期化を完了",
    "setup.action.next": "次へ",
    "setup.info.connectionTested":
      "デモの接続チェックに合格しました。実サービスでは接続を確立しマイグレーションを実行して requestId を返します。",

    "setup.option.postgres.description": "本番利用可能。コントロールプレーンの永続化に信頼できる選択肢です。",
    "setup.option.mysql.description":
      "本番利用可能。MySQL 8.0+ が必要で、MariaDB は別の互換性項目として評価します。",
    "setup.option.sqlite.description":
      "ローカルでの体験や単一マシンの開発専用。本番クラスターのストレージには使いません。",
    "setup.option.nacos.description":
      "管理サービスが制御された書き戻しフローを通じて完全なルールスナップショットを公開します。",
    "setup.option.consul.description":
      "Nacos と同じくルールの事実ソースですが、アカウントや監査のストレージには使いません。",
    "setup.option.credentialReference.label": "デプロイ時の資格情報参照を使う",
    "setup.option.credentialReference.description":
      "シークレット管理、Kubernetes Secret、デプロイ設定からサーバーへ資格情報を提供します。",
    "setup.option.direct.label": "コンソールで資格情報を入力する",
    "setup.option.direct.description":
      "管理されたイントラネット向け。資格情報は書き込みのみでバックエンドに送信され、ページに再表示されません。",
    "setup.option.none.label": "認証を有効にしない",
    "setup.option.none.description":
      "隔離され匿名アクセスが明示的に許可された設定センター専用です。TLS の有効化も推奨します。",

    "setup.step.database.label": "システムストレージ",
    "setup.step.database.description":
      "データベース接続を検証し、コントロールプレーンのデータ構造を作成します。",
    "setup.step.admin.label": "組み込み管理者",
    "setup.step.admin.description": "唯一の最初の admin を作成します。システムに既定のパスワードはありません。",
    "setup.step.source.label": "ルールソース",
    "setup.step.source.description":
      "Nacos または Consul を登録します。ルールは引き続き設定センターが権威的に保持します。",
    "setup.step.finish.label": "初期化を完了",
    "setup.step.finish.description": "初期化結果を記録し、ログインとコンソール API を解放します。",

    "account.credentialsRequired": "アカウント名とパスワードを入力してください。",
    "account.passwordTooShort":
      "パスワードは {min} 文字以上とし、複数種類の文字種を含めてください。",
    "account.loginRequired": "ログイン名とパスワードを入力してください。",
    "password.tooShort":
      "新しいパスワードは {min} 文字以上とし、複数種類の文字種を含めてください。",
    "password.mismatch": "新しいパスワードが一致しません。",
    "setup.adminRequired":
      "管理者情報を入力し、{min} 文字以上のパスワードを設定してください。",
    "setup.adminPasswordMismatch": "管理者パスワードが一致しません。",
    "setup.credentialReferenceRequired":
      "デプロイ時の資格情報参照を入力するか、資格情報の直接入力 / 認証無効を選択してください。",
    "setup.nacosCredentialsRequired": "Nacos のユーザー名とパスワードを入力してください。",
    "setup.consulTokenRequired": "Consul の ACL トークンを入力してください。",
  },
} as const satisfies LocaleBundle;
