/**
 * 密码策略：长度与一致性规则。
 *
 * 中文
 * ----
 * 本模块不依赖 React、语言包和网络，只回答「这组密码字段是否满足规则」。
 *
 * 旧实现把规则内联在 `ChangePasswordPage` 的 submit 处理器里，于是「至少 12 位」这个
 * 领域约束同时出现在三个地方（改密页、新建账号对话框、初始化向导），三份判断可能
 * 悄悄漂移，而且每份都直接产出已翻译的中文字符串，无法单测。
 *
 * 校验结果用**结构化问题**（消息键 + 插值参数）而不是已翻译字符串：翻译发生在 UI 层，
 * 参数（`min`）由常量注入，界面文案不需要重复「12」这个魔法值。
 */
/** 密码最小长度。新建账号、改密与初始化内置管理员共用这一条。 */
export const PASSWORD_MIN_LENGTH = 12;

/**
 * 身份 feature 各表单校验共用的**结构化问题**形状。
 *
 * 放在这里是因为密码策略是三条校验链（新建账号、修改密码、创建内置管理员）的共同
 * 依赖；问题只描述「哪里不合法」，不含任何界面文案。
 */
export interface IdentityIssue<K extends string> {
  /** 消息键。取值形如 `password.tooShort`，由 UI 层的文案表解析。 */
  readonly key: K;
  /** 插值参数，例如 `{ min: PASSWORD_MIN_LENGTH }`。 */
  readonly params?: Readonly<Record<string, string | number>>;
}

/** 密码校验的消息键。 */
export type PasswordIssueKey = "password.tooShort" | "password.mismatch";

/** 一条密码问题。 */
export type PasswordIssue = IdentityIssue<PasswordIssueKey>;

/** 修改密码表单的三个字段。 */
export interface PasswordChangeDraft {
  readonly current: string;
  readonly next: string;
  readonly confirm: string;
}

/** 全空的改密表单初值。 */
export const EMPTY_PASSWORD_CHANGE: PasswordChangeDraft = Object.freeze({
  current: "",
  next: "",
  confirm: "",
});

/**
 * 校验一次改密提交。
 *
 * 只做**本地语义校验**：长度与两次输入是否一致。当前密码是否正确、是否会话失效，
 * 属于服务端判断，前端不得代替。
 */
export function validatePasswordChange(
  draft: PasswordChangeDraft,
): readonly PasswordIssue[] {
  if (draft.next.length < PASSWORD_MIN_LENGTH) {
    return [{ key: "password.tooShort", params: { min: PASSWORD_MIN_LENGTH } }];
  }
  if (draft.next !== draft.confirm) {
    return [{ key: "password.mismatch" }];
  }
  return [];
}
