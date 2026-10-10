import introStyles from "../../../../shared/ui/Intro.module.scss";
import identityStyles from "../Identity.module.scss";
import { scopedClasses } from "../../../../shared/ui/styles/scopedClasses";
/**
 * 身份页面的标题区。
 *
 * 中文
 * ----
 * 账户维护、角色绑定与修改密码三个页面的首屏结构完全相同（eyebrow + 标题 + 描述 +
 * 右侧动作）。旧实现把它作为局部组件写在 `IdentityPages.tsx` 里，只有本文件能看见；
 * 现在成为本 feature 的私有展示组件，**第二个消费者出现**（三个页面）就是拆出的
 * 理由，与文件行数无关。
 *
 * 组件只渲染 props；布局组合共享 Intro 皮肤，feature 只补充身份页所需的局部结构。
 */
import type { ReactNode } from "react";

const styleModules = [introStyles, identityStyles] as const;

export type IdentityIntroProps = {
  readonly eyebrow: string;
  readonly title: string;
  readonly description: string;
  readonly action?: ReactNode;
};

export function IdentityIntro({ eyebrow, title, description, action }: IdentityIntroProps) {
  return (
    <div className={scopedClasses(styleModules, "intro identity-intro")}>
      <div>
        <span className={scopedClasses(styleModules, "eyebrow")}>{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
