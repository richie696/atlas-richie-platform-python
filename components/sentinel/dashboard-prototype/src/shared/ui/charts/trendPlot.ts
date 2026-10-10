import type { MetricKey } from "../../types/dashboard";
import { formatLocaleNumber } from "../../presentation/formatLocaleNumber";

/** Presentation input, not a Console wire DTO. Missing/nonfinite observations stay gaps, never zero. */
export type TrendPoint = Readonly<
  { time?: string; timestampMs?: number } & Partial<Record<MetricKey, number | null>>
>;
export type TrendDomain = readonly [number, number];
export interface TrendPlotPoint {
  readonly id: string;
  readonly time: string | number;
  readonly primary: number | null;
  readonly secondary: number | null;
  readonly secondaryY: number | null;
}
export interface TrendPlot {
  readonly points: readonly TrendPlotPoint[];
  readonly domain: TrendDomain;
  readonly secondaryDomain: TrendDomain;
  readonly ticks: readonly string[];
  /** Epoch-millisecond extent for a proportional time axis; absent for legacy display labels. */
  readonly xDomain?: TrendDomain;
  readonly problem: "ambiguous_time" | "invalid_time" | "invalid_domain" | "invalid_metric" | null;
}

const EMPTY_DOMAIN: TrendDomain = Object.freeze([0, 1]);
const SINGLE_TIMESTAMP_PADDING_MS = 30_000;
const finiteValue = (value: number | null | undefined): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

function extent(values: readonly (number | null)[]): TrendDomain {
  let min = Infinity,
    max = -Infinity;
  for (const value of values)
    if (value !== null) {
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
  if (min === Infinity) return EMPTY_DOMAIN;
  if (min !== max) return [min, max];
  const padding = Math.max(Math.abs(min) * 0.05, 1);
  return [min - padding, max + padding];
}
function validDomain(domain: TrendDomain): boolean {
  return (
    domain.every(Number.isFinite) && domain[0] < domain[1] && Number.isFinite(domain[1] - domain[0])
  );
}

/** Pure plot projection: validate identity, preserve gaps, share a common axis or explicitly normalize a second one. */
export function buildTrendPlot(
  data: readonly TrendPoint[],
  metric: MetricKey,
  second?: MetricKey,
  secondAxis = false,
  domain?: TrendDomain,
): TrendPlot {
  const failed = (problem: TrendPlot["problem"]): TrendPlot => ({
    points: [],
    domain: EMPTY_DOMAIN,
    secondaryDomain: EMPTY_DOMAIN,
    ticks: [],
    problem,
  });
  const points: Omit<TrendPlotPoint, "secondaryY">[] = [];
  if (second === metric) return failed("invalid_metric");
  const seen = new Set<string>();
  const timestamped = data.some((point) => point.timestampMs !== undefined);
  let previous = -Infinity;
  for (const point of data) {
    const time = timestamped ? point.timestampMs : point.time;
    if (typeof time !== "number" && typeof time !== "string") return failed("invalid_time");
    if (
      timestamped
        ? typeof time !== "number" ||
          !Number.isSafeInteger(time) ||
          !Number.isFinite(new Date(time).getTime()) ||
          time < previous
        : typeof time !== "string" || time.trim() === ""
    )
      return failed("invalid_time");
    const id = String(time);
    if (seen.has(id)) return failed("ambiguous_time");
    seen.add(id);
    if (typeof time === "number") previous = time;
    points.push({
      id,
      time,
      primary: finiteValue(point[metric]),
      secondary: second ? finiteValue(point[second]) : null,
    });
  }
  const primaryDomain =
    domain ??
    extent(
      points.flatMap((point) =>
        second && !secondAxis ? [point.primary, point.secondary] : [point.primary],
      ),
    );
  const secondaryDomain = extent(points.map((point) => point.secondary));
  if (!validDomain(primaryDomain) || !validDomain(secondaryDomain)) return failed("invalid_domain");
  const span = primaryDomain[1] - primaryDomain[0];
  const secondarySpan = secondaryDomain[1] - secondaryDomain[0];
  const projected = points.map((point) => ({
    ...point,
    secondaryY:
      point.secondary === null
        ? null
        : secondAxis
          ? primaryDomain[0] + ((point.secondary - secondaryDomain[0]) / secondarySpan) * span
          : point.secondary,
  }));
  if (projected.some((point) => point.secondaryY !== null && !Number.isFinite(point.secondaryY)))
    return failed("invalid_domain");
  const step = Math.max(1, Math.ceil(points.length / 7));
  const firstTime = points[0]?.time;
  const lastTime = points.at(-1)?.time;
  const xDomain: TrendDomain | undefined =
    typeof firstTime === "number" && typeof lastTime === "number"
      ? firstTime === lastTime
        ? [firstTime - SINGLE_TIMESTAMP_PADDING_MS, lastTime + SINGLE_TIMESTAMP_PADDING_MS]
        : [firstTime, lastTime]
      : undefined;
  return {
    points: projected,
    domain: primaryDomain,
    secondaryDomain,
    ticks: points
      .filter((_, index) => index === 0 || index === points.length - 1 || index % step === 0)
      .map((point) => point.id),
    problem: null,
    xDomain,
  };
}

/** Locale formats timestamps, never identities; include the calendar date when a window crosses midnight. */
export function formatTrendTime(
  time: string | number,
  locale: string,
  includeDate = false,
  timeZone?: string,
): string {
  return typeof time === "string"
    ? time
    : new Intl.DateTimeFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone,
        ...(includeDate ? { month: "2-digit", day: "2-digit" } : {}),
      }).format(time);
}

