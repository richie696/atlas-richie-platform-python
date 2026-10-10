import { lazy, Suspense, useCallback, useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { MetricKey } from "../../types/dashboard";
import type { TranslationKey } from "../../types/translation";
import { scopedClasses } from "../styles/scopedClasses";
import { annotationStyle, buildChartTheme, type ChartSeriesColor } from "./chartTheme";
import { useChartTokens } from "./ChartThemeProvider";
import {
  buildTrendPlot,
  formatTrendTime,
  formatTrendValue,
  trendTickValues,
  trendEventCoordinate,
  type TrendDomain,
  type TrendPoint,
} from "./trendPlot";
import trendChartStyles from "./TrendChart.module.scss";

const styleModules = [trendChartStyles] as const;
const ResponsiveLine = lazy(async () => {
  const { ResponsiveLine: NivoResponsiveLine } = await import("@nivo/line");
  return { default: NivoResponsiveLine };
});
const METRIC_LABEL_KEY: Readonly<Record<MetricKey, TranslationKey>> = Object.freeze({
  qps: "shell.chart.metric.qps",
  rt: "shell.chart.metric.rt",
  blocked: "shell.chart.metric.blocked",
  cpu: "shell.chart.metric.cpu",
  memory: "shell.chart.metric.memory",
  tps: "observation.metric.tps",
  entryRate: "observation.metric.entryRate",
  memoryBytes: "observation.metric.memoryBytes",
});
export type { TrendDomain } from "./trendPlot";

/** An actual feature-owned event; this renderer never invents a release time or event name. */
export interface TrendAnnotation {
  readonly time: string | number;
  readonly label: string;
}
export interface TrendChartProps {
  /** Immutable presentation observations; null/absent/nonfinite values create visible gaps. */
  readonly data: readonly TrendPoint[];
  readonly metric: MetricKey;
  readonly color?: ChartSeriesColor;
  readonly unit?: string;
  readonly second?: MetricKey;
  readonly secondColor?: ChartSeriesColor;
  readonly secondAxis?: boolean;
  readonly secondUnit?: string;
  /** Only annotations with identities inside this window are rendered. */
  readonly annotations?: readonly TrendAnnotation[];
  readonly cursorTime?: string;
  readonly height?: number;
  readonly domain?: TrendDomain;
  /** Exact timestamp window, [from,to), independently of the first/last available samples. */
  readonly timeWindow?: TrendDomain;
  readonly timeZone?: string;
}

/** Shared Nivo operational treatment: rendering, accessible observations and skin projection only. */
export function TrendChart({
  data,
  metric,
  color = "primary",
  unit = "",
  second,
  secondColor = "secondary",
  secondAxis = false,
  secondUnit = "",
  annotations = [],
  cursorTime,
  height = 170,
  domain,
  timeWindow,
  timeZone,
}: TrendChartProps) {
  const { t, i18n } = useTranslation();
  const summaryId = useId();
  const [width, setWidth] = useState(0);
  const onResize = useCallback(
    (dimensions: { width: number; height: number }) => setWidth(dimensions.width),
    [],
  );
  const tokens = useChartTokens();
  const theme = useMemo(() => buildChartTheme(tokens), [tokens]);
  const annotation = useMemo(() => annotationStyle(tokens), [tokens]);
  const plot = useMemo(
    () => buildTrendPlot(data, metric, second, secondAxis, domain),
    [data, metric, second, secondAxis, domain],
  );
  const pointById = new Map(plot.points.map((point) => [point.id, point]));
  const locale = i18n.resolvedLanguage ?? i18n.language;
  const dayFormat = new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    timeZone,
  });
  const includeDate =
    new Set(
      plot.points.flatMap((point) =>
        typeof point.time === "number" ? [dayFormat.format(point.time)] : [],
      ),
    ).size > 1;
  const timeLabel = (id: string) =>
    formatTrendTime(pointById.get(id)?.time ?? id, locale, includeDate, timeZone);
  const valueLabel = (value: number | null, valueUnit: string) =>
    value === null ? t("shell.chart.missing") : formatTrendValue(value, locale, valueUnit);
  const metricLabel = (key: MetricKey) => t(METRIC_LABEL_KEY[key]);
  const primaryCount = plot.points.filter((point) => point.primary !== null).length;
  const secondaryCount = plot.points.filter((point) => point.secondary !== null).length;
  const hasSamples = primaryCount > 0 || (second !== undefined && secondaryCount > 0);
  const secondValueUnit = secondAxis ? secondUnit : unit;
  const coordinate = (id: string) => (plot.xDomain ? Number(id) : id);
  const leftMargin = includeDate ? 52 : 48;
  const rightMargin = secondAxis ? 64 : includeDate ? 52 : 32;
  const ticks = trendTickValues(plot, width - leftMargin - rightMargin, includeDate ? 100 : 60).map(
    coordinate,
  );
  const series = [
    {
      id: metric,
      color: tokens.series[color],
      data: plot.points.map((point) => ({ x: coordinate(point.id), y: point.primary })),
    },
    ...(second
      ? [
          {
            id: second,
            color: tokens.series[secondColor],
            data: plot.points.map((point) => ({ x: coordinate(point.id), y: point.secondaryY })),
          },
        ]
      : []),
  ];
  const axisSpan = plot.domain[1] - plot.domain[0];
  const secondarySpan = plot.secondaryDomain[1] - plot.secondaryDomain[0];

  return (
    <div className={scopedClasses(styleModules, "trend")}>
      <div className={scopedClasses(styleModules, "plot")} style={{ height }}>
        {plot.problem || !hasSamples ? (
          <p className={scopedClasses(styleModules, "chart-empty")} role="status">
            {t(plot.problem ? "shell.chart.invalid" : "shell.chart.empty")}
          </p>
        ) : (
          <Suspense
            fallback={
              <p className={scopedClasses(styleModules, "chart-empty")} role="status">
                {t("shell.chart.loading")}
              </p>
            }
          >
            <ResponsiveLine
              data={series}
              onResize={onResize}
              margin={{
                top: 12,
                right: rightMargin,
                bottom: includeDate ? 42 : 28,
                left: leftMargin,
              }}
              xScale={
                plot.xDomain
                  ? {
                      type: "linear",
                      min: timeWindow?.[0] ?? plot.xDomain[0],
                      max: timeWindow?.[1] ?? plot.xDomain[1],
                    }
                  : { type: "point" }
              }
              yScale={{
                type: "linear",
                min: plot.domain[0],
                max: plot.domain[1],
                stacked: false,
                reverse: false,
              }}
              curve="monotoneX"
              colors={{ datum: "color" }}
              lineWidth={2.5}
              enableArea
              areaBaselineValue={plot.domain[0]}
              areaOpacity={0.18}
              enablePoints={primaryCount === 1 || (second !== undefined && secondaryCount === 1)}
              pointSize={6}
              enableGridX
              gridXValues={ticks}
              enableGridY
              axisTop={null}
              axisRight={
                secondAxis && second
                  ? {
                      tickSize: 0,
                      tickPadding: 8,
                      tickValues: 5,
                      format: (value: number) =>
                        formatTrendValue(
                          plot.secondaryDomain[0] +
                            ((value - plot.domain[0]) / axisSpan) * secondarySpan,
                          locale,
                          secondUnit,
                          true,
                        ),
                    }
                  : null
              }
              axisBottom={{
                tickSize: 0,
                tickPadding: 9,
                tickValues: ticks,
                format: (value) => timeLabel(String(value)),
              }}
              axisLeft={{
                tickSize: 0,
                tickPadding: 8,
                tickValues: 5,
                format: (value: number) => formatTrendValue(value, locale, unit, true),
              }}
              enableSlices="x"
              enableCrosshair
              crosshairType="x"
              animate={false}
              isInteractive
              role="img"
              ariaLabel={[metricLabel(metric), ...(second ? [metricLabel(second)] : [])].join(
                " / ",
              )}
              ariaDescribedBy={summaryId}
              markers={[
                ...annotations.flatMap((event) => {
                  const at = trendEventCoordinate(event.time, plot, timeWindow);
                  return at === null
                    ? []
                    : [
                        {
                          axis: "x" as const,
                          value: at,
                          lineStyle: {
                            stroke: annotation.stroke,
                            strokeWidth: annotation.strokeWidth,
                            strokeDasharray: annotation.strokeDasharray,
                          },
                          textStyle: {
                            fill: annotation.fill,
                            fontSize: annotation.fontSize,
                            fontWeight: annotation.fontWeight,
                          },
                          legend: event.label,
                          legendPosition: "top-right" as const,
                          legendOrientation: "horizontal" as const,
                        },
                      ];
                }),
                ...(cursorTime && pointById.has(cursorTime)
                  ? [
                      {
                        axis: "x" as const,
                        value: coordinate(cursorTime),
                        lineStyle: { stroke: tokens.crosshair, strokeOpacity: 0.6, strokeWidth: 1 },
                      },
                    ]
                  : []),
              ]}
              theme={theme}
              sliceTooltip={({ slice }) => {
                const point = pointById.get(String(slice.points[0]?.data.x));
                if (!point) return null;
                return (
                  <div
                    className={scopedClasses(styleModules, "chart-tooltip")}
                    style={theme.tooltip.container}
                  >
                    <strong>{timeLabel(point.id)}</strong>
                    <div style={{ color: tokens.series[color] }}>
                      {metricLabel(metric)}: {valueLabel(point.primary, unit)}
                    </div>
                    {second && (
                      <div style={{ color: tokens.series[secondColor] }}>
                        {metricLabel(second)}: {valueLabel(point.secondary, secondValueUnit)}
                      </div>
                    )}
                  </div>
                );
              }}
            />
          </Suspense>
        )}
      </div>
      <details className={scopedClasses(styleModules, "chart-observations")}>
        <summary id={summaryId}>
          {t("shell.chart.observations", {
            metric: metricLabel(metric),
            valid: primaryCount,
            total: plot.points.length,
          })}
          {second &&
            ` · ${t("shell.chart.observations", { metric: metricLabel(second), valid: secondaryCount, total: plot.points.length })}`}
        </summary>
        <div className={scopedClasses(styleModules, "chart-table-scroll")}>
          <table>
            <caption>{t("shell.chart.table")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("shell.chart.time")}</th>
                <th scope="col">
                  {metricLabel(metric)}
                  {unit}
                </th>
                {second && (
                  <th scope="col">
                    {metricLabel(second)}
                    {secondValueUnit}
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {plot.points.map((point) => (
                <tr key={point.id}>
                  <th scope="row">{timeLabel(point.id)}</th>
                  <td>{valueLabel(point.primary, unit)}</td>
                  {second && <td>{valueLabel(point.secondary, secondValueUnit)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
