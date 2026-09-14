import { useEffect, useMemo, useState } from "react";
import { useOnlineStatus } from "@richie696/react-framework-react";
import {
  ActivityIcon as Activity,
  ArrowRightIcon as ArrowRight,
  CaretDownIcon as CaretDown,
  ChartLineUpIcon as ChartLineUp,
  CloudCheckIcon as CloudCheck,
  FloppyDiskIcon as FloppyDisk,
  GearSixIcon as GearSix,
  HardDrivesIcon as HardDrives,
  InfoIcon as Info,
  MagnifyingGlassIcon as MagnifyingGlass,
  PauseIcon as Pause,
  PlayIcon as Play,
  ShieldCheckIcon as ShieldCheck,
  SlidersHorizontalIcon as SlidersHorizontal,
  SquaresFourIcon as SquaresFour,
  StackIcon as Stack,
  WarningIcon as Warning,
} from "@phosphor-icons/react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  APPLICATIONS,
  CONNECTIONS,
  FAULT_EVENTS,
  FLEET_TREND,
  ORDER_INSTANCES,
  PAGE_ITEMS,
  RULES,
  RULESET_VERSIONS,
  TIME_RANGES,
  makeInstanceTrend,
  numberText,
  seriesForRange,
} from "./demoData";
import {
  DASHBOARD_LOCALES,
  createRuleTranslator,
  ruleMessages,
} from "./ruleI18n";
import {
  AccountMaintenancePage,
  ChangePasswordPage,
  LoginPage,
  RoleBindingPage,
  SystemInitializationPage,
} from "./features/identity/ui/IdentityPages";

const NAV_ICONS = [
  SquaresFour,
  Stack,
  SlidersHorizontal,
  Activity,
  Warning,
  GearSix,
];
const ISSUES = ORDER_INSTANCES.filter(
  (item) => item.status !== "healthy",
).length;
const AUXILIARY_PAGES = Object.freeze([
  "accounts",
  "roles",
  "change-password",
  "login",
  "setup",
]);

function initialPage() {
  const name = window.location.hash.slice(1);
  return PAGE_ITEMS.some((item) => item.id === name) || AUXILIARY_PAGES.includes(name)
    ? name
    : "overview";
}

