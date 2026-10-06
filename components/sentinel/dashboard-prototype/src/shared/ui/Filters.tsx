import type { ReactNode } from "react";

import { useTranslator } from "../../core/i18n/useTranslator";
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
 *
 * ## 标签归属 `core/i18n/shell.ts`，不再内联
 *
 * 旧实现在本文件里写死 `DEFAULT_LABELS` 与 `label="时间范围"`。本组件被 4 个页面
 * 共用，页面迁到 i18n 而它没迁，筛选条就仍是中文——而且**看起来**每个页面都迁完了。
 * 共享组件的文案归壳层包（`core/i18n`），只有一个变化原因。
 *
 * `labels` prop 保留为覆盖入口：规则页有自己的措辞（`ruleMessages().rules.filters`），
 * 语义确实不同，不强行共用。
 *
 * 时间范围标签原先经 `createRuleTranslator`（旧的 `ruleI18n`）解析，而
 * `shell.range.*` 键早就在 `SHELL_COPY` 里了——那是一处不必要的耦合，一并切断。
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
  /** 覆盖壳层默认措辞。规则页用自己的 filters 文案。 */
  readonly labels?: {
    readonly environment: string;
    readonly production: string;
    readonly application: string;
    readonly allApplications: string;
    readonly sample: string;
  };
};

export function Filters({
  appId,
  setAppId,
  applications,
  range,
  setRange,
  all = false,
  extra = null,
  showRange = true,
  labels,
}: FiltersProps) {
  const t = useTranslator();
  const shellLabels = {
    environment: t("shell.filter.environment"),
    production: t("shell.filter.production"),
    application: t("shell.filter.application"),
    allApplications: t("shell.filter.allApplications"),
    sample: t("shell.filter.sample"),
  };
  const text = labels ?? shellLabels;
  const appOptions = applications.map((app) => ({ value: app.id, label: app.label }));
  const rangeOptions = TIME_RANGES.map((value) => ({
    value,
    label: t(TIME_RANGE_LABEL_KEY[value]),
  }));

  return (
    <div className="filters">
      <Select
        label={text.environment}
        value={text.production}
        onChange={() => undefined}
        options={[text.production]}
      />
      <Select
        label={text.application}
        value={appId}
        onChange={setAppId}
        options={all ? [{ value: ALL_APPLICATIONS, label: text.allApplications }, ...appOptions] : appOptions}
      />
      {showRange && (
        <Select<TimeRangeId>
          label={t("shell.filter.range")}
          value={range}
          onChange={setRange}
          options={rangeOptions}
        />
      )}
      {extra}
      <span className="sample-age">
        <i className="live-dot" /> {text.sample}
      </span>
    </div>
  );
}
