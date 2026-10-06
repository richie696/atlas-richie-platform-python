/**
 * 修改密码页面容器。
 *
 * 中文
 * ----
 * 页面只做三件事：订阅账号列表、组合区域、把提交映射为 `usePasswordForm` 的命令。
 *
 * 旧实现把三字段状态和两条校验规则内联在 submit 里；现在状态在
 * `state/usePasswordForm`，规则在 `model/passwordPolicy`，翻译在 `ui/identityCopy`，
 * 页面只负责展示与提示。
 *
 * 账号来自共享 store 而不是模块内示例列表：新建的账号通过 URL 里的 `account` 参数
 * 打开时也能显示正确的用户名。
 */
import { useState, type FormEvent } from "react";
import {
  ArrowLeftIcon as ArrowLeft,
  KeyIcon as Key,
} from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { TextField } from "../../../shared/ui/TextField";
import { ROUTE } from "../../../app/router/route.constants";
import type { Navigate } from "../../../shared/types/dashboard";
import { usePasswordForm } from "../state/usePasswordForm";
import { loadAccounts, useAccounts } from "../state/accountStore";
import { INITIAL_ACCOUNTS } from "../fixtures/identityFixtures";
import { IdentityIntro } from "./components/IdentityIntro";
import { IdentityPanel } from "./components/IdentityPanel";
import { identityIssueText } from "./identityCopy";

// 演示装配，与另外两个账号页面共用同一个 store 命令。
loadAccounts(INITIAL_ACCOUNTS);

/** 未指定账号时的演示默认值。真实默认值来自会话。 */
const DEFAULT_ACCOUNT_ID = "account-admin";

export function ChangePasswordPage({ navigate, accountId = DEFAULT_ACCOUNT_ID }: { navigate: Navigate; accountId?: string }) {
  const { accounts } = useAccounts();
  const account = accounts.find((item) => item.id === accountId) ?? accounts[0];
  const form = usePasswordForm();
  const [message, setMessage] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const result = form.submit();
    setMessage(
      result.status === "accepted"
        ? "演示校验通过；真实环境将调用修改密码 API，不会在页面保存密码。"
        : identityIssueText(result.issue),
    );
  };

  return (
    <>
      <IdentityIntro eyebrow="SYSTEM / PASSWORD" title="修改密码" description={`为账号 ${account.username} 设置新的登录密码。密码只提交给后端校验，不进入 URL、日志或浏览器存储。`} action={<ActionButton className="secondary-button" type="button" onClick={() => navigate(ROUTE.Accounts)}><ArrowLeft size={16} /> 返回账户维护</ActionButton>} />
      {message && <div className="identity-notice" role="status">{message}</div>}
      <IdentityPanel title="更新登录密码" subtitle="建议使用密码管理器生成唯一密码；修改成功后可使其它会话失效。">
        <form className="password-form" onSubmit={submit}>
          <TextField label="当前密码" type="password" autoComplete="current-password" value={form.values.current} onChange={form.setCurrent} />
          <TextField label="新密码" type="password" autoComplete="new-password" hint="至少 12 位；不要使用账号名或环境名称。" value={form.values.next} onChange={form.setNext} />
          <TextField label="确认新密码" type="password" autoComplete="new-password" value={form.values.confirm} onChange={form.setConfirm} />
          <div className="identity-form-actions"><ActionButton className="primary-button" type="submit"><Key size={16} /> 保存新密码</ActionButton></div>
        </form>
      </IdentityPanel>
    </>
  );
}
