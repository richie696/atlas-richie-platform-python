/**
 * 总览首屏的异常摘要。
 *
 * 中文
 * ----
 * 标题里的两个数字来自 `FleetAttention`，不是写死的文案：演示目录只有 3 个应用行，
 * 而摘要声称的是 18 个应用（旧实现把这两个数字都硬编码在 JSX 里，改一处不会
 * 提示另一处已经对不上）。
 *
 * 摘要文本是**已确认的观察结论**，不写「因为 CPU 升高导致阻断率上升」这类因果推断
 * （`DASHBOARD_CONTROL_PLANE.md` §4.1：时间相关不直接断言因果）。
 * 下钻按钮指向 `focusedAppIds` 的首个应用。
 */
import { ArrowRightIcon as ArrowRight, WarningIcon as Warning } from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { ROUTE } from "../../../app/router/route.constants";
import type { Navigate } from "../../../shared/types/dashboard";
import type { FleetAttention } from "../model/overview";

export interface AttentionHeroProps {
  readonly attention: FleetAttention;
  /** 下钻目标应用 id。 */
  readonly appId: string;
  readonly navigate: Navigate;
}

export function AttentionHero({ attention, appId, navigate }: AttentionHeroProps) {
  return (
    <div className="alert-hero">
      <span className="alert-icon">
        <Warning size={27} weight="fill" />
      </span>
      <div>
        <span className="eyebrow">NEEDS ATTENTION</span>
        <h2>
          {`${attention.totalApps} 个应用运行中，`}
          <em>{`${attention.attentionCount} 个需要关注`}</em>
        </h2>
        <p>{attention.summary}</p>
      </div>
      <ActionButton
        type="button"
        className="primary-button"
        onClick={() => navigate(ROUTE.Applications, { appId })}
      >
        查看异常应用 <ArrowRight size={16} />
      </ActionButton>
    </div>
  );
}
