import { useTranslation } from "react-i18next";
import type { AccountDraft } from "../../model/account";
import { ROLE_OPTIONS } from "../../presentation/rolePresentation";
import { FormGrid } from "../../../../shared/ui/FormGrid";
import { TextField } from "../../../../shared/ui/TextField";
import { Select } from "../../../../shared/ui/Select";

/** Shared vendor field anatomy; transient credentials belong to the enclosing dialog. */
export function AccountFields({
  draft,
  onChange,
  disabled = false,
}: {
  readonly draft: AccountDraft;
  readonly onChange: (draft: AccountDraft) => void;
  readonly disabled?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <FormGrid>
      <TextField
        label={t("accountDialog.field.username")}
        value={draft.username}
        autoComplete="username"
        disabled={disabled}
        onChange={(username) => onChange({ ...draft, username })}
      />
      <TextField
        label={t("accountDialog.field.password")}
        value={draft.password}
        type="password"
        autoComplete="new-password"
        disabled={disabled}
        onChange={(password) => onChange({ ...draft, password })}
      />
      <Select
        label={t("accountDialog.field.role")}
        value={draft.roleId}
        disabled={disabled}
        onChange={(roleId) => onChange({ ...draft, roleId })}
        options={ROLE_OPTIONS.map((role) => ({ value: role.id, label: t(role.labelKey) }))}
      />
    </FormGrid>
  );
}
