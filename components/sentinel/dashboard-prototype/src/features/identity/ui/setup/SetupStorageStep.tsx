import { DatabaseIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { ActionButton } from "../../../../shared/ui/ActionButton";
import { TextField } from "../../../../shared/ui/TextField";
import { FormGrid, FormGridFullRow } from "../../../../shared/ui/FormGrid";
import { RadioGroup } from "../../../../shared/ui/RadioGroup";
import {
  SETUP_FIELD,
  type ControlPlaneDatabaseKind,
  type SetupDatabaseDraft,
  type SetupField,
} from "../../model/setup";
import {
  SETUP_DATABASE_OPTIONS,
  setupDatabasePresentationFor,
} from "../../presentation/setupPresentation";
import { SetupStepHeading } from "./SetupStepHeading";
import { setupClass } from "./setupStyle";

/** Database fields only. A connection-test callback is not a claim that the browser connected to a database. */
export function SetupStorageStep({
  kind,
  connection,
  port,
  onKindChange,
  onPortChange,
  onConnectionChange,
  onTestConnection,
  isChecking = false,
  fieldErrors,
}: {
  readonly kind: ControlPlaneDatabaseKind;
  readonly connection: SetupDatabaseDraft;
  readonly port: string;
  readonly onKindChange: (kind: ControlPlaneDatabaseKind) => void;
  readonly onPortChange: (port: string) => void;
  readonly onConnectionChange: (patch: Partial<SetupDatabaseDraft>) => void;
  readonly onTestConnection: () => void;
  readonly isChecking?: boolean;
  readonly fieldErrors: Partial<Record<SetupField, string>>;
}) {
  const { t } = useTranslation();
  const selected = setupDatabasePresentationFor(kind);
  return (
    <>
      <SetupStepHeading
        icon={<DatabaseIcon size={25} />}
        title={t("setup.stage.database.title")}
        description={t("setup.stage.database.description")}
      />
      <RadioGroup
        variant="cards"
        label={t("setup.field.database")}
        value={kind}
        onChange={onKindChange}
        className={setupClass("setup-choice")}
        options={SETUP_DATABASE_OPTIONS.map((database) => ({
          value: database.id,
          label: database.label,
          description: t(database.descriptionKey),
        }))}
      />
      {selected.requiresNetworkConfiguration ? (
        <FormGrid className="setup-form-grid">
          <TextField
            label={t("setup.field.host")}
            value={connection.host}
            onChange={(host) => onConnectionChange({ host })}
            placeholder="db.internal.example"
            autoComplete="off"
            error={fieldErrors[SETUP_FIELD.DatabaseHost]}
          />
          <TextField
            label={t("setup.field.port")}
            value={port}
            onChange={onPortChange}
            error={fieldErrors[SETUP_FIELD.DatabasePort]}
          />
          <TextField
            label={t("setup.field.databaseName")}
            value={connection.name}
            onChange={(name) => onConnectionChange({ name })}
            autoComplete="off"
            error={fieldErrors[SETUP_FIELD.DatabaseName]}
          />
          <TextField
            label={t("setup.field.username")}
            value={connection.username}
            onChange={(username) => onConnectionChange({ username })}
            autoComplete="username"
            error={fieldErrors[SETUP_FIELD.DatabaseUsername]}
          />
          <FormGridFullRow>
            <TextField
              label={t("setup.field.password")}
              type="password"
              value={connection.password}
              onChange={(password) => onConnectionChange({ password })}
              autoComplete="new-password"
              error={fieldErrors[SETUP_FIELD.DatabasePassword]}
            />
          </FormGridFullRow>
        </FormGrid>
      ) : (
        <div className={setupClass("setup-local-note")}>{t("setup.sqliteNote")}</div>
      )}
      <ActionButton
        className={setupClass("secondary-button")}
        type="button"
        disabled={isChecking}
        onClick={onTestConnection}
      >
        {t("setup.action.testConnection")}
      </ActionButton>
    </>
  );
}
