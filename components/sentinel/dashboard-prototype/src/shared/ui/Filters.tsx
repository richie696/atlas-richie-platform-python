import type { ReactNode } from "react";

import { createRuleTranslator } from "../../ruleI18n";
import {
  ALL_APPLICATIONS,
  TIME_RANGES,
  TIME_RANGE_LABEL_KEY,
  type TimeRangeId,
} from "../../app/router/route.constants";
import { Select } from "./Select";

/**
 * 跨页共用的筛选条（环境 / 应用 / 时间范围）。
 *
 * 中文
 * ----
 * 时间范围传的是协议值（`15m` / `1h`），下拉标签由 `TIME_RANGE_LABEL_KEY` 经语言
 * 资源解析。旧实现把中文文案「最近 15 分钟」直接当状态值，切换语言会让选中项与
 * 比较条件同时失效。
 *
 * 应用列表由调用方传入。本组件曾经直接读取跨 feature 的演示数据模块，于是「应用」
 * 这个筛选的候选集在所有页面共享一份全局常量——任何一个 feature 改演示数据都会
 * 静默影响另外五个页面的下拉内容。应用目录属于各 feature 自己的读模型
 * （`DASHBOARD_CONTROL_PLANE.md` §4.2），由页面传入更符合边界。
 */
export type FiltersProps = {
  readonly appId: string;
  readonly setAppId: (id: string) => void;
  /** 当前 feature 可见的应用目录。 */
  readonly applications: readonly { readonly id: string; readonly label: string }[];
  readonly range: TimeRangeId;
  readonly setRange: (range: TimeRangeId) => void;
  /** 是否提供「全部应用」选项。跨应用大盘需要，单应用页不需要。 */
  readonly all?: boolean;
  /** 追加的业务筛选控件。 */
  readonly extra?: ReactNode;
  readonly showRange?: boolean;
  readonly labels?: {
    readonly environment: string;
    readonly production: string;
    readonly application: string;
    readonly allApplications: string;
    readonly sample: string;
  };
  /** 界面语言，用于解析时间窗口与筛选项标签。 */
  readonly locale: string;
};

const DEFAULT_LABELS = {
  environment: "环境",
  production: "生产环境 (PROD)",
  application: "应用",
  allApplications: "全部应用",
  sample: "示例采样 · 14:32:18",
} as const;

export function Filters({
  appId,
  setAppId,
  applications,
  range,
  setRange,
  all = false,
  extra = null,
  showRange = true,
  labels = DEFAULT_LABELS,
  locale,
}: FiltersProps) {
  const t = createRuleTranslator(locale);
  const appOptions = applications.map((app) => ({ value: app.id, label: app.label }));
  const rangeOptions = TIME_RANGES.map((value) => ({
    value,
    label: t(TIME_RANGE_LABEL_KEY[value]),
  }));

  return (
    <div className="filters">
      <Select
        label={labels.environment}
        value={labels.production}
        onChange={() => undefined}
        options={[labels.production]}
      />
      <Select
        label={labels.application}
        value={appId}
        onChange={setAppId}
        options={all ? [{ value: ALL_APPLICATIONS, label: labels.allApplications }, ...appOptions] : appOptions}
      />
      {showRange && (
        <Select<TimeRangeId>
          label="时间范围"
          value={range}
          onChange={setRange}
          options={rangeOptions}
        />
      )}
      {extra}
      <span className="sample-age">
        <i className="live-dot" /> {labels.sample}
      </span>
    </div>
  );
}
