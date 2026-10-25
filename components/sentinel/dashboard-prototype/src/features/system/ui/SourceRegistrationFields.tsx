import { useTranslation } from "react-i18next";
import { FormGrid } from "../../../shared/ui/FormGrid";
import { TextField } from "../../../shared/ui/TextField";
import { Select } from "../../../shared/ui/Select";
import {
  RULE_SOURCE,
  RULE_SOURCES,
  RULE_SOURCE_AUTHENTICATION,
  RULE_SOURCE_AUTHENTICATION_MODES,
} from "../../../shared/model/configurationSource";
import {
  SOURCE_CREDENTIAL_ACTION,
  type SourceRegistrationDraft,
} from "../model/sourceRegistration";
import { SOURCE_AUTH_LABEL } from "../presentation/sourceRegistrationLabels";
import styles from "./SystemObservation.module.scss";

/** Controlled transient write-only fields. No credential enters a store, URL, read model or persisted draft. */
export function SourceRegistrationFields({
  draft,
  editing,
  disabled,
  onChange,
}: {
  readonly draft: SourceRegistrationDraft;
  readonly editing: boolean;
  readonly disabled: boolean;
  readonly onChange: (next: SourceRegistrationDraft) => void;
}) {
  const { t } = useTranslation(),
    connection = draft.connection;
  const patch = (next: Partial<typeof connection>) =>
    onChange({ ...draft, connection: { ...connection, ...next } });
  const credential = (field: keyof typeof connection.credentials, value: string) =>
    patch({ credentials: { ...connection.credentials, [field]: value } });
  const replacing = draft.credentialAction === SOURCE_CREDENTIAL_ACTION.Replace;
  return (
    <FormGrid className={styles["source-registration-fields"]}>
      <TextField
        label={t("system.source.name")}
        value={draft.name}
        disabled={disabled}
        onChange={(name) => onChange({ ...draft, name })}
      />
      <Select
        label={t("system.source.provider")}
        value={connection.provider}
        disabled={disabled}
        options={RULE_SOURCES.map((value) => ({
          value,
          label: value === RULE_SOURCE.Nacos ? "Nacos" : "Consul",
        }))}
        onChange={(provider) => patch({ provider })}
      />
      <TextField
        label={t("system.source.endpoint")}
        hint={t("system.source.endpointHint")}
        value={connection.endpoint}
        disabled={disabled}
        onChange={(endpoint) => patch({ endpoint })}
      />
      <TextField
        label={t(
          connection.provider === RULE_SOURCE.Nacos
            ? "system.source.namespace"
            : "system.source.datacenter",
        )}
        hint={t("system.source.locationHint")}
        value={connection.location}
        disabled={disabled}
        onChange={(location) => patch({ location })}
      />
      {editing && (
        <Select
          label={t("system.source.credentials")}
          hint={t("system.source.keepHint")}
          value={draft.credentialAction}
          disabled={disabled}
          options={[
            { value: SOURCE_CREDENTIAL_ACTION.Keep, label: t("system.source.keep") },
            { value: SOURCE_CREDENTIAL_ACTION.Replace, label: t("system.source.replace") },
          ]}
          onChange={(credentialAction) => onChange({ ...draft, credentialAction })}
        />
      )}
      {replacing && (
        <Select
          label={t("system.source.authentication")}
          value={connection.authentication}
          disabled={disabled}
          options={RULE_SOURCE_AUTHENTICATION_MODES.map((value) => ({
            value,
            label: t(SOURCE_AUTH_LABEL[value]),
          }))}
          onChange={(authentication) => patch({ authentication })}
        />
      )}
      {replacing &&
        connection.authentication === RULE_SOURCE_AUTHENTICATION.CredentialReference && (
          <TextField
            label={t("system.source.reference")}
            hint={t("system.source.referenceHint")}
            type="password"
            autoComplete="new-password"
            value={connection.credentials.reference}
            disabled={disabled}
            onChange={(value) => credential("reference", value)}
          />
        )}
      {replacing &&
        connection.authentication === RULE_SOURCE_AUTHENTICATION.Direct &&
        (connection.provider === RULE_SOURCE.Nacos ? (
          <>
            <TextField
              label={t("system.source.username")}
              autoComplete="off"
              value={connection.credentials.username}
              disabled={disabled}
              onChange={(value) => credential("username", value)}
            />
            <TextField
              label={t("system.source.password")}
              hint={t("system.source.secretHint")}
              type="password"
              autoComplete="new-password"
              value={connection.credentials.password}
              disabled={disabled}
              onChange={(value) => credential("password", value)}
            />
          </>
        ) : (
          <TextField
            label={t("system.source.token")}
            hint={t("system.source.secretHint")}
            type="password"
            autoComplete="new-password"
            value={connection.credentials.consulToken}
            disabled={disabled}
            onChange={(value) => credential("consulToken", value)}
          />
        ))}
    </FormGrid>
  );
}
