import { UserCircleIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { TextField } from "../../../../shared/ui/TextField";
import { FormGrid } from "../../../../shared/ui/FormGrid";
import { SETUP_FIELD, type SetupAdminDraft, type SetupField } from "../../model/setup";
import { SetupStepHeading } from "./SetupStepHeading";

/** Built-in account fields. Confirmation remains local and is omitted by the command projection. */
export function SetupAdminStep({
  draft,
  onChange,
  fieldErrors,
}: {
  readonly draft: SetupAdminDraft;
  readonly onChange: (patch: Partial<SetupAdminDraft>) => void;
  readonly fieldErrors: Partial<Record<SetupField, string>>;
}) {
  const { t } = useTranslation();
  return (
    <>
      <SetupStepHeading
        icon={<UserCircleIcon size={25} />}
        title={t("setup.stage.admin.title")}
        description={t("setup.stage.admin.description")}
      />
      <FormGrid className="setup-form-grid">
        <TextField
          label={t("setup.field.adminUsername")}
          autoComplete="username"
          value={draft.username}
          onChange={(username) => onChange({ username })}
          error={fieldErrors[SETUP_FIELD.AdminUsername]}
        />
        <TextField
          label={t("setup.field.adminPassword")}
          type="password"
          autoComplete="new-password"
          value={draft.password}
          onChange={(password) => onChange({ password })}
          error={fieldErrors[SETUP_FIELD.AdminPassword]}
        />
        <TextField
          label={t("setup.field.adminConfirm")}
          type="password"
          autoComplete="new-password"
          value={draft.confirm}
          onChange={(confirm) => onChange({ confirm })}
          error={fieldErrors[SETUP_FIELD.AdminConfirm]}
        />
      </FormGrid>
    </>
  );
}
