import { useTranslation } from "react-i18next";
import { TextField } from "../../../../shared/ui/TextField";
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from "../../model/passwordPolicy";
import type { PasswordForm } from "../../state/usePasswordForm";

/** Stateless own-password fields shared during migration; no target selection or effects. */
export function PasswordFields({
  form,
  disabled = false,
}: {
  readonly form: PasswordForm;
  readonly disabled?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <>
      <TextField
        label={t("changePassword.field.current")}
        type="password"
        autoComplete="current-password"
        value={form.values.current}
        onChange={form.setCurrent}
        disabled={disabled}
      />
      <TextField
        label={t("changePassword.field.next")}
        type="password"
        autoComplete="new-password"
        hint={t("changePassword.field.nextHint", {
          min: PASSWORD_MIN_LENGTH,
          max: PASSWORD_MAX_LENGTH,
        })}
        value={form.values.next}
        onChange={form.setNext}
        disabled={disabled}
      />
      <TextField
        label={t("changePassword.field.confirm")}
        type="password"
        autoComplete="new-password"
        value={form.values.confirm}
        onChange={form.setConfirm}
        disabled={disabled}
      />
    </>
  );
}
