/**
 * 首屏四张摘要卡。
 *
 * 中文
 * ----
 * 旧实现把四张 `NumberCard` 直接写在页面组件体内，数值、单位和对比说明都是内联字面量。
 * 拆出来的原因是这块有独立的**数据来源与生命周期**：接入 Console API 后它由
 * `RealtimeSummary` 供给，并需要 scope / 窗口 / 来源 / 新鲜度四个标注，页面其余部分
 * 不跟着变（`REWRITE_PLAN.md` §4.4）。
 *
 * 组件是纯展示：不取数、不做格式化、不判断语义色。当前传入的是 `fixtures/` 里的示例
 * 数值，因此这里刻意**不包含 TPS 卡**——TPS 需由业务成功交易事件定义并单独接入，不能
 * 由 HTTP QPS 推算（`DASHBOARD_CONTROL_PLANE.md` §3「业务吞吐」行）。
 */
import { NumberCard } from "../../../shared/ui/NumberCard";
import type { RealtimeSummaryCard } from "../model/realtime";

export interface RealtimeSummaryCardsProps {
  readonly cards: readonly RealtimeSummaryCard[];
}

export function RealtimeSummaryCards({ cards }: RealtimeSummaryCardsProps) {
  return (
    <div className="number-grid">
      {cards.map((card) => (
        <NumberCard
          key={card.label}
          label={card.label}
          value={card.value}
          unit={card.unit}
          note={card.note}
          tone={card.tone}
        />
      ))}
    </div>
  );
}
