import { CloudCheckIcon, LockKeyIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { TextField } from "../../../../shared/ui/TextField";
import { ActionButton } from "../../../../shared/ui/ActionButton";
import { FormGrid, FormGridFullRow } from "../../../../shared/ui/FormGrid";
import { RadioGroup } from "../../../../shared/ui/RadioGroup";
import {
  RULE_SOURCE,
  RULE_SOURCE_AUTHENTICATION,
  SETUP_FIELD,
  type RuleSourceKind,
  type SetupRuleSourceDraft,
  type RuleSourceAuthenticationMode,
  type RuleSourceCredentials,
  type SetupField,
} from "../../model/setup";
import {
  RULE_SOURCE_OPTIONS,
  RULE_SOURCE_AUTHENTICATION_OPTIONS,
} from "../../presentation/setupPresentation";
import { SetupStepHeading } from "./SetupStepHeading";
import { setupClass } from "./setupStyle";

/** Provider/authentication presentation. Mode changes are commands to the form owner, never hidden credential merging. */
export function SetupSourceStep({
  kind,
  connection,
  mode,
  credentials,
  onKindChange,
  onConnectionChange,
  onModeChange,
  onCredentialsChange,
  onTestConnection,
  isChecking = false,
  fieldErrors,
}: {
  readonly kind: RuleSourceKind;
  readonly connection: SetupRuleSourceDraft;
  readonly mode: RuleSourceAuthenticationMode;
  readonly credentials: RuleSourceCredentials;
  readonly onKindChange: (kind: RuleSourceKind) => void;
  readonly onConnectionChange: (patch: Partial<SetupRuleSourceDraft>) => void;
  readonly onModeChange: (mode: RuleSourceAuthenticationMode) => void;
  readonly onCredentialsChange: (patch: Partial<RuleSourceCredentials>) => void;
  readonly onTestConnection?: () => void;
  readonly isChecking?: boolean;
  readonly fieldErrors: Partial<Record<SetupField, string>>;
}) {
  const { t } = useTranslation();
  const isNacos = kind === RULE_SOURCE.Nacos;
  return (
    <>
      <SetupStepHeading
        icon={<CloudCheckIcon size={25} />}
        title={t("setup.stage.source.title")}
        description={t("setup.stage.source.description")}
      />
      <RadioGroup
        variant="cards"
        label={t("setup.field.ruleSource")}
        value={kind}
        onChange={onKindChange}
        className={setupClass("setup-choice")}
        options={RULE_SOURCE_OPTIONS.map((source) => ({
          value: source.id,
          label: source.label,
          description: t(source.descriptionKey),
        }))}
      />
      <FormGrid className="setup-form-grid">
        <FormGridFullRow>
          <TextField
            label={t("setup.field.serviceAddress")}
            placeholder={isNacos ? "https://nacos.example.com" : "https://consul.example.com"}
            autoComplete="off"
            value={connection.address}
            onChange={(address) => onConnectionChange({ address })}
            error={fieldErrors[SETUP_FIELD.SourceAddress]}
          />
        </FormGridFullRow>
        <TextField
          label={t("setup.field.namespace")}
          autoComplete="off"
          value={connection.namespace}
          onChange={(namespace) => onConnectionChange({ namespace })}
        />
      </FormGrid>
      <fieldset className={setupClass("setup-authentication")}>
        <legend>{t("setup.field.authenticationMode")}</legend>
        <RadioGroup
          variant="cards"
          label={t("setup.field.authenticationMode")}
          value={mode}
          onChange={onModeChange}
          className={setupClass("setup-choice")}
          options={RULE_SOURCE_AUTHENTICATION_OPTIONS.map((option) => ({
            value: option.id,
            label: t(option.labelKey),
            description: t(option.descriptionKey),
          }))}
        />
      </fieldset>
      {mode === RULE_SOURCE_AUTHENTICATION.CredentialReference && (
        <FormGrid className="setup-form-grid">
          <FormGridFullRow>
            <TextField
              label={t("setup.field.credentialReference")}
              value={credentials.reference}
              onChange={(reference) => onCredentialsChange({ reference })}
              placeholder={t(isNacos ? "setup.placeholder.nacos" : "setup.placeholder.consul")}
              autoComplete="off"
              hint={t("setup.credentialReferenceHint")}
              error={fieldErrors[SETUP_FIELD.CredentialReference]}
            />
          </FormGridFullRow>
        </FormGrid>
      )}
      {mode === RULE_SOURCE_AUTHENTICATION.Direct && (
        <>
          <div className={setupClass("setup-security-note")}>
            <LockKeyIcon size={17} />
            <span>{t("setup.directNote")}</span>
          </div>
          <FormGrid className="setup-form-grid">
            {isNacos ? (
              <>
                <TextField
                  label={t("setup.field.nacosUsername")}
                  value={credentials.username}
                  onChange={(username) => onCredentialsChange({ username })}
                  autoComplete="username"
                  error={fieldErrors[SETUP_FIELD.NacosUsername]}
                />
                <TextField
                  label={t("setup.field.nacosPassword")}
                  type="password"
                  value={credentials.password}
                  onChange={(password) => onCredentialsChange({ password })}
                  autoComplete="new-password"
                  error={fieldErrors[SETUP_FIELD.NacosPassword]}
                />
              </>
            ) : (
              <FormGridFullRow>
                <TextField
                  label={t("setup.field.consulToken")}
                  type="password"
                  value={credentials.consulToken}
                  onChange={(consulToken) => onCredentialsChange({ consulToken })}
                  autoComplete="new-password"
                  error={fieldErrors[SETUP_FIELD.ConsulToken]}
                />
              </FormGridFullRow>
            )}
          </FormGrid>
        </>
      )}
      {mode === RULE_SOURCE_AUTHENTICATION.None && (
        <div className={setupClass("setup-security-note")}>
          <LockKeyIcon size={17} />
          <span>{t("setup.noneNote", { source: isNacos ? "Nacos" : "Consul" })}</span>
        </div>
      )}
      {onTestConnection && (
        <div className={setupClass("setup-actions")}>
          <ActionButton disabled={isChecking} onClick={onTestConnection}>
            {t("setup.action.testSource")}
          </ActionButton>
        </div>
      )}
    </>
  );
}
