/**
 * 「权限与审计」面板：最小权限模型 + 发布审计链。
 *
 * 中文
 * ----
 * 两条角色声明与四步审计链来自 `model/systemStatus.ts`，本面板只渲染。
 *
 * 产品硬约束（`DASHBOARD_CONTROL_PLANE.md` §2、§4.3）：这里**不得**引入
 * Viewer/Editor/Approver 层级，也不得把审计四步合并成「发布成功」一个状态。
 * 界面隐藏按钮不是安全边界，服务端对每次写操作独立鉴权。
 *
 * 面板末尾只有一行文字指引，不再有身份快捷入口。原先的「账户维护 / 角色绑定 /
 * 打开登录页」三个按钮已删除，原因见 `styles.css` 中 `.permission-hint` 的注释：
 * 前两个与本页 tab 条重复（且按钮跨路由跳走、tab 只切当前页，同一目标两种行为），
 * 第三个不属于权限模型；三个按钮还夹在两条角色说明之间，被读成某条角色的操作。
 * 授予能力的真实路径由上方 tab 条承担，本面板负责说清这条路径。
 */
import {
  ShieldCheckIcon as ShieldCheck,
  SlidersHorizontalIcon as SlidersHorizontal,
} from "@phosphor-icons/react";

import { Panel } from "../../../shared/ui/Panel";
import { Status } from "../../../shared/ui/Status";
import {
  AUDIT_CHAIN_STEPS,
  RULE_MAINTAINER_PERMISSION,
  VIEWER_PERMISSION,
  type PermissionDeclaration,
} from "../model/systemStatus";
import { useTranslator } from "../../../core/i18n/useTranslator";

/** 角色 id → 图标。图标是呈现细节，留在 UI 层。 */
const PERMISSION_ICONS: Readonly<Record<PermissionDeclaration["id"], typeof ShieldCheck>> =
  Object.freeze({
    viewer: ShieldCheck,
    "rule-maintainer": SlidersHorizontal,
  });

/**
 * 授予能力的路径说明。
 *
 * 中文
 * ----
 * 指向的是**本页的 tab**，不是路由：`账户维护` 与 `角色绑定` 就在上方 tab 条里，
 * 说清楚去哪里做即可，不需要再放一组会跳走的按钮。
 */
const PERMISSION_HINT = "system.permissions.grantHint";

export function PermissionsPanel() {
  const t = useTranslator();
  const ViewerIcon = PERMISSION_ICONS[VIEWER_PERMISSION.id];
  const MaintainerIcon = PERMISSION_ICONS[RULE_MAINTAINER_PERMISSION.id];

  return (
    <div className="system-grid">
      <Panel
        title={t("system.permissions.title")}
        subtitle={t("system.permissions.subtitle")}
      >
        <div className="permission">
          <ViewerIcon size={23} />
          <div>
            <b>{t(VIEWER_PERMISSION.titleKey)}</b>
            <p>
              {VIEWER_PERMISSION.capability} · {t(VIEWER_PERMISSION.descriptionKey)}
            </p>
          </div>
          <Status tone={VIEWER_PERMISSION.tone}>
            {t(VIEWER_PERMISSION.statusLabelKey)}
          </Status>
        </div>
        <div className="permission">
          <MaintainerIcon size={23} />
          <div>
            <b>{t(RULE_MAINTAINER_PERMISSION.titleKey)}</b>
            <p>
              {RULE_MAINTAINER_PERMISSION.capability} ·{" "}
              {t(RULE_MAINTAINER_PERMISSION.descriptionKey)}
            </p>
          </div>
          <Status tone={RULE_MAINTAINER_PERMISSION.tone}>
            {t(RULE_MAINTAINER_PERMISSION.statusLabelKey)}
          </Status>
        </div>
        <p className="permission-hint">{t(PERMISSION_HINT)}</p>
      </Panel>
      <Panel
        title={t("system.permissions.auditTitle")}
        subtitle={t("system.permissions.auditSubtitle")}
      >
        <div className="audit-flow">
          {AUDIT_CHAIN_STEPS.map((step) => (
            <div key={step.step}>
              <span>{step.step}</span>
              <b>{t(step.titleKey)}</b>
              <small>{t(step.detailKey)}</small>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
