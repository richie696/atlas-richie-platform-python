/**
 * 新建账号对话框。
 *
 * 中文
 * ----
 * props 与回调契约保持不变：`onCreate` 收到写入式草稿，`onValidationError` 收到
 * **已翻译的**文案，因此调用方不需要知道消息键。
 *
 * 旧实现在 submit 里内联两条必填/长度判断并直接产出中文字符串；现在判断在
 * `model/account.ts` 的 `validateAccountDraft`，本组件只负责把结构化问题翻译成
 * 文案再交给调用方。角色下拉的 `value as IdentityRoleId` 断言也不再需要：`Select`
 * 的值域由 `draft.roleId` 推出 `IdentityRoleId`。
 */
import { useId, useState, type FormEvent } from "react";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { Select } from "../../../shared/ui/Select";
import { TextField } from "../../../shared/ui/TextField";
import { IDENTITY_ROLES, validateAccountDraft, type AccountDraft } from "../model/account";
import { identityIssueText } from "./identityCopy";

type AccountCreateForm = AccountDraft;

const EMPTY_DRAFT: AccountCreateForm = {
  username: "",
  password: "",
  roleId: "view",
};

type AccountCreateDialogProps = {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  onCreate: (draft: AccountDraft) => void;
  onValidationError: (message: string) => void;
};

/** Modal workflow for creating a dashboard account through Astryx Dialog. */
export function AccountCreateDialog({
  isOpen,
  onOpenChange,
  onCreate,
  onValidationError,
}: AccountCreateDialogProps) {
  const formId = useId();
  const [draft, setDraft] = useState<AccountCreateForm>(EMPTY_DRAFT);

  const close = () => {
    setDraft(EMPTY_DRAFT);
    onOpenChange(false);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      close();
      return;
    }
    onOpenChange(true);
  };

  const updateDraft = <K extends keyof AccountCreateForm>(key: K, value: AccountCreateForm[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const issues = validateAccountDraft(draft);
    if (issues.length > 0) {
      onValidationError(identityIssueText(issues[0]));
      return;
    }
    onCreate({
      username: draft.username.trim(),
      password: draft.password,
      roleId: draft.roleId,
    });
    close();
  };

  return (
    <DialogFrame
      isOpen={isOpen}
      onOpenChange={handleOpenChange}
      title="新增账号"
      subtitle="创建时设置初始登录密码；服务端只保存密码哈希，页面不会回显凭证。"
      actions={
        <>
          <ActionButton className="secondary-button" type="button" onClick={close}>
            取消
          </ActionButton>
          <ActionButton className="primary-button" type="submit" form={formId}>
            创建账号
          </ActionButton>
        </>
      }
    >
      <form id={formId} className="account-dialog-form" onSubmit={submit}>
        <TextField
          label="账号名"
          value={draft.username}
          onChange={(value) => updateDraft("username", value)}
          autoComplete="username"
        />
        <TextField
          label="密码"
          type="password"
          autoComplete="new-password"
          value={draft.password}
          onChange={(value) => updateDraft("password", value)}
        />
        <Select
          label="角色"
          value={draft.roleId}
          onChange={(value) => updateDraft("roleId", value)}
          options={IDENTITY_ROLES.map((role) => ({
            value: role.id,
            label: role.label,
          }))}
        />
        <p className="account-dialog-password-note">
          密码至少 12 位；仅提交给后台保存哈希，页面不会保存或回显凭证。
        </p>
      </form>
    </DialogFrame>
  );
}
