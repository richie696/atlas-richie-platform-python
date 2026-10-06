/**
 * 身份页面的面板外壳。
 *
 * 中文
 * ----
 * 身份 feature 的每个区块都是「标题 + 副标题 + 内容」的同一形态，但需要固定
 * `identity-panel` 这个类名——全局样式按它排版。旧实现是一个局部包装组件；现在作为
 * 私有展示组件，四个页面共用。
 *
 * 它只做一件事：把语义化标题交给共享 `Panel`，并附加本 feature 的类名。不引入任何
 * 状态或业务判断。
 */
import type { ReactNode } from "react";

import { Panel } from "../../../../shared/ui/Panel";

export type IdentityPanelProps = {
  readonly title: string;
  readonly subtitle?: string;
  readonly children: ReactNode;
};

export function IdentityPanel({ title, subtitle, children }: IdentityPanelProps) {
  return (
    <Panel title={title} subtitle={subtitle} className="identity-panel">
      {children}
    </Panel>
  );
}
