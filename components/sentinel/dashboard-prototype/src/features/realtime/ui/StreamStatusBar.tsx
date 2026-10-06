/**
 * 回放状态条：当前窗口、示例标注与播放/暂停命令。
 *
 * 中文
 * ----
 * 旧实现把这段写在页面组件体内。拆出来的原因是它有**自己的变化原因**：接入真实数据流
 * 后这一条要显示连接状态、采样器安装情况与断线提示，而页面其余部分不关心这些。
 *
 * 组件只渲染传入的 `status` 并抛出 `onToggle`，不持有播放状态。
 *
 * 口径标注是产品硬要求，不是装饰：未接入实时后端时必须显示「示例曲线回放」与
 * 「未连接实时数据流」，接入后由 `samplerInstalled` 决定文案切换，**不得**在任何阶段
 * 让静态样本看起来像实时数据（`DASHBOARD_CONTROL_PLANE.md` §4.4）。
 */
import { PauseIcon as Pause, PlayIcon as Play } from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import type { TimeRangeId } from "../../../app/router/route.constants";
import type { StreamStatus } from "../model/realtime";
import { useTranslator } from "../../../core/i18n/useTranslator";

/** 已接入采样器时的游标说明。接入前不会出现。 */
const LIVE_STREAM_HINT = "realtime.bar.liveHint";

/** 未接入采样器时的游标说明。 */
const REPLAY_HINT = "realtime.bar.replayHint";

export interface StreamStatusBarProps {
  /** 当前时间窗口（协议值）。 */
  readonly range: TimeRangeId;
  readonly status: StreamStatus;
  readonly onToggle: () => void;
}

export function StreamStatusBar({ range, status, onToggle }: StreamStatusBarProps) {
  const t = useTranslator();
  return (
    <div className="monitor-bar">
      <div>
        <i className="live-dot" />
        <b>{t("realtime.bar.replayRange", { range })}</b>
        <span>{t(status.samplerInstalled ? LIVE_STREAM_HINT : REPLAY_HINT)}</span>
      </div>
      <ActionButton
        type="button"
        className="secondary-button"
        onClick={onToggle}
      >
        {status.paused ? <Play size={16} /> : <Pause size={16} />}
        {t(status.paused ? "realtime.action.resumeReplay" : "realtime.action.pauseReplay")}
      </ActionButton>
    </div>
  );
}
