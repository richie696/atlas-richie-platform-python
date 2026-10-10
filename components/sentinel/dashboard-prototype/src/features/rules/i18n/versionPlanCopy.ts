/** Presentation metadata owned by this feature; never part of a wire/domain contract. */

/**
 * 版本面板使用的文案集合。
 *
 * 归属 rules/i18n，与 RuleWorkbenchMessages 同层；版本领域类型不依赖文案。
 */
export interface VersionPlanCopy {
  readonly title: string;
  readonly subtitle: string;
  readonly createVersion: string;
  /** 点击创建版本后的演示提示之一。 */
  readonly previewOnly: string;
  /** 演示提示之一：版本不可变。 */
  readonly immutable: string;
  /** 各状态标签，键与 {@link VERSION_STATE} 一致。 */
  readonly active: string;
  readonly scheduled: string;
  readonly superseded: string;
  readonly plannedWindow: string;
  readonly timeZone: string;
  readonly returnTo: string;
  readonly publishedAt: string;
  readonly noEnd: string;
  readonly effectiveWindow: string;
}