function Status({ tone = "healthy", children }) {
  return <span className={`status status-${tone}`}>{children}</span>;
}
function LinkButton({ children, onClick }) {
  return (
    <button type="button" className="link-button" onClick={onClick}>
      {children}
      <ArrowRight size={15} />
    </button>
  );
}
function Panel({ title, subtitle, action, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
function NumberCard({ label, value, unit, note, tone = "" }) {
  return (
    <div className="number-card">
      <span>{label}</span>
      <strong>
        {value}
        <small>{unit}</small>
      </strong>
      <p className={tone}>{note}</p>
    </div>
  );
}

function Select({ label, value, onChange, options }) {
  return (
    <label className="select-control">
      <span>{label}</span>
      <span className="select-box">
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          {options.map((item) => (
            <option key={item.value ?? item} value={item.value ?? item}>
              {item.label ?? item}
            </option>
          ))}
        </select>
        <CaretDown size={14} />
      </span>
    </label>
  );
}

function Filters({
  appId,
  setAppId,
  range,
  setRange,
  all = false,
  extra,
  showRange = true,
  labels = {
    environment: "环境",
    production: "生产环境 (PROD)",
    application: "应用",
    allApplications: "全部应用",
    sample: "示例采样 · 14:32:18",
  },
}) {
  const appOptions = APPLICATIONS.map((app) => ({
    value: app.id,
    label: app.label,
  }));
  return (
    <div className="filters">
      <Select
        label={labels.environment}
        value={labels.production}
        onChange={() => {}}
        options={[labels.production]}
      />
      <Select
        label={labels.application}
        value={appId}
        onChange={setAppId}
        options={
          all
            ? [{ value: "all", label: labels.allApplications }, ...appOptions]
            : appOptions
        }
      />
      {showRange && (
        <Select
          label="时间范围"
          value={range}
          onChange={setRange}
          options={TIME_RANGES}
        />
      )}
      {extra}
      <span className="sample-age">
        <i className="live-dot" /> {labels.sample}
      </span>
    </div>
  );
}

function Trend({
  data,
  metric,
  color = "#59adff",
  unit = "",
  second,
  secondColor = "#ffbd59",
  secondAxis = false,
  secondUnit = "",
  marker = true,
  cursorTime,
  height = 170,
  domain,
}) {
  return (
    <div className="trend" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={data}
          margin={{ top: 12, right: 8, bottom: 0, left: -17 }}
        >
          <defs>
            <linearGradient
              id={`gradient-${metric}`}
              x1="0"
              x2="0"
              y1="0"
              y2="1"
            >
              <stop offset="0%" stopColor={color} stopOpacity="0.24" />
              <stop offset="100%" stopColor={color} stopOpacity="0.01" />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#2a3c47" />
          <XAxis
            dataKey="time"
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#8499a8", fontSize: 11 }}
            minTickGap={45}
          />
          <YAxis
            yAxisId="left"
            domain={domain ?? ["auto", "auto"]}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#8499a8", fontSize: 11 }}
            tickFormatter={(value) =>
              `${value >= 1000 ? `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}k` : value}${unit}`
            }
          />
          {secondAxis && (
            <YAxis
              yAxisId="right"
              orientation="right"
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#d39194", fontSize: 11 }}
              tickFormatter={(value) => `${value}${secondUnit}`}
              width={34}
            />
          )}
          <Tooltip
            contentStyle={{
              background: "#182a35",
              border: "1px solid #426075",
              borderRadius: 8,
              color: "#eef6fc",
            }}
            formatter={(value, name) => [
              `${numberText(value)}${secondAxis && name === second?.toUpperCase() ? secondUnit : unit}`,
              name,
            ]}
          />
          <Area
            yAxisId="left"
            type="monotone"
            dataKey={metric}
            name={metric.toUpperCase()}
            stroke={color}
            strokeWidth={2}
            fill={`url(#gradient-${metric})`}
            isAnimationActive={false}
          />
          {second && (
            <Line
              yAxisId={secondAxis ? "right" : "left"}
              type="monotone"
              dataKey={second}
              name={second.toUpperCase()}
              stroke={secondColor}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          )}
          {marker && data.some((item) => item.time === "14:02") && (
            <ReferenceLine
              yAxisId="left"
              x="14:02"
              stroke="#62b5ff"
              strokeDasharray="5 4"
              label={{
                value: "发布变更",
                fill: "#8ccaff",
                position: "insideTopRight",
                fontSize: 10,
              }}
            />
          )}
          {cursorTime && (
            <ReferenceLine
              yAxisId="left"
              x={cursorTime}
              stroke="#d5e9f8"
              strokeOpacity={0.6}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function Intro({ eyebrow, title, description, aside }) {
  return (
    <div className="intro">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {aside && <div className="intro-aside">{aside}</div>}
    </div>
  );
}
function Table({ heads, rows, className = "" }) {
  return (
    <div className="table-scroll">
      <table className={`data-table ${className}`}>
        <thead>
          <tr>
            {heads.map((head) => (
              <th key={head}>{head}</th>
            ))}
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  );
}

function Overview({ navigate, appId, setAppId, range, setRange }) {
  const trend = seriesForRange(FLEET_TREND, range);
  const apps =
    appId === "all"
      ? APPLICATIONS
      : APPLICATIONS.filter((app) => app.id === appId);
  return (
    <>
      <div className="overview-context">
        <Intro
          eyebrow="OPERATIONS / FLEET"
          title="全局运行概览"
          description="从应用视角了解整体流量与防护状况，快速定位需要关注的服务。"
        />
        <Filters
          appId={appId}
          setAppId={(id) =>
            id === "all" ? setAppId(id) : navigate("applications", id)
          }
          range={range}
          setRange={setRange}
          all
        />
      </div>
      <div className="overview-top">
        <div className="alert-hero">
          <span className="alert-icon">
            <Warning size={27} weight="fill" />
          </span>
          <div>
            <span className="eyebrow">NEEDS ATTENTION</span>
            <h2>
              18 个应用运行中，<em>2 个需要关注</em>
            </h2>
            <p>资源压力与阻断率上升集中在 order-service 和 payment-service。</p>
          </div>
          <button
            type="button"
            className="primary-button"
            onClick={() => navigate("applications", "order-service")}
          >
            查看异常应用 <ArrowRight size={16} />
          </button>
        </div>
        <div className="infra-card">
          <div className="card-heading">
            基础组件与规则状态 <small>均为演示状态</small>
          </div>
          <div className="infra-items">
            <div>
              <CloudCheck size={30} color="#56d6a1" />
              <b>Nacos</b>
              <small>可用 · 12 ms</small>
            </div>
            <div>
              <CloudCheck size={30} color="#56d6a1" />
              <b>Consul</b>
              <small>可用 · 18 ms</small>
            </div>
            <div>
              <ShieldCheck size={30} color="#5badff" />
              <b>规则版本下发</b>
              <small>142 / 145 · 98%</small>
            </div>
          </div>
        </div>
      </div>
      <Panel
        title="全局流量与防护趋势"
        subtitle={
          range === "最近 15 分钟"
            ? "当前窗口不含 14:02 发布时点；切换到最近 1 小时查看发布前后对比。"
            : "上下图共用时间范围；蓝色虚线标注一次示例规则发布。"
        }
        action={<span className="muted">TPS 暂无接入 · 不与 QPS 混用</span>}
        className="overview-trends"
      >
        <div className="trend-block">
          <div className="trend-title">
            <h3>总 HTTP QPS（次/秒）</h3>
            {range === "最近 15 分钟" ? (
              <span>14:17–14:32 · 示例窗口</span>
            ) : (
              <span>
                发布前 <b>24.1K</b> → 发布后 <b>17.6K</b>{" "}
                <em className="green">↓ 27%</em>
              </span>
            )}
          </div>
          <Trend data={trend} metric="qps" height={139} />
        </div>
        <div className="trend-block">
          <div className="trend-title">
            <h3>请求拦截率（Blocked Rate）</h3>
            {range === "最近 15 分钟" ? (
              <span>14:17–14:32 · 示例窗口</span>
            ) : (
              <span>
                发布前 <b>1.8%</b> → 发布后 <b>8.6%</b>{" "}
                <em className="red">↑ 6.8%</em>
              </span>
            )}
          </div>
          <Trend
            data={trend}
            metric="blocked"
            color="#ff7778"
            unit="%"
            height={139}
          />
        </div>
      </Panel>
      <Panel
        title="应用运行状态"
        subtitle="按应用聚合的关键指标，点击应用可进入实例矩阵。"
        action={
          <LinkButton onClick={() => navigate("applications", "order-service")}>
            查看全部应用
          </LinkButton>
        }
      >
        <Table
          heads={[
            "应用名称",
            "状态",
            "实例数",
            "CPU 平均",
            "内存平均",
            "HTTP QPS",
            "RT p95",
            "拦截率",
            "规则版本",
            "操作",
          ]}
          rows={apps.map((app) => (
            <tr key={app.id}>
              <td>
                <LinkButton onClick={() => navigate("applications", app.id)}>
                  {app.label}
                </LinkButton>
              </td>
              <td>
                <Status tone={app.state}>{app.stateLabel}</Status>
              </td>
              <td>
                {app.running} / {app.total}
              </td>
              <td className={app.cpu > 75 ? "red" : ""}>{app.cpu}%</td>
              <td>{app.memory}%</td>
              <td>{numberText(app.qps)}</td>
              <td className={app.rt > 350 ? "red" : ""}>{app.rt} ms</td>
              <td className={app.blocked > 10 ? "red" : ""}>{app.blocked}%</td>
              <td>{app.version}</td>
              <td>
                <LinkButton onClick={() => navigate("applications", app.id)}>
                  详情
                </LinkButton>
              </td>
            </tr>
          ))}
        />
        <p className="table-note">演示列表显示 {apps.length} / 18 个应用。</p>
      </Panel>
    </>
  );
}

function Usage({ value, tone = "blue" }) {
  return (
    <span className="usage">
      <i className={`usage-${tone}`} style={{ width: `${value}%` }} />
    </span>
  );
}
function HostRows({ host, rows, selectedId, setSelectedId }) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <tr className="host-row">
        <td colSpan={8}>
          <button type="button" onClick={() => setOpen(!open)}>
            <CaretDown size={14} className={open ? "" : "rotated"} /> {host}{" "}
            <span>({rows.length} 个实例)</span>
          </button>
        </td>
      </tr>
      {open &&
        rows.map((row) => (
          <tr
            key={row.id}
            className={`instance-row ${selectedId === row.id ? "selected" : ""} ${row.status !== "healthy" ? row.status : ""}`}
            onClick={() => setSelectedId(row.id)}
          >
            <td>
              <button type="button" onClick={() => setSelectedId(row.id)}>
                {row.id}
              </button>
            </td>
            <td>
              <Status tone={row.status}>{row.statusLabel}</Status>
            </td>
            <td>
              {row.cpu}%{" "}
              <Usage value={row.cpu} tone={row.cpu > 80 ? "red" : "blue"} />
            </td>
            <td>
              {row.memory}%{" "}
              <Usage
                value={row.memory}
                tone={row.memory > 80 ? "amber" : "blue"}
              />
            </td>
            <td>{numberText(row.qps)}</td>
            <td>{row.rt} ms</td>
            <td className={row.blocked > 1 ? "red" : ""}>
              {row.blocked.toFixed(2)}%
            </td>
            <td>{row.version}</td>
          </tr>
        ))}
    </>
  );
}
function Applications({ navigate, appId, setAppId, range, setRange }) {
  const [selectedId, setSelectedId] = useState("order-5");
  const [anomaliesOnly, setAnomaliesOnly] = useState(false);
  const [scope, setScope] = useState("容器");
  const app = APPLICATIONS.find((item) => item.id === appId) ?? APPLICATIONS[0];
  const selected =
    ORDER_INSTANCES.find((item) => item.id === selectedId) ??
    ORDER_INSTANCES[4];
  const rows = anomaliesOnly
    ? ORDER_INSTANCES.filter((item) => item.status !== "healthy")
    : ORDER_INSTANCES;
  const hosts = [...new Set(rows.map((item) => item.host))];
  const trend = useMemo(
    () => seriesForRange(makeInstanceTrend(selected), range),
    [selected, range],
  );
  return (
    <>
      <div className="application-context">
        <Intro
          eyebrow="APPLICATIONS / INSTANCES"
          title="应用与实例"
          description="先比较实例，再按宿主机、容器或进程定位资源压力与流控影响。"
        />
        <Filters
          appId={appId}
          setAppId={setAppId}
          range={range}
          setRange={setRange}
        />
      </div>
      <div className="app-hero">
        <div className="alert-hero">
          <span className="alert-icon">
            <Warning size={27} weight="fill" />
          </span>
          <div>
            <span className="eyebrow">SELECTED APPLICATION</span>
            <h2>
              {app.label} ·{" "}
              {app.id === "order-service"
                ? `12 个实例中 ${ISSUES} 个资源压力偏高`
                : app.stateLabel}
            </h2>
            <p>
              {app.id === "order-service"
                ? "两个实例出现 CPU 或内存持续高位，建议尽快处理。"
                : "此原型仅有 order-service 的实例示例，不会伪造其他应用的实例。"}
            </p>
          </div>
          <button
            className="primary-button"
            type="button"
            onClick={() => setAnomaliesOnly(true)}
          >
            查看异常实例 <ArrowRight size={16} />
          </button>
        </div>
        <div className="rule-card">
          <span>
            当前规则版本 <b>{app.version}</b>
          </span>
          <span>
            配置来源 <b>{app.provider}</b>
          </span>
          <span>
            示例生效{" "}
            <b>
              {app.running} / {app.total} 实例
            </b>
          </span>
          <LinkButton onClick={() => navigate("rules")}>
            查看规则详情
          </LinkButton>
        </div>
      </div>
      {app.id !== "order-service" && (
        <div className="inline-note">
          <Info size={16} /> 下方仍为 order-service
          的示例矩阵，应用筛选不改变这组演示数据。
        </div>
      )}
      <div className="instance-layout">
        <Panel
          title="实例健康矩阵"
          subtitle={`共 12 个示例实例，按宿主机分组 · ${anomaliesOnly ? "仅看异常" : "全部"}`}
          action={
            <label className="checkbox">
              <input
                type="checkbox"
                checked={anomaliesOnly}
                onChange={(event) => setAnomaliesOnly(event.target.checked)}
              />{" "}
              仅看异常
            </label>
          }
          className="instance-panel"
        >
          <Table
            heads={[
              "实例 / 宿主机",
              "状态",
              "容器 CPU",
              "容器内存",
              "HTTP QPS",
              "RT p95",
              "请求拦截率",
              "规则版本",
            ]}
            rows={hosts.map((host) => (
              <HostRows
                key={host}
                host={host}
                rows={rows.filter((row) => row.host === host)}
                selectedId={selectedId}
                setSelectedId={setSelectedId}
              />
            ))}
            className="instances-table"
          />
        </Panel>
        <Panel
          title={selected.id}
          subtitle={`${selected.host} · container: ${selected.id} · 示例`}
          action={
            <div className="segments">
              {["宿主机", "容器", "进程"].map((name) => (
                <button
                  type="button"
                  key={name}
                  className={scope === name ? "active" : ""}
                  onClick={() => setScope(name)}
                >
                  {name}
                </button>
              ))}
            </div>
          }
          className="detail-panel"
        >
          <div className="detail-status">
            <Status tone={selected.status}>{selected.statusLabel}</Status>
            <span>
              {scope === "容器"
                ? "容器指标 · 演示数据"
                : `${scope}指标尚无示例数据`}
            </span>
          </div>
          {scope === "容器" ? (
            <>
              <h3>
                CPU / 内存使用率{" "}
                <small>
                  <i className="dot-blue" /> CPU　
                  <i className="dot-amber" /> 内存
                </small>
              </h3>
              <Trend
                data={trend}
                metric="cpu"
                second="memory"
                unit="%"
                domain={[0, 100]}
                height={212}
              />
              <h3>
                HTTP QPS / 请求拦截率
                <small>
                  <i className="dot-blue" /> QPS　
                  <i className="dot-red" /> 拦截率
                </small>
              </h3>
              <Trend
                data={trend}
                metric="qps"
                second="blocked"
                secondColor="#ff7778"
                secondAxis
                secondUnit="%"
                height={182}
              />
            </>
          ) : (
            <div className="scope-empty">
              <Info size={20} />{" "}
              当前原型只提供容器级示例曲线；宿主机和进程指标需接入对应采集源。
            </div>
          )}
          <div className="detail-rule">
            <b>当前流控规则</b>
            <span>QPS 阈值 2,000 · 慢调用比例 20%</span>
            <LinkButton onClick={() => navigate("rules")}>查看规则</LinkButton>
          </div>
        </Panel>
      </div>
    </>
  );
}

const SentinelCode = Object.freeze({
  FLOW_GRADE_THREAD: 0,
  FLOW_GRADE_QPS: 1,
  FLOW_STRATEGY_DIRECT: 0,
  FLOW_STRATEGY_RELATE: 1,
  FLOW_STRATEGY_CHAIN: 2,
  FLOW_BEHAVIOR_REJECT: 0,
  FLOW_BEHAVIOR_WARM_UP: 1,
  FLOW_BEHAVIOR_QUEUEING: 2,
  DEGRADE_SLOW_REQUEST_RATIO: 0,
  DEGRADE_ERROR_RATIO: 1,
  DEGRADE_ERROR_COUNT: 2,
  AUTHORITY_WHITE: 0,
  AUTHORITY_BLACK: 1,
  DISABLED_SYSTEM_THRESHOLD: -1,
});

const RULE_TYPE_META = Object.freeze({
  flow: {
    className: "FlowRule",
    configName: "flow-rules",
  },
  degrade: {
    className: "DegradeRule",
    configName: "degrade-rules",
  },
  system: {
    className: "SystemRule",
    configName: "system-rules",
  },
  authority: {
    className: "AuthorityRule",
    configName: "authority-rules",
  },
  param: {
    className: "ParamFlowRule",
    configName: "param-flow-rules",
  },
});

const FLOW_GRADE_OPTIONS = Object.freeze([
  { value: SentinelCode.FLOW_GRADE_QPS, label: "QPS" },
  { value: SentinelCode.FLOW_GRADE_THREAD, label: "并发线程数" },
]);
const FLOW_STRATEGY_OPTIONS = Object.freeze([
  { value: SentinelCode.FLOW_STRATEGY_DIRECT, label: "直接" },
  { value: SentinelCode.FLOW_STRATEGY_CHAIN, label: "链路" },
  { value: SentinelCode.FLOW_STRATEGY_RELATE, label: "关联" },
]);
const FLOW_BEHAVIOR_OPTIONS = Object.freeze([
  { value: SentinelCode.FLOW_BEHAVIOR_REJECT, label: "直接拒绝" },
  { value: SentinelCode.FLOW_BEHAVIOR_WARM_UP, label: "慢启动" },
  { value: SentinelCode.FLOW_BEHAVIOR_QUEUEING, label: "排队等待" },
]);
const DEGRADE_OPTIONS = Object.freeze([
  { value: SentinelCode.DEGRADE_SLOW_REQUEST_RATIO, label: "慢调用比例" },
  { value: SentinelCode.DEGRADE_ERROR_RATIO, label: "异常比例" },
  { value: SentinelCode.DEGRADE_ERROR_COUNT, label: "异常数" },
]);
const AUTHORITY_OPTIONS = Object.freeze([
  { value: SentinelCode.AUTHORITY_WHITE, label: "白名单" },
  { value: SentinelCode.AUTHORITY_BLACK, label: "黑名单" },
]);
const DEFAULT_CLUSTER_CONFIG = Object.freeze({
  thresholdType: 0,
  fallbackToLocalWhenFail: true,
  sampleCount: 10,
  windowIntervalMs: 1000,
});

function cloneRule(rule) {
  return JSON.parse(JSON.stringify(rule));
}

function RuleField({ label, hint, children }) {
  return (
    <label className="rule-field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

function RuleInput({
  label,
  hint,
  value,
  onChange,
  disabled,
  numeric = false,
}) {
  return (
    <RuleField label={label} hint={hint}>
      <input
        type={numeric ? "number" : "text"}
        inputMode={numeric ? "decimal" : undefined}
        value={value ?? ""}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </RuleField>
  );
}

function RuleSelect({ label, hint, value, options, onChange, disabled }) {
  return (
    <RuleField label={label} hint={hint}>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </RuleField>
  );
}

function RuleToggle({ label, hint, checked, onChange, disabled }) {
  return (
    <label className="rule-toggle">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>
        <b>{label}</b>
        {hint && <small>{hint}</small>}
      </span>
    </label>
  );
}

function localizedOptions(options, labels) {
  return options.map((option, index) => ({ ...option, label: labels[index] }));
}

function validationErrors(ruleType, rule, t) {
  const errors = [];
  if (ruleType !== "system" && !String(rule.resource ?? "").trim())
    errors.push(t("rules.errors.resourceRequired"));
  if (["flow", "param"].includes(ruleType) && !(Number(rule.count) > 0))
    errors.push(t("rules.errors.countPositive"));
  if (
    ruleType === "flow" &&
    rule.strategy !== SentinelCode.FLOW_STRATEGY_DIRECT &&
    !String(rule.refResource ?? "").trim()
  )
    errors.push(t("rules.errors.referenceRequired"));
  if (ruleType === "degrade") {
    if (!(Number(rule.count) > 0) || !(Number(rule.timeWindow) > 0))
      errors.push(t("rules.errors.degradePositive"));
    if (
      rule.grade === SentinelCode.DEGRADE_SLOW_REQUEST_RATIO &&
      !(
        Number(rule.slowRatioThreshold) > 0 &&
        Number(rule.slowRatioThreshold) <= 1
      )
    )
      errors.push(t("rules.errors.slowRatio"));
  }
  if (
    ruleType === "param" &&
    (!Number.isInteger(Number(rule.paramIdx)) || Number(rule.paramIdx) < 0)
  )
    errors.push(t("rules.errors.parameterIndex"));
  if (ruleType === "authority" && !String(rule.limitApp ?? "").trim())
    errors.push(t("rules.errors.originsRequired"));
  if (
    ruleType === "system" &&
    ["highestSystemLoad", "avgRt", "maxThread", "qps", "highestCpuUsage"].every(
      (field) => Number(rule[field]) === SentinelCode.DISABLED_SYSTEM_THRESHOLD,
    )
  )
    errors.push(t("rules.errors.systemEnabled"));
  return errors;
}

function RuleEditor({ type, rule, editable, onChange, messages }) {
  const disabled = !editable;
  const fields = messages.fields;
  const typeMessages = messages.types[type];
  const update = (field, value) => onChange({ ...rule, [field]: value });
  const updateNumber = (field, value) =>
    update(field, value === "" ? "" : Number(value));
  const updateCluster = (field, value) =>
    update("clusterConfig", { ...rule.clusterConfig, [field]: value });
  const systemValue = (field) =>
    rule[field] === SentinelCode.DISABLED_SYSTEM_THRESHOLD ? "" : rule[field];
  const updateSystem = (field, value) =>
    update(
      field,
      value === "" ? SentinelCode.DISABLED_SYSTEM_THRESHOLD : Number(value),
    );

  if (type === "flow") {
    const supportsRefResource =
      rule.strategy !== SentinelCode.FLOW_STRATEGY_DIRECT;
    const isWarmUp =
      rule.controlBehavior === SentinelCode.FLOW_BEHAVIOR_WARM_UP;
    const isQueueing =
      rule.controlBehavior === SentinelCode.FLOW_BEHAVIOR_QUEUEING;
    const setClusterMode = (enabled) =>
      onChange(
        enabled
          ? {
              ...rule,
              clusterMode: true,
              clusterConfig:
                rule.clusterConfig ?? cloneRule(DEFAULT_CLUSTER_CONFIG),
            }
          : { ...rule, clusterMode: false },
      );
    return (
      <div className="rule-form">
        <p className="form-description">{typeMessages.description}</p>
        <div className="rule-form-grid">
          <RuleInput
            label={fields.resourceName.label}
            hint={fields.resourceName.hint}
            value={rule.resource}
            onChange={(value) => update("resource", value)}
            disabled={disabled}
          />
          <RuleInput
            label={fields.callerOrigin.label}
            hint={fields.callerOrigin.hint}
            value={rule.limitApp}
            onChange={(value) => update("limitApp", value)}
            disabled={disabled}
          />
          <RuleSelect
            label={fields.thresholdType.label}
            hint={fields.thresholdType.hint}
            value={rule.grade}
            options={localizedOptions(
              FLOW_GRADE_OPTIONS,
              messages.options.flowGrade,
            )}
            onChange={(value) => update("grade", value)}
            disabled={disabled}
          />
          <RuleInput
            label={fields.singleNodeThreshold.label}
            hint={fields.singleNodeThreshold.hint}
            value={rule.count}
            onChange={(value) => updateNumber("count", value)}
            disabled={disabled}
            numeric
          />
          <RuleSelect
            label={fields.controlStrategy.label}
            hint={fields.controlStrategy.hint}
            value={rule.strategy}
            options={localizedOptions(
              FLOW_STRATEGY_OPTIONS,
              messages.options.flowStrategy,
            )}
            onChange={(value) => update("strategy", value)}
            disabled={disabled}
          />
          <RuleSelect
            label={fields.controlBehavior.label}
            hint={fields.controlBehavior.hint}
            value={rule.controlBehavior}
            options={localizedOptions(
              FLOW_BEHAVIOR_OPTIONS,
              messages.options.flowBehavior,
            )}
            onChange={(value) => update("controlBehavior", value)}
            disabled={disabled}
          />
          {supportsRefResource && (
            <RuleInput
              label={fields.relatedResource.label}
              hint={fields.relatedResource.hint}
              value={rule.refResource ?? ""}
              onChange={(value) => update("refResource", value)}
              disabled={disabled}
            />
          )}
          {isWarmUp && (
            <RuleInput
              label={fields.warmUpPeriod.label}
              hint={fields.warmUpPeriod.hint}
              value={rule.warmUpPeriodSec ?? ""}
              onChange={(value) => updateNumber("warmUpPeriodSec", value)}
              disabled={disabled}
              numeric
            />
          )}
          {isQueueing && (
            <RuleInput
              label={fields.maxQueueingTime.label}
              hint={fields.maxQueueingTime.hint}
              value={rule.maxQueueingTimeMs ?? ""}
              onChange={(value) => updateNumber("maxQueueingTimeMs", value)}
              disabled={disabled}
              numeric
            />
          )}
        </div>
        <div className="advanced-rule-section">
          <RuleToggle
            label={fields.clusterMode.label}
            hint={fields.clusterMode.hint}
            checked={Boolean(rule.clusterMode)}
            onChange={setClusterMode}
            disabled={disabled}
          />
          {rule.clusterMode && (
            <div className="rule-form-grid cluster-grid">
              <RuleInput
                label={fields.clusterThresholdType.label}
                hint={fields.clusterThresholdType.hint}
                value={rule.clusterConfig?.thresholdType ?? ""}
                onChange={(value) =>
                  updateCluster("thresholdType", Number(value))
                }
                disabled={disabled}
                numeric
              />
              <RuleToggle
                label={fields.localFallback.label}
                hint={fields.localFallback.hint}
                checked={Boolean(rule.clusterConfig?.fallbackToLocalWhenFail)}
                onChange={(value) =>
                  updateCluster("fallbackToLocalWhenFail", value)
                }
                disabled={disabled}
              />
              <RuleInput
                label={fields.sampleCount.label}
                hint={fields.sampleCount.hint}
                value={rule.clusterConfig?.sampleCount ?? ""}
                onChange={(value) =>
                  updateCluster("sampleCount", Number(value))
                }
                disabled={disabled}
                numeric
              />
              <RuleInput
                label={fields.statisticWindow.label}
                hint={fields.statisticWindow.hint}
                value={rule.clusterConfig?.windowIntervalMs ?? ""}
                onChange={(value) =>
                  updateCluster("windowIntervalMs", Number(value))
                }
                disabled={disabled}
                numeric
              />
            </div>
          )}
        </div>
      </div>
    );
  }

  if (type === "degrade") {
    const isSlowRequest =
      rule.grade === SentinelCode.DEGRADE_SLOW_REQUEST_RATIO;
    return (
      <div className="rule-form">
        <p className="form-description">{typeMessages.description}</p>
        <div className="rule-form-grid">
          <RuleInput
            label={fields.resourceName.label}
            hint={fields.resourceName.hint}
            value={rule.resource}
            onChange={(value) => update("resource", value)}
            disabled={disabled}
          />
          <RuleSelect
            label={fields.circuitStrategy.label}
            hint={fields.circuitStrategy.hint}
            value={rule.grade}
            options={localizedOptions(
              DEGRADE_OPTIONS,
              messages.options.degrade,
            )}
            onChange={(value) => update("grade", value)}
            disabled={disabled}
          />
          <RuleInput
            label={fields.circuitThreshold.label}
            hint={fields.circuitThreshold.hint}
            value={rule.count}
            onChange={(value) => updateNumber("count", value)}
            disabled={disabled}
            numeric
          />
          <RuleInput
            label={fields.breakDuration.label}
            hint={fields.breakDuration.hint}
            value={rule.timeWindow}
            onChange={(value) => updateNumber("timeWindow", value)}
            disabled={disabled}
            numeric
          />
          <RuleInput
            label={fields.minimumRequests.label}
            hint={fields.minimumRequests.hint}
            value={rule.minRequestAmount}
            onChange={(value) => updateNumber("minRequestAmount", value)}
            disabled={disabled}
            numeric
          />
          <RuleInput
            label={fields.statisticWindow.label}
            hint={fields.statisticWindow.hint}
            value={rule.statIntervalMs}
            onChange={(value) => updateNumber("statIntervalMs", value)}
            disabled={disabled}
            numeric
          />
          {isSlowRequest && (
            <RuleInput
              label={fields.slowCallRatio.label}
              hint={fields.slowCallRatio.hint}
              value={rule.slowRatioThreshold ?? ""}
              onChange={(value) => updateNumber("slowRatioThreshold", value)}
              disabled={disabled}
              numeric
            />
          )}
        </div>
      </div>
    );
  }

  if (type === "system") {
    return (
      <div className="rule-form">
        <p className="form-description">
          {typeMessages.description} {messages.rules.systemDisabled}
        </p>
        <div className="rule-form-grid">
          <RuleInput
            label={fields.systemLoad.label}
            hint={fields.systemLoad.hint}
            value={systemValue("highestSystemLoad")}
            onChange={(value) => updateSystem("highestSystemLoad", value)}
            disabled={disabled}
            numeric
          />
          <RuleInput
            label={fields.averageRt.label}
            hint={fields.averageRt.hint}
            value={systemValue("avgRt")}
            onChange={(value) => updateSystem("avgRt", value)}
            disabled={disabled}
            numeric
          />
          <RuleInput
            label={fields.maximumThreads.label}
            hint={fields.maximumThreads.hint}
            value={systemValue("maxThread")}
            onChange={(value) => updateSystem("maxThread", value)}
            disabled={disabled}
            numeric
          />
          <RuleInput
            label={fields.entranceQps.label}
            hint={fields.entranceQps.hint}
            value={systemValue("qps")}
            onChange={(value) => updateSystem("qps", value)}
            disabled={disabled}
            numeric
          />
          <RuleInput
            label={fields.cpuUsage.label}
            hint={fields.cpuUsage.hint}
            value={systemValue("highestCpuUsage")}
            onChange={(value) => updateSystem("highestCpuUsage", value)}
            disabled={disabled}
            numeric
          />
        </div>
      </div>
    );
  }

  if (type === "authority") {
    return (
      <div className="rule-form">
        <p className="form-description">{typeMessages.description}</p>
        <div className="rule-form-grid">
          <RuleInput
            label={fields.resourceName.label}
            hint={fields.resourceName.hint}
            value={rule.resource}
            onChange={(value) => update("resource", value)}
            disabled={disabled}
          />
          <RuleSelect
            label={fields.authorityMode.label}
            hint={fields.authorityMode.hint}
            value={rule.strategy}
            options={localizedOptions(
              AUTHORITY_OPTIONS,
              messages.options.authority,
            )}
            onChange={(value) => update("strategy", value)}
            disabled={disabled}
          />
          <RuleInput
            label={fields.originList.label}
            hint={fields.originList.hint}
            value={rule.limitApp}
            onChange={(value) => update("limitApp", value)}
            disabled={disabled}
          />
        </div>
      </div>
    );
  }

  const paramItems = rule.paramFlowItemList ?? [];
  const updateParamItem = (index, field, value) =>
    update(
      "paramFlowItemList",
      paramItems.map((item, itemIndex) =>
        itemIndex === index ? { ...item, [field]: value } : item,
      ),
    );
  return (
    <div className="rule-form">
      <p className="form-description">{typeMessages.description}</p>
      <div className="rule-form-grid">
        <RuleInput
          label={fields.resourceName.label}
          hint={fields.resourceName.hint}
          value={rule.resource}
          onChange={(value) => update("resource", value)}
          disabled={disabled}
        />
        <RuleSelect
          label={fields.thresholdType.label}
          hint={fields.thresholdType.hint}
          value={rule.grade}
          options={localizedOptions(
            FLOW_GRADE_OPTIONS,
            messages.options.flowGrade,
          )}
          onChange={(value) => update("grade", value)}
          disabled={disabled}
        />
        <RuleInput
          label={fields.singleNodeThreshold.label}
          hint={fields.singleNodeThreshold.hint}
          value={rule.count}
          onChange={(value) => updateNumber("count", value)}
          disabled={disabled}
          numeric
        />
        <RuleInput
          label={fields.statisticPeriod.label}
          hint={fields.statisticPeriod.hint}
          value={rule.durationInSec}
          onChange={(value) => updateNumber("durationInSec", value)}
          disabled={disabled}
          numeric
        />
        <RuleInput
          label={fields.parameterIndex.label}
          hint={fields.parameterIndex.hint}
          value={rule.paramIdx}
          onChange={(value) => updateNumber("paramIdx", value)}
          disabled={disabled}
          numeric
        />
      </div>
      <div className="param-exceptions">
        <div className="param-exceptions-head">
          <b>{fields.parameterExceptions.label}</b>
          <button
            type="button"
            className="text-button"
            disabled={disabled}
            onClick={() =>
              update("paramFlowItemList", [
                ...paramItems,
                {
                  classType: "java.lang.String",
                  object: "",
                  count: rule.count,
                },
              ])
            }
          >
            {messages.rules.addException}
          </button>
        </div>
        {paramItems.map((item, index) => (
          <div className="param-item" key={`${item.object}-${index}`}>
            <RuleInput
              label={fields.parameterType.label}
              hint={fields.parameterType.hint}
              value={item.classType}
              onChange={(value) => updateParamItem(index, "classType", value)}
              disabled={disabled}
            />
            <RuleInput
              label={fields.parameterValue.label}
              hint={fields.parameterValue.hint}
              value={item.object}
              onChange={(value) => updateParamItem(index, "object", value)}
              disabled={disabled}
            />
            <RuleInput
              label={fields.exceptionThreshold.label}
              hint={fields.exceptionThreshold.hint}
              value={item.count}
              onChange={(value) =>
                updateParamItem(
                  index,
                  "count",
                  value === "" ? "" : Number(value),
                )
              }
              disabled={disabled}
              numeric
            />
            <button
              type="button"
              className="icon-text-button"
              disabled={disabled}
              onClick={() =>
                update(
                  "paramFlowItemList",
                  paramItems.filter((_, itemIndex) => itemIndex !== index),
                )
              }
            >
              {messages.rules.remove}
            </button>
          </div>
        ))}
      </div>
      <div className="compatibility-note">
        <Info size={15} /> {messages.rules.paramCompatibility}
      </div>
    </div>
  );
}

function VersionPlan({ messages }) {
  const [message, setMessage] = useState("");
  const labels = messages.rules.versions;
  const toneFor = {
    active: "healthy",
    scheduled: "blue",
    superseded: "info",
  };
  return (
    <Panel
      title={labels.title}
      subtitle={labels.subtitle}
      action={
        <button
          type="button"
          className="secondary-button"
          onClick={() =>
            setMessage(`${labels.previewOnly} ${labels.immutable}`)
          }
        >
          {labels.createVersion}
        </button>
      }
      className="version-plan-panel"
    >
      <div className="version-plan-list">
        {RULESET_VERSIONS.map((version) => (
          <article
            className={`version-plan version-${version.state}`}
            key={version.id}
          >
            <div className="version-marker" aria-hidden="true" />
            <div className="version-main">
              <div className="version-heading">
                <b>{version.name}</b>
                <code>{version.id}</code>
                <Status tone={toneFor[version.state]}>
                  {labels[version.state]}
                </Status>
              </div>
              <span>
                {version.summary} · {version.source} · {version.checksum}
              </span>
            </div>
            {version.state === "scheduled" ? (
              <div className="version-window">
                <span>
                  {labels.plannedWindow} · {labels.timeZone}
                </span>
                <b>
                  {version.startsAt} → {version.endsAt}
                </b>
                <small>
                  {labels.returnTo}: {version.restoreVersion}
                </small>
              </div>
            ) : (
              <div className="version-window">
                <span>{labels.publishedAt}</span>
                <b>{version.publishedAt}</b>
                <small>
                  {version.state === "active"
                    ? labels.noEnd
                    : labels.effectiveWindow}
                </small>
              </div>
            )}
          </article>
        ))}
      </div>
      {message && <div className="version-note">{message}</div>}
    </Panel>
  );
}

function Rules({ appId, setAppId, range, setRange, locale }) {
  const messages = ruleMessages(locale);
  const t = createRuleTranslator(locale);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [selectedId, setSelectedId] = useState(RULES[0].id);
  const [draftRule, setDraftRule] = useState(() =>
    cloneRule(RULES[0].sentinelRule),
  );
  const [draft, setDraft] = useState(false);
  const [message, setMessage] = useState("");
  const shown = RULES.filter(
    (item) =>
      (appId === "all" || item.app === appId) &&
      (kind === "all" || item.ruleType === kind) &&
      `${item.resource} ${item.strategy}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const selected = shown.find((item) => item.id === selectedId) ?? null;
  function choose(item) {
    setSelectedId(item.id);
    setDraftRule(cloneRule(item.sentinelRule));
    setDraft(false);
    setMessage("");
  }
  function validate() {
    const errors = validationErrors(selected.ruleType, draftRule, t);
    setMessage(
      errors.length > 0 ? errors.join(" ") : t("rules.validationPassed"),
    );
  }
  return (
    <>
      <Intro
        eyebrow={t("rules.eyebrow")}
        title={t("rules.title")}
        description={t("rules.description")}
        aside={<Status tone="blue">{t("rules.sourceOfTruth")}</Status>}
      />
      <Filters
        appId={appId}
        setAppId={setAppId}
        range={range}
        setRange={setRange}
        all
        showRange={false}
        labels={messages.rules.filters}
      />
      <div className="rule-headline">
        <ShieldCheck size={24} color="#56d6a1" />
        <div>
          <b>{t("rules.headline")}</b>
          <p>{t("rules.headlineDetail")}</p>
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={() => {
            setDraft(true);
            setMessage("");
          }}
        >
          {t("rules.editSample")}
        </button>
      </div>
      <VersionPlan messages={messages} />
      <div className="rules-layout">
        <Panel
          title={t("rules.catalog")}
          subtitle={t("rules.catalogDetail", { count: shown.length })}
          action={
            <div className="rule-filters">
              <label className="search">
                <MagnifyingGlass size={16} />
                <input
                  aria-label={t("rules.search")}
                  placeholder={t("rules.search")}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              <select
                aria-label={t("rules.allTypes")}
                value={kind}
                onChange={(event) => setKind(event.target.value)}
              >
                <option value="all">{t("rules.allTypes")}</option>
                {Object.entries(messages.types).map(([type, metadata]) => (
                  <option key={type} value={type}>
                    {metadata.label}
                  </option>
                ))}
              </select>
            </div>
          }
        >
          <Table
            heads={[
              t("rules.resourceAndType"),
              t("rules.policy"),
              t("rules.threshold"),
              t("rules.source"),
              t("rules.status"),
            ]}
            rows={shown.map((item) => (
              <tr
                key={item.id}
                className={selectedId === item.id ? "selected" : ""}
                onClick={() => choose(item)}
              >
                <td>
                  <button
                    type="button"
                    className="resource-button"
                    onClick={() => choose(item)}
                  >
                    {item.resource}
                    <small>{messages.types[item.ruleType].label}</small>
                  </button>
                </td>
                <td>{item.strategy}</td>
                <td>{item.threshold}</td>
                <td>
                  <Status tone={item.provider === "Nacos" ? "blue" : "purple"}>
                    {item.provider}
                  </Status>
                </td>
                <td>
                  <Status>{t("rules.active")}</Status>
                </td>
              </tr>
            ))}
          />
          {shown.length === 0 && (
            <div className="empty">{t("rules.search")}：0</div>
          )}
        </Panel>
        {selected ? (
          <Panel
            title={draft ? t("rules.draft") : t("rules.details")}
            subtitle={
              draft ? t("rules.draftDescription") : t("rules.detailDescription")
            }
            className="rule-inspector"
          >
            <div className="key-value">
              <span>{t("rules.resource")}</span>
              <b>{selected.resource}</b>
            </div>
            <div className="key-value">
              <span>{t("rules.provider")}</span>
              <b>{selected.provider}</b>
            </div>
            <div className="key-value">
              <span>{t("rules.baseline")}</span>
              <b>{selected.version}</b>
            </div>
            <div className="key-value">
              <span>{t("rules.scope")}</span>
              <b>
                {t("rules.scopeExample", {
                  scope: messages.rules.scopes[selected.scope],
                })}
              </b>
            </div>
            <div className="key-value">
              <span>{t("rules.compatibilityType")}</span>
              <b>{RULE_TYPE_META[selected.ruleType].className}</b>
            </div>
            <div className="divider" />
            <div className="rule-format-header">
              <div>
                <b>
                  {t("rules.configuration", {
                    type: messages.types[selected.ruleType].label,
                  })}
                </b>
                <span>{messages.types[selected.ruleType].description}</span>
              </div>
              {!draft && (
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setDraft(true)}
                >
                  {t("rules.editDraft")}
                </button>
              )}
            </div>
            <RuleEditor
              type={selected.ruleType}
              rule={draftRule}
              editable={draft}
              messages={messages}
              onChange={(nextRule) => {
                setDraftRule(nextRule);
                setDraft(true);
                setMessage("");
              }}
            />
            <div className="compatibility-json">
              <div>
                <b>{t("rules.configPreview")}</b>
                <span>
                  {t("rules.jsonArray", {
                    name: RULE_TYPE_META[selected.ruleType].configName,
                  })}
                </span>
              </div>
              <pre>{JSON.stringify([draftRule], null, 2)}</pre>
            </div>
            {message && (
              <div
                className={`inline-note ${message === t("rules.validationPassed") ? "" : "invalid"}`}
              >
                {message}
              </div>
            )}
            <button
              type="button"
              className="primary-button full"
              onClick={validate}
            >
              <FloppyDisk size={16} /> {t("rules.validate")}
            </button>
            <p className="nonproduction">{t("rules.notProduction")}</p>
          </Panel>
        ) : (
          <Panel
            title={t("rules.details")}
            subtitle={t("rules.detailDescription")}
          >
            <div className="empty">{t("rules.search")}：0</div>
          </Panel>
        )}
      </div>
    </>
  );
}

function Realtime({ navigate, appId, setAppId, range, setRange }) {
  const [paused, setPaused] = useState(false);
  const [metric, setMetric] = useState("全部指标");
  const [frame, setFrame] = useState(0);
  const trend = useMemo(() => seriesForRange(FLEET_TREND, range), [range]);
  useEffect(() => {
    if (paused) return undefined;
    const timer = window.setInterval(
      () => setFrame((index) => (index + 1) % trend.length),
      1200,
    );
    return () => window.clearInterval(timer);
  }, [paused, trend]);
  const cursorTime = trend[frame % trend.length]?.time;
  const keys =
    metric === "全部指标" ? ["qps", "rt", "blocked", "cpu"] : [metric];
  const chartCards = [
    {
      key: "qps",
      title: "HTTP QPS",
      subtitle:
        range === "最近 15 分钟"
          ? "当前窗口请求量（无发布时点）"
          : "整体请求量与规则发布时点",
      color: "#59adff",
    },
    {
      key: "rt",
      title: "RT p95",
      subtitle: "尾部响应时间，单位 ms",
      color: "#ffbd59",
    },
    {
      key: "blocked",
      title: "请求拦截率",
      subtitle: "被 Sentinel 拒绝的请求占比",
      color: "#ff7778",
      unit: "%",
    },
    {
      key: "cpu",
      title: "CPU 与内存使用率",
      subtitle: "示例应用资源压力",
      color: "#59adff",
      unit: "%",
      second: "memory",
    },
  ];
  return (
    <>
      <Intro
        eyebrow="LIVE / TELEMETRY"
        title="实时监控"
        description="用同一时间轴观察流量、响应时间、拦截与资源压力的先后关系。"
        aside={
          <Status tone={paused ? "warning" : "healthy"}>
            {paused ? "回放已暂停" : "示例回放"}
          </Status>
        }
      />
      <Filters
        appId={appId}
        setAppId={(id) =>
          id === "all" ? setAppId(id) : navigate("applications", id)
        }
        range={range}
        setRange={setRange}
        all
        extra={
          <Select
            label="指标"
            value={metric}
            onChange={setMetric}
            options={[
              { value: "全部指标", label: "全部指标" },
              { value: "qps", label: "HTTP QPS" },
              { value: "rt", label: "RT p95" },
              { value: "blocked", label: "拦截率" },
              { value: "cpu", label: "CPU" },
            ]}
          />
        }
      />
      <div className="monitor-bar">
        <div>
          <i className="live-dot" />
          <b>{range} · 示例曲线回放</b>
          <span>光标移动仅演示交互，未连接实时数据流</span>
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={() => setPaused(!paused)}
        >
          {paused ? <Play size={16} /> : <Pause size={16} />}
          {paused ? "继续回放" : "暂停回放"}
        </button>
      </div>
      <div className="number-grid">
        <NumberCard
          label="HTTP QPS"
          value="17.6K"
          unit="次/秒"
          note="↓ 27% · 相对发布前"
          tone="green"
        />
        <NumberCard
          label="RT p95"
          value="188"
          unit="ms"
          note="↑ 86 ms · 需要排查"
          tone="red"
        />
        <NumberCard
          label="请求拦截率"
          value="8.6"
          unit="%"
          note="↑ 6.8% · 相对发布前"
          tone="red"
        />
        <NumberCard
          label="CPU 平均使用率"
          value="62"
          unit="%"
          note="↑ 14% · 进程资源"
          tone="amber"
        />
      </div>
      <div className="monitor-grid">
        {chartCards
          .filter((item) => keys.includes(item.key))
          .map((item) => (
            <Panel key={item.key} title={item.title} subtitle={item.subtitle}>
              <Trend
                data={trend}
                cursorTime={cursorTime}
                metric={item.key}
                color={item.color}
                unit={item.unit}
                second={item.second}
                domain={item.key === "cpu" ? [0, 100] : undefined}
                height={240}
              />
            </Panel>
          ))}
      </div>
      <div className="bottom-note">
        <Info size={18} /> TPS 需由业务成功交易事件定义并单独接入，不能由 HTTP
        QPS 推算。
        <LinkButton onClick={() => navigate("faults")}>查看关联故障</LinkButton>
      </div>
    </>
  );
}

function Faults({ navigate, appId, setAppId, range, setRange }) {
  const [severity, setSeverity] = useState("all");
  const [selectedId, setSelectedId] = useState(FAULT_EVENTS[0].id);
  const scopeEvents = FAULT_EVENTS.filter(
    (item) =>
      (appId === "all" || item.app === appId) &&
      (range !== "最近 15 分钟" || item.at >= "14:17:00"),
  );
  const events = scopeEvents.filter(
    (item) => severity === "all" || item.severity === severity,
  );
  const selected =
    events.find((item) => item.id === selectedId) ?? events[0] ?? null;
  const criticalCount = scopeEvents.filter(
    (item) => item.severity === "critical",
  ).length;
  const warningCount = scopeEvents.filter(
    (item) => item.severity === "warning",
  ).length;
  const releaseCount = scopeEvents.filter(
    (item) => item.kind === "规则发布",
  ).length;
  const affectedApps = new Set(scopeEvents.map((item) => item.app)).size;
  return (
    <>
      <Intro
        eyebrow="DIAGNOSIS / INCIDENTS"
        title="故障分析"
        description="把压力、响应变慢、拦截升高和规则发布放到同一条证据时间线上。"
        aside={<Status tone="critical">{criticalCount} 个严重事件</Status>}
      />
      <Filters
        appId={appId}
        setAppId={setAppId}
        range={range}
        setRange={setRange}
        all
      />
      <div className="number-grid">
        <NumberCard
          label="严重事件"
          value={criticalCount}
          note="需要处理"
          tone="red"
        />
        <NumberCard
          label="警告事件"
          value={warningCount}
          note="持续观察"
          tone="amber"
        />
        <NumberCard label="规则变更" value={releaseCount} note="当前筛选窗口" />
        <NumberCard label="影响应用" value={affectedApps} note="当前筛选窗口" />
      </div>
      <div className="fault-layout">
        <Panel
          title="事件时间线"
          subtitle="示例事件按发生时间倒序排列"
          action={
            <select
              value={severity}
              aria-label="事件级别"
              onChange={(event) => setSeverity(event.target.value)}
            >
              <option value="all">全部级别</option>
              <option value="critical">严重</option>
              <option value="warning">警告</option>
              <option value="info">信息</option>
            </select>
          }
        >
          <div className="events">
            {events.map((item) => (
              <button
                type="button"
                className={`event ${selected?.id === item.id ? "active" : ""}`}
                key={item.id}
                onClick={() => setSelectedId(item.id)}
              >
                <i className={`event-dot ${item.severity}`} />
                <span>{item.at}</span>
                <div>
                  <b>{item.title}</b>
                  <small>
                    {item.app} · {item.kind}
                  </small>
                </div>
                <ArrowRight size={16} />
              </button>
            ))}
          </div>
          {events.length === 0 && (
            <div className="empty">当前筛选条件下没有示例事件。</div>
          )}
        </Panel>
        {selected ? (
          <Panel
            title="事件证据"
            subtitle="先确认事实，再判断相关性；时间接近不等于因果关系。"
            className="event-detail"
          >
            <Status tone={selected.severity}>
              {selected.severity === "critical"
                ? "严重"
                : selected.severity === "warning"
                  ? "警告"
                  : "信息"}
            </Status>
            <h2>{selected.title}</h2>
            <div className="key-value">
              <span>发生时间</span>
              <b>2026-09-14 {selected.at}</b>
            </div>
            <div className="key-value">
              <span>影响应用</span>
              <b>{selected.app}</b>
            </div>
            <div className="key-value">
              <span>关联实例</span>
              <b>{selected.instance}</b>
            </div>
            <div className="divider" />
            <h3>观测事实</h3>
            <p>{selected.detail}</p>
            <h3>建议下一步</h3>
            <p>{selected.action}</p>
            <div className="inline-note">
              <Info size={16} /> 关联为示例，不提供自动根因断言。
            </div>
            <LinkButton onClick={() => navigate("applications", selected.app)}>
              查看应用与实例
            </LinkButton>
          </Panel>
        ) : (
          <Panel title="事件证据" subtitle="选择事件查看观测事实与建议动作。">
            <div className="empty">暂无可展示的事件证据。</div>
          </Panel>
        )}
      </div>
    </>
  );
}

function System({ navigate }) {
  const [tab, setTab] = useState("连接与采集");
  return (
    <>
      <Intro
        eyebrow="ADMIN / SYSTEM"
        title="系统管理"
        description="检查配置中心、指标采集和事件上报边界，保持运维权限简单明确。"
        aside={<Status tone="blue">演示环境 · 无凭证操作</Status>}
      />
      <div className="tabs" role="group" aria-label="系统管理分类">
        {["连接与采集", "权限与审计", "协议与版本", "账户维护", "角色绑定"].map((name) => (
          <button
            type="button"
            aria-pressed={tab === name}
            className={tab === name ? "active" : ""}
            key={name}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </div>
      {tab === "连接与采集" && (
        <>
          <div className="number-grid">
            <NumberCard
              label="配置中心"
              value="2 / 2"
              note="Nacos 与 Consul（示例）"
              tone="green"
            />
            <NumberCard
              label="采样覆盖率"
              value="100"
              unit="%"
              note="演示指标"
            />
            <NumberCard
              label="规则生效覆盖"
              value="98"
              unit="%"
              note="142 / 145 实例（示例）"
            />
            <NumberCard
              label="采集链路"
              value="未连接"
              note="真实 Collector 尚未接入"
              tone="amber"
            />
          </div>
          <Panel
            title="连接与能力状态"
            subtitle="配置中心读写、指标与事件上报是不同链路；下列状态均为示例。"
          >
            <Table
              heads={["组件", "状态", "延迟", "覆盖", "用途", "能力边界"]}
              rows={CONNECTIONS.map((item) => (
                <tr key={item.name}>
                  <td>
                    <b>{item.name}</b>
                  </td>
                  <td>
                    <Status tone={item.state === "可用" ? "healthy" : "blue"}>
                      {item.state}
                    </Status>
                  </td>
                  <td>{item.latency}</td>
                  <td>{item.scope}</td>
                  <td>{item.purpose}</td>
                  <td>{item.capability}</td>
                </tr>
              ))}
            />
          </Panel>
          <div className="bottom-note">
            <Info size={18} /> 真正的 Nacos / Consul
            健康检查、条件写入和回滚能力需由独立管理服务实现。
            <LinkButton onClick={() => navigate("rules")}>
              查看规则工作台
            </LinkButton>
          </div>
        </>
      )}
      {tab === "权限与审计" && (
        <div className="system-grid">
          <Panel
            title="最小权限模型"
            subtitle="只区分查看与修改规则，不引入多租户 RBAC。"
          >
            <div className="permission">
              <ShieldCheck size={23} />
              <div>
                <b>观察者</b>
                <p>
                  metrics:view ·
                  可查看总览、应用实例、实时指标、故障事件与规则详情。
                </p>
              </div>
              <Status tone="blue">只读</Status>
            </div>
            <div className="identity-shortcuts">
              <button className="secondary-button" type="button" onClick={() => navigate("accounts")}>账户维护</button>
              <button className="secondary-button" type="button" onClick={() => navigate("roles")}>角色绑定</button>
              <button className="link-button" type="button" onClick={() => navigate("login")}>打开登录页 <ArrowRight size={15} /></button>
            </div>
            <div className="permission">
              <SlidersHorizontal size={23} />
              <div>
                <b>规则维护者</b>
                <p>
                  rules:write · 可提交规则变更；生产流程仍需基准版本校验与审计。
                </p>
              </div>
              <Status tone="warning">可变更</Status>
            </div>
          </Panel>
          <Panel title="发布审计链" subtitle="本原型不产生真实发布记录。">
            <div className="audit-flow">
              {[
                ["01", "编辑并校验", "schema、阈值、影响范围"],
                ["02", "生成差异", "基准版本、操作者、理由"],
                ["03", "条件写回", "Nacos / Consul 成功确认"],
                ["04", "观察生效", "各实例版本与失败项"],
              ].map(([step, title, detail]) => (
                <div key={step}>
                  <span>{step}</span>
                  <b>{title}</b>
                  <small>{detail}</small>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      )}
      {tab === "账户维护" && <AccountMaintenancePage navigate={navigate} />}
      {tab === "角色绑定" && <RoleBindingPage navigate={navigate} />}
      {tab === "协议与版本" && (
        <div className="system-grid">
          <Panel title="协议边界" subtitle="控制面与观测面独立演进。">
            <div className="protocol">
              <CloudCheck size={23} />
              <div>
                <b>规则配置</b>
                <p>Nacos / Consul 为权威规则源；Dashboard 通过管理服务写入。</p>
              </div>
            </div>
            <div className="protocol">
              <Activity size={23} />
              <div>
                <b>Agent Reporting</b>
                <p>上报实例版本、健康与事件，不参与准入决策。</p>
              </div>
            </div>
            <div className="protocol">
              <HardDrives size={23} />
              <div>
                <b>Cluster Token</b>
                <p>负责配额决策，与规则编辑和事件上报分离。</p>
              </div>
            </div>
          </Panel>
          <Panel title="版本与状态" subtitle="示例值不代表部署环境现状。">
            <div className="key-value">
              <span>界面状态</span>
              <b>设计原型</b>
            </div>
            <div className="key-value">
              <span>配置中心写回</span>
              <b>未实现</b>
            </div>
            <div className="key-value">
              <span>真实指标数据</span>
              <b>未连接</b>
            </div>
            <div className="key-value">
              <span>实时事件</span>
              <b>未连接</b>
            </div>
            <div className="inline-note">
              <Info size={16} /> 正式交付前需分开验证
              UI、管理服务、配置中心和实例生效闭环。
            </div>
          </Panel>
        </div>
      )}
    </>
  );
}

export function App() {
  const [page, setPage] = useState(initialPage);
  const [appId, setAppId] = useState("all");
  const [range, setRange] = useState("最近 1 小时");
  const [locale, setLocale] = useState("zh-CN");
  const [identityAccountId, setIdentityAccountId] = useState("account-admin");
  const online = useOnlineStatus();
  const shell = ruleMessages(locale).shell;
  useEffect(() => {
    const handler = () => setPage(initialPage());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  function navigate(next, nextApp) {
    if (nextApp && (next === "applications" || next === "overview")) {
      setAppId(nextApp);
    }
    if ((next === "roles" || next === "change-password") && nextApp) {
      setIdentityAccountId(nextApp);
    }
    window.location.hash = next;
    setPage(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function onNav(next) {
    if (next === "applications" && appId === "all") setAppId("order-service");
    if (next === "overview" || next === "realtime") setAppId("all");
    navigate(next);
  }
  if (page === "login") {
    return <LoginPage navigate={navigate} />;
  }
  if (page === "setup") {
    return <SystemInitializationPage navigate={navigate} />;
  }
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">
            <ChartLineUp size={23} weight="bold" />
          </span>
          <span>
            Atlas Richie <strong>Sentinel</strong>
          </span>
        </div>
        <nav className="main-nav" aria-label={shell.language}>
          {PAGE_ITEMS.map((item, index) => {
            const Icon = NAV_ICONS[index];
            return (
              <button
                key={item.id}
                type="button"
                className={page === item.id ? "active" : ""}
                onClick={() => onNav(item.id)}
              >
                <Icon size={16} />
                <span>{shell.navigation[index]}</span>
              </button>
            );
          })}
        </nav>
        <div className="header-info">
          <label className="locale-control">
            <span>{shell.language}</span>
            <select
              value={locale}
              onChange={(event) => setLocale(event.target.value)}
            >
              {DASHBOARD_LOCALES.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <span className={online ? "" : "offline-state"}>
            <i className="live-dot" /> {online ? shell.online : shell.offline}
          </span>
          <span className="clock">2026-09-14 14:32（示例）</span>
          <button className="avatar" type="button" onClick={() => navigate("accounts")} aria-label="打开账户维护">LD</button>
        </div>
      </header>
      <div className="demo-banner" role="status">
        <Info size={16} weight="fill" />
        <span>
          <b>{shell.demo}</b> · {shell.demoNotice}
        </span>
      </div>
      <main className={`content page-${page}`}>
        {page === "overview" && (
          <Overview
            navigate={navigate}
            appId={appId}
            setAppId={setAppId}
            range={range}
            setRange={setRange}
          />
        )}
        {page === "applications" && (
          <Applications
            navigate={navigate}
            appId={appId === "all" ? "order-service" : appId}
            setAppId={setAppId}
            range={range}
            setRange={setRange}
          />
        )}
        {page === "rules" && (
          <Rules
            appId={appId}
            setAppId={setAppId}
            range={range}
            setRange={setRange}
            locale={locale}
          />
        )}
        {page === "realtime" && (
          <Realtime
            navigate={navigate}
            appId={appId}
            setAppId={setAppId}
            range={range}
            setRange={setRange}
          />
        )}
        {page === "faults" && (
          <Faults
            navigate={navigate}
            appId={appId}
            setAppId={setAppId}
            range={range}
            setRange={setRange}
          />
        )}
        {page === "system" && <System navigate={navigate} />}
        {page === "accounts" && <AccountMaintenancePage navigate={navigate} />}
        {page === "roles" && <RoleBindingPage navigate={navigate} selectedAccountId={identityAccountId} />}
        {page === "change-password" && <ChangePasswordPage navigate={navigate} accountId={identityAccountId} />}
      </main>
      <footer className="footer">
        Atlas Richie Sentinel · Dashboard 设计原型{" "}
        <span>示例数据仅用于交互与布局评审</span>
      </footer>
    </div>
  );
}
