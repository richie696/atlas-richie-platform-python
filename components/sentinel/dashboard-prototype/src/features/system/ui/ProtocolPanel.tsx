/**
 * 「协议与版本」面板：控制面/观测面/决策面的边界说明 + 交付形态状态。
 *
 * 中文
 * ----
 * 边界文案在 `model/systemStatus.ts`，图标映射留在本文件。状态清单描述的是
 * **本交付物走到了哪一步**，不是对部署环境的探测结果，所以标题下必须保留
 * 「示例值不代表部署环境现状」这句限定。
 */
import {
  ActivityIcon as Activity,
  CloudCheckIcon as CloudCheck,
  HardDrivesIcon as HardDrives,
  InfoIcon as Info,
} from "@phosphor-icons/react";

import { Panel } from "../../../shared/ui/Panel";
import {
  DELIVERY_STATUS_ITEMS,
  PROTOCOL_BOUNDARIES,
  type ProtocolBoundaryId,
} from "../model/systemStatus";
import { useTranslator } from "../../../core/i18n/useTranslator";

/** 边界 id → 图标。图标是呈现细节，留在 UI 层。 */
const PROTOCOL_ICONS: Readonly<Record<ProtocolBoundaryId, typeof Activity>> = Object.freeze({
  "rule-config": CloudCheck,
  "agent-reporting": Activity,
  "cluster-token": HardDrives,
});

export function ProtocolPanel() {
  const t = useTranslator();
  return (
    <div className="system-grid">
      <Panel
        title={t("system.protocol.boundaryTitle")}
        subtitle={t("system.protocol.boundarySubtitle")}
      >
        {PROTOCOL_BOUNDARIES.map((boundary) => {
          const Icon = PROTOCOL_ICONS[boundary.id];
          return (
            <div className="protocol" key={boundary.id}>
              <Icon size={23} />
              <div>
                <b>{t(boundary.nameKey)}</b>
                <p>{t(boundary.roleKey)}</p>
              </div>
            </div>
          );
        })}
      </Panel>
      <Panel
        title={t("system.protocol.deliveryTitle")}
        subtitle={t("system.protocol.deliverySubtitle")}
      >
        {DELIVERY_STATUS_ITEMS.map((item) => (
          <div className="key-value" key={item.id}>
            <span>{t(item.labelKey)}</span>
            <b>{t(item.valueKey)}</b>
          </div>
        ))}
        <div className="inline-note">
          <Info size={16} /> {t("system.protocol.note")}
        </div>
      </Panel>
    </div>
  );
}
