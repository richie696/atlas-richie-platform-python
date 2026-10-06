import { ResponsiveLine } from "@nivo/line";
import { useMemo } from "react";

import {
  annotationStyle,
  buildChartTheme,
  chartTokens,
  type ChartSeriesColor,
} from "./chartTheme";

import type { MetricKey, MetricPoint } from "../../types/dashboard";

export type TrendDomain = [string | number, string | number];
export type TrendChartProps = {
  /** 只读序列。图表不修改输入，也不生成样本。 */
  readonly data: readonly MetricPoint[];
  /** 主指标键。字面量联合，拼写错误在编译期暴露。 */
  readonly metric: MetricKey;
  /** 序列色语义键。色值由 chartTheme 从 CSS token 解析，页面不再直接传十六进制。 */
  readonly color?: ChartSeriesColor;
  readonly unit?: string;
  /** 次指标键；双轴展示时同时提供 `secondAxis` 与 `secondUnit`。 */
  readonly second?: MetricKey;
  readonly secondColor?: ChartSeriesColor;
  readonly secondAxis?: boolean;
  readonly secondUnit?: string;
  readonly marker?: boolean;
  readonly cursorTime?: string;
  readonly height?: number;
  readonly domain?: TrendDomain;
};

/**
 * Renders the Dashboard's shared operational trend treatment with Nivo Line.
 * Data and rule-release annotations are supplied by the
 * owning feature; this component does not fetch or synthesize samples.
 */
export function TrendChart({
  data,
  metric,
  color = "primary",
  unit = "",
  second,
  secondColor = "secondary",
  secondAxis = false,
  secondUnit = "",
  marker = true,
  cursorTime,
  height = 170,
  domain,
}: TrendChartProps) {
  // 主题与序列色都由 CSS token 解析。memo 一次即可：Nivo 在 theme 变化时会重算整套
  // 刻度，没必要每帧新建对象。
  const theme = useMemo(() => buildChartTheme(), []);
  const palette = chartTokens().series;
  const primaryColor = palette[color];
  const secondaryColor = palette[secondColor];
  const releaseAnnotation = useMemo(() => annotationStyle(), []);

  const primaryData = data.map((item) => item[metric]);
  const secondaryData = second ? data.map((item) => item[second]) : undefined;
  const formatValue = (value: number, valueUnit: string) => `${value >= 1000 ? `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}k` : value}${valueUnit}`;
  const primaryMin = domain && typeof domain[0] === "number" ? domain[0] : Math.min(...primaryData);
  const primaryMax = domain && typeof domain[1] === "number" ? domain[1] : Math.max(...primaryData);
  const secondaryMin = secondaryData ? Math.min(...secondaryData) : 0;
  const secondaryMax = secondaryData ? Math.max(...secondaryData) : 1;
  const primarySpan = primaryMax - primaryMin || 1;
  const secondarySpan = secondaryMax - secondaryMin || 1;
  const toPrimaryScale = (value: number) => primaryMin + ((value - secondaryMin) / secondarySpan) * primarySpan;
  const xTickStep = Math.max(1, Math.ceil(data.length / 7));
  const xTickValues = data
    .filter((_, index) => index === 0 || index === data.length - 1 || index % xTickStep === 0)
    .map((item) => item.time);
  const series = [
    { id: metric, data: data.map((item, index) => ({ x: item.time, y: primaryData[index] })), color: primaryColor },
    ...(second && secondaryData ? [{ id: second, data: data.map((item, index) => ({ x: item.time, y: secondAxis ? toPrimaryScale(secondaryData[index]) : secondaryData[index] })), color: secondaryColor }] : []),
  ];

  return (
    <div className="trend" style={{ height }}>
      <ResponsiveLine
        data={series}
        margin={{ top: 12, right: secondAxis ? 38 : 8, bottom: 28, left: 42 }}
        xScale={{ type: "point" }}
        yScale={{ type: "linear", min: primaryMin, max: primaryMax, stacked: false, reverse: false }}
        curve="monotoneX"
        colors={{ datum: "color" }}
        lineWidth={2.5}
        enableArea
        areaOpacity={0.18}
        enablePoints={false}
        enableGridX
        gridXValues={xTickValues}
        enableGridY
        axisTop={null}
        axisRight={secondAxis ? { tickSize: 0, tickPadding: 8, tickValues: 5, format: (value: number) => `${Math.round(secondaryMin + ((value - primaryMin) / primarySpan) * secondarySpan)}${secondUnit}` } : null}
        axisBottom={{ tickSize: 0, tickPadding: 9, tickRotation: 0, tickValues: xTickValues }}
        axisLeft={{ tickSize: 0, tickPadding: 8, tickRotation: 0, format: (value: number) => formatValue(value, unit), tickValues: 5 }}
        enableSlices="x"
        useMesh
        enableCrosshair
        crosshairType="x"
        animate={false}
        isInteractive
        markers={[
          ...(marker && data.some((item) => item.time === "14:02") ? [{ axis: "x" as const, value: "14:02", lineStyle: { stroke: releaseAnnotation.stroke, strokeWidth: releaseAnnotation.strokeWidth, strokeDasharray: releaseAnnotation.strokeDasharray }, textStyle: { fill: releaseAnnotation.fill, fontSize: releaseAnnotation.fontSize, fontWeight: releaseAnnotation.fontWeight }, legend: "发布变更", legendPosition: "top-right" as const, legendOrientation: "horizontal" as const }] : []),
          ...(cursorTime ? [{ axis: "x" as const, value: cursorTime || "", lineStyle: { stroke: theme.crosshair.line.stroke, strokeOpacity: 0.6, strokeWidth: 1 } }] : []),
        ]}
        theme={theme}
        tooltip={({ point }) => {
          const current = data.find((item) => item.time === String(point.data.x));
          const rawValue = current
        ? current[point.seriesId as MetricKey]
        : Number(point.data.y) || 0;
          const valueUnit = secondAxis && point.seriesId === second ? secondUnit : unit;
          return <div><strong>{String(point.data.x)}</strong><div>{String(point.seriesId).toUpperCase()}：{formatValue(rawValue, valueUnit)}</div></div>;
        }}
      />
    </div>
  );
}
