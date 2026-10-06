/**
 * 修改密码表单的状态与本地校验。
 *
 * 中文
 * ----
 * 旧实现把三字段状态、校验规则和「校验通过后清空表单」写在 `ChangePasswordPage` 的
 * 组件体内，于是页面同时承担展示、状态和领域判断。
 *
 * 这里把表单状态收成单一所有者，并把校验交给 `model/passwordPolicy`：
 *
 * - `submit()` **不翻译**，只返回结构化结论（`accepted` 或具体 `issue`），由页面把
 *   消息键与参数翻译成文案；
 * - 校验失败时**不动表单**，用户不必重输；校验通过才清空三个字段——这与旧实现一致，
 *   因为密码是写入式凭证，提交后必须从 UI 状态移除。
 *
 * 本 Hook 不发请求。当前密码是否正确、会话是否失效都由服务端判定。
 */
import { useCallback, useState } from "react";

import {
  EMPTY_PASSWORD_CHANGE,
  validatePasswordChange,
  type PasswordChangeDraft,
  type PasswordIssue,
} from "../model/passwordPolicy";

/** 一次提交的结论。`accepted` 表示本地校验通过，可以交给服务端。 */
export type PasswordSubmitResult =
  | { readonly status: "accepted" }
  | { readonly status: "invalid"; readonly issue: PasswordIssue };

export interface PasswordForm {
  readonly values: PasswordChangeDraft;
  setCurrent: (value: string) => void;
  setNext: (value: string) => void;
  setConfirm: (value: string) => void;
  /** 执行本地校验；通过时清空表单。 */
  submit: () => PasswordSubmitResult;
}

export function usePasswordForm(): PasswordForm {
  const [values, setValues] = useState<PasswordChangeDraft>(EMPTY_PASSWORD_CHANGE);

  const setField = useCallback(
    (field: keyof PasswordChangeDraft, value: string) => {
      setValues((current) => ({ ...current, [field]: value }));
    },
    [],
  );

  const setCurrent = useCallback((value: string) => setField("current", value), [setField]);
  const setNext = useCallback((value: string) => setField("next", value), [setField]);
  const setConfirm = useCallback((value: string) => setField("confirm", value), [setField]);

  const submit = useCallback((): PasswordSubmitResult => {
    const issues = validatePasswordChange(values);
    if (issues.length > 0) return { status: "invalid", issue: issues[0] };
    setValues(EMPTY_PASSWORD_CHANGE);
    return { status: "accepted" };
  }, [values]);

  return { values, setCurrent, setNext, setConfirm, submit };
}