/**
 * Timestamped events may fall BETWEEN samples; never require a fabricated sample
 * at the publication time. Explicit windows are half-open. Legacy label plots
 * continue accepting only labels with a known point identity.
 */
export function trendEventCoordinate(
  time: string | number,
  plot: TrendPlot,
  timeWindow?: TrendDomain,
): string | number | null {
  if (!plot.xDomain)
    return plot.points.some((point) => point.id === String(time)) ? String(time) : null;
  const at = typeof time === "number" ? time : Number(time);
  const extent = timeWindow ?? plot.xDomain;
  if (
    !Number.isSafeInteger(at) ||
    !Number.isFinite(new Date(at).getTime()) ||
    at < extent[0] ||
    (timeWindow ? at >= extent[1] : at > extent[1])
  )
    return null;
  return at;
}

/** Units are supplied by the metric owner; numbers use the active locale without changing the sample. */
export function formatTrendValue(
  value: number,
  locale: string,
  unit: string,
  compact = false,
): string {
  return `${formatLocaleNumber(value, locale, {
    maximumFractionDigits: 2,
    ...(compact ? { notation: "compact" } : {}),
  })}${unit}`;
}

/** Select ticks by available pixel spacing; keep endpoints without crowding irregular timestamp samples. */
export function trendTickValues(
  plot: TrendPlot,
  width: number,
  minimumGap: number,
): readonly string[] {
  if (plot.points.length <= 1) return plot.points.map((point) => point.id);
  const first = plot.points[0];
  const last = plot.points[plot.points.length - 1];
  if (width <= 0) return [first.id, last.id];
  const position = (point: TrendPlotPoint, index: number) =>
    plot.xDomain
      ? ((Number(point.time) - plot.xDomain[0]) / (plot.xDomain[1] - plot.xDomain[0])) * width
      : (index / (plot.points.length - 1)) * width;
  const ticks = [first.id];
  let previous = 0;
  for (let index = 1; index < plot.points.length - 1; index++) {
    const x = position(plot.points[index], index);
    if (x - previous >= minimumGap && width - x >= minimumGap) {
      ticks.push(plot.points[index].id);
      previous = x;
    }
  }
  ticks.push(last.id);
  return ticks;
}
