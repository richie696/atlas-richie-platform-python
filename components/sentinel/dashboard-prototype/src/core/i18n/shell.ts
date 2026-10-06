/**
 * 应用壳层的文案（导航、语言名、时间范围、在线状态、原型声明）。
 *
 * 中文
 * ----
 * 归属 `core/i18n` 而非某个 feature：这些文案被所有页面共享，且只有「壳层」这一个
 * 变化原因。页面正文一律归各自 feature 目录下的 `i18n/`。
 * 归属理由见 `docs/PRE_CODING_REVIEW.md` 第 2 问。
 *
 * 键名保持 `shell.` 前缀：既保留既有调用点的键不变（避免一次迁移牵动 6 个页面），
 * 又明确它属于壳层而非某个 feature。
 */
import type { LocaleBundle } from "./types";

export const SHELL_COPY = {
  "zh-CN": {
    "shell.language": "界面语言",
    "shell.nav.overview": "总览",
    "shell.nav.applications": "应用与实例",
    "shell.nav.rules": "规则",
    "shell.nav.realtime": "实时监控",
    "shell.nav.faults": "故障分析",
    "shell.nav.system": "系统管理",
    "shell.nav.accounts": "账户维护",
    "shell.nav.roles": "角色绑定",
    "shell.nav.changePassword": "修改密码",
    "shell.nav.login": "登录",
    "shell.nav.setup": "系统初始化",
    "shell.range.last15Minutes": "最近 15 分钟",
    "shell.range.last1Hour": "最近 1 小时",
    "shell.filter.environment": "环境",
    "shell.filter.production": "生产环境 (PROD)",
    "shell.filter.application": "应用",
    "shell.filter.allApplications": "全部应用",
    "shell.filter.sample": "示例采样 · 14:32:18",
    "shell.filter.range": "时间范围",
    "shell.prototype": "设计原型",
    "shell.online": "浏览器在线",
    "shell.offline": "浏览器离线 · 仅本地演示",
    "shell.demo": "交互设计原型",
    "shell.demoNotice":
      "全部指标、应用、规则与连接状态均为示例数据；未连接生产服务或配置中心。",
  },
  "en-US": {
    "shell.language": "Language",
    "shell.nav.overview": "Overview",
    "shell.nav.applications": "Applications & instances",
    "shell.nav.rules": "Rules",
    "shell.nav.realtime": "Live monitoring",
    "shell.nav.faults": "Fault analysis",
    "shell.nav.system": "System",
    "shell.nav.accounts": "Account maintenance",
    "shell.nav.roles": "Role binding",
    "shell.nav.changePassword": "Change password",
    "shell.nav.login": "Sign in",
    "shell.nav.setup": "System setup",
    "shell.range.last15Minutes": "Last 15 minutes",
    "shell.range.last1Hour": "Last 1 hour",
    "shell.filter.environment": "Environment",
    "shell.filter.production": "Production (PROD)",
    "shell.filter.application": "Application",
    "shell.filter.allApplications": "All applications",
    "shell.filter.sample": "Sample · 14:32:18",
    "shell.filter.range": "Time range",
    "shell.prototype": "Design prototype",
    "shell.online": "Browser online",
    "shell.offline": "Browser offline · local demo only",
    "shell.demo": "Interactive design prototype",
    "shell.demoNotice":
      "All metrics, applications, rules, and connection states are sample data; no production service or configuration center is connected.",
  },
  "ja-JP": {
    "shell.language": "表示言語",
    "shell.nav.overview": "概要",
    "shell.nav.applications": "アプリケーションとインスタンス",
    "shell.nav.rules": "ルール",
    "shell.nav.realtime": "リアルタイム監視",
    "shell.nav.faults": "障害分析",
    "shell.nav.system": "システム",
    "shell.nav.accounts": "アカウント管理",
    "shell.nav.roles": "ロール割り当て",
    "shell.nav.changePassword": "パスワード変更",
    "shell.nav.login": "ログイン",
    "shell.nav.setup": "システム初期化",
    "shell.range.last15Minutes": "直近 15 分",
    "shell.range.last1Hour": "直近 1 時間",
    "shell.filter.environment": "環境",
    "shell.filter.production": "本番環境 (PROD)",
    "shell.filter.application": "アプリケーション",
    "shell.filter.allApplications": "すべてのアプリケーション",
    "shell.filter.sample": "サンプル · 14:32:18",
    "shell.filter.range": "時間範囲",
    "shell.prototype": "デザインプロトタイプ",
    "shell.online": "ブラウザ接続中",
    "shell.offline": "ブラウザオフライン · ローカルデモのみ",
    "shell.demo": "インタラクティブデザインプロトタイプ",
    "shell.demoNotice":
      "すべてのメトリクス、アプリケーション、ルール、接続状態はサンプルデータです。本番サービスおよび設定センターには接続していません。",
  },
} as const satisfies LocaleBundle;
