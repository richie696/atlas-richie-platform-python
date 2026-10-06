/**
 * 图表主题适配器。
 *
 * 中文
 * ----
 * Nivo 的主题**只接受具体颜色值**，不吃 CSS 自定义属性：SVG 呈现属性不是 CSS 声明，
 * `fill="var(--chart-qps)"` 不会解析。因此适配器在这里把 token 读成真实色值再交给
 * Nivo，让「产品皮肤拥有图表配色」这件事有一个明确归属，而不是散落在
 * `TrendChart` 的 `theme` 对象和三个页面手传的 `color="#ff7778"` 里。
 *
 * 读不到值时（无 DOM 的环境）回落到 {@link FALLBACK_CHART_TOKENS}，其数值与
 * `styles.css` 的 `:root` 定义逐字一致，因此回落不会改变渲染结果。
 *
 * 新增序列时：先在 `styles.css` 的 `:root` 登记 `--chart-<name>`，再在
 * {@link CHART_SERIES_COLOR} 登记取值映射，不要在页面里直接写十六进制色值。
 */

/** 一条图表序列对应的语义色键。键名与指标语义对应，不与具体色值绑定。 */
export type ChartSeriesColor = "primary" | "secondary" | "danger";

/** 图表使用的全部语义色。 */
export interface ChartTokens {
  readonly axisText: string;
  readonly axisLine: string;
  readonly gridLine: string;
  readonly crosshair: string;
  readonly tooltipBackground: string;
  readonly tooltipBorder: string;
  readonly tooltipText: string;
  /** 发布变更标记线。 */
  readonly annotationLine: string;
  readonly annotationText: string;
  /**
   * 序列色。
   *
   * 键是**语义**（primary / secondary / danger）而不是色名：调色板时不必改调用点，
   * 也避免「红色到底是 danger 还是 secondary」这种含义漂移。
   */
  readonly series: Readonly<Record<ChartSeriesColor, string>>;
}

/** 无 DOM 环境下的回退值，与 `styles.css` 的 `:root` 定义一致。 */
const FALLBACK_CHART_TOKENS: ChartTokens = Object.freeze({
  axisText: "#8499a8",
  axisLine: "transparent",
  gridLine: "#2a3c47",
  crosshair: "#d5e9f8",
  tooltipBackground: "#182a35",
  tooltipBorder: "#426075",
  tooltipText: "#eef6fc",
  annotationLine: "#62b5ff",
  annotationText: "#76bcf2",
  series: Object.freeze({
    primary: "#59adff",
    secondary: "#ffbd59",
    danger: "#ff7778",
  }),
});

const CSS_VAR_BY_TOKEN: Readonly<Record<keyof Omit<ChartTokens, "series">, string>> =
  Object.freeze({
    axisText: "--chart-axis-text",
    axisLine: "--chart-axis-line",
    gridLine: "--chart-grid-line",
    crosshair: "--chart-crosshair",
    tooltipBackground: "--chart-tooltip-bg",
    tooltipBorder: "--chart-tooltip-border",
    tooltipText: "--chart-tooltip-text",
    annotationLine: "--chart-annotation-line",
    annotationText: "--chart-annotation-text",
  });

const CSS_VAR_BY_SERIES: Readonly<Record<ChartSeriesColor, string>> = Object.freeze({
  primary: "--chart-series-primary",
  secondary: "--chart-series-secondary",
  danger: "--chart-series-danger",
});

/** 读一次并缓存：主题值在同一页面生命周期内不变，避免每帧都触发样式重算。 */
let cache: ChartTokens | null = null;

function readTokens(): ChartTokens {
  if (typeof window === "undefined" || !window.getComputedStyle) return FALLBACK_CHART_TOKENS;
  const style = window.getComputedStyle(document.documentElement);
  const readVar = (name: string, fallback: string): string => {
    const raw = style.getPropertyValue(name).trim();
    return raw.length > 0 ? raw : fallback;
  };
  const read = (name: keyof typeof CSS_VAR_BY_TOKEN): string =>
    readVar(CSS_VAR_BY_TOKEN[name], FALLBACK_CHART_TOKENS[name]);
  return Object.freeze({
    axisText: read("axisText"),
    axisLine: read("axisLine"),
    gridLine: read("gridLine"),
    crosshair: read("crosshair"),
    tooltipBackground: read("tooltipBackground"),
    tooltipBorder: read("tooltipBorder"),
    tooltipText: read("tooltipText"),
    annotationLine: read("annotationLine"),
    annotationText: read("annotationText"),
    series: Object.freeze({
      primary: readVar(CSS_VAR_BY_SERIES.primary, FALLBACK_CHART_TOKENS.series.primary),
      secondary: readVar(CSS_VAR_BY_SERIES.secondary, FALLBACK_CHART_TOKENS.series.secondary),
      danger: readVar(CSS_VAR_BY_SERIES.danger, FALLBACK_CHART_TOKENS.series.danger),
    }),
  });
}

/** 当前生效的图表 token。 */
export function chartTokens(): ChartTokens {
  cache ??= readTokens();
  return cache;
}

/** 仅供测试或主题切换后失效缓存使用。 */
export function resetChartTokenCache(): void {
  cache = null;
}

/** Nivo 需要的最小主题形状。避免为它引入整个类型依赖。 */
export interface ChartTheme {
  readonly axis: {
    readonly domain: { readonly line: { readonly stroke: string } };
    readonly ticks: {
      readonly line: { readonly stroke: string };
      readonly text: { readonly fill: string; readonly fontSize: number };
    };
  };
  readonly grid: { readonly line: { readonly stroke: string; readonly strokeWidth: number } };
  readonly crosshair: { readonly line: { readonly stroke: string; readonly strokeOpacity: number } };
  readonly tooltip: {
    readonly container: {
      readonly background: string;
      readonly border: string;
      readonly borderRadius: number;
      readonly color: string;
      readonly fontSize: number;
    };
  };
}

/** 由 token 构建 Nivo 主题。切主题时刷新样式后需配合 {@link resetChartTokenCache}。 */
export function buildChartTheme(): ChartTheme {
  const tokens = chartTokens();
  return {
    axis: {
      domain: { line: { stroke: tokens.axisLine } },
      ticks: {
        line: { stroke: tokens.axisLine },
        text: { fill: tokens.axisText, fontSize: 11 },
      },
    },
    grid: { line: { stroke: tokens.gridLine, strokeWidth: 1 } },
    crosshair: { line: { stroke: tokens.crosshair, strokeOpacity: 0.6 } },
    tooltip: {
      container: {
        background: tokens.tooltipBackground,
        border: `1px solid ${tokens.tooltipBorder}`,
        borderRadius: 8,
        color: tokens.tooltipText,
        fontSize: 12,
      },
    },
  };
}

/** 发布变更标记线的样式，读同一份 token。 */
export function annotationStyle(): {
  readonly stroke: string;
  readonly strokeWidth: number;
  readonly strokeDasharray: string;
  readonly fill: string;
  readonly fontSize: number;
  readonly fontWeight: number;
} {
  const tokens = chartTokens();
  return {
    stroke: tokens.annotationLine,
    strokeWidth: 1.5,
    strokeDasharray: "5 4",
    fill: tokens.annotationText,
    fontSize: 11,
    fontWeight: 600,
  };
}
