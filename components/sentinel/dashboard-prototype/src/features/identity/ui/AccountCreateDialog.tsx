import actionButtonStyles from "../../../shared/ui/ActionButton.module.scss";
import identityStyles from "./Identity.module.scss";
import { scopedClasses } from "../../../shared/ui/styles/scopedClasses";
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
import { useTranslation } from "react-i18next";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { validateAccountDraft, type AccountDraft } from "../model/account";
import { AccountFields } from "./components/AccountFields";

const styleModules = [actionButtonStyles, identityStyles] as const;

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
  const { t } = useTranslation();
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

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const issues = validateAccountDraft(draft);
    if (issues.length > 0) {
      onValidationError(t(issues[0].key));
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
      title={t("accountDialog.title")}
      subtitle={t("accountDialog.subtitle")}
      actions={
        <>
          <ActionButton
            className={scopedClasses(styleModules, "secondary-button")}
            type="button"
            onClick={close}
          >
            {t("accountDialog.action.cancel")}
          </ActionButton>
          <ActionButton
            className={scopedClasses(styleModules, "primary-button")}
            type="submit"
            form={formId}
          >
            {t("accountDialog.action.create")}
          </ActionButton>
        </>
      }
    >
      <form
        id={formId}
        className={scopedClasses(styleModules, "account-dialog-form")}
        onSubmit={submit}
      >
        <AccountFields draft={draft} onChange={setDraft} />
        <p className={scopedClasses(styleModules, "account-dialog-password-note")}>
          {t("accountDialog.passwordHint")}
        </p>
      </form>
    </DialogFrame>
  );
}
