import { useTranslation } from "react-i18next";
import type { RuleSetVersion } from "../model/ruleDeployment";
import { resolveCivilMinute } from "../model/ruleActivation";
import type { RuleScheduleDraft } from "../model/ruleScheduleDraft";
import { FormGrid } from "../../../shared/ui/FormGrid";
import { TextField } from "../../../shared/ui/TextField";
import { Select } from "../../../shared/ui/Select";
import { scheduleOccurrenceOptions } from "../presentation/scheduleTime";
/** Local civil-time fields, with explicit choices for repeated DST minutes. They do not run a scheduler. */
export function RulePlanFields({
  draft,
  versions,
  disabled,
  onChange,
}: {
  readonly draft: RuleScheduleDraft;
  readonly versions: readonly RuleSetVersion[];
  readonly disabled: boolean;
  readonly onChange: (draft: RuleScheduleDraft) => void;
}) {
  const { t, i18n } = useTranslation();
  const choices = [
    { value: "", label: t("rules.deployment.chooseVersion") },
    ...versions.map((version) => ({ value: version.id, label: version.name })),
  ];
  const starts = resolveCivilMinute(draft.startsAt, draft.timeZone),
    ends = resolveCivilMinute(draft.endsAt, draft.timeZone);
  const occurrences = (values: readonly number[]) =>
    scheduleOccurrenceOptions(
      values,
      i18n.resolvedLanguage ?? i18n.language,
      t("rules.deployment.chooseOccurrence"),
    );
  return (
    <FormGrid>
      <Select
        label={t("rules.deployment.targetVersion")}
        value={draft.versionId}
        options={choices}
        disabled={disabled}
        onChange={(versionId) => onChange({ ...draft, versionId })}
      />
      <Select
        label={t("rules.deployment.restoreVersion")}
        value={draft.restoreVersionId}
        options={choices}
        disabled={disabled}
        onChange={(restoreVersionId) => onChange({ ...draft, restoreVersionId })}
      />
      <TextField
        label={t("rules.deployment.timeZone")}
        hint={t("rules.deployment.timeZoneHint")}
        value={draft.timeZone}
        disabled={disabled}
        onChange={(timeZone) =>
          onChange({ ...draft, timeZone, startOccurrence: "", endOccurrence: "" })
        }
      />
      <TextField
        label={t("rules.deployment.startsAt")}
        hint={t("rules.deployment.civilHint")}
        value={draft.startsAt}
        disabled={disabled}
        onChange={(startsAt) => onChange({ ...draft, startsAt, startOccurrence: "" })}
      />
      <TextField
        label={t("rules.deployment.endsAt")}
        hint={t("rules.deployment.civilHint")}
        value={draft.endsAt}
        disabled={disabled}
        onChange={(endsAt) => onChange({ ...draft, endsAt, endOccurrence: "" })}
      />
      {starts.length > 1 && (
        <Select
          label={t("rules.deployment.startOccurrence")}
          hint={t("rules.deployment.ambiguityHint")}
          value={draft.startOccurrence}
          options={occurrences(starts)}
          disabled={disabled}
          onChange={(startOccurrence) => onChange({ ...draft, startOccurrence })}
        />
      )}
      {ends.length > 1 && (
        <Select
          label={t("rules.deployment.endOccurrence")}
          hint={t("rules.deployment.ambiguityHint")}
          value={draft.endOccurrence}
          options={occurrences(ends)}
          disabled={disabled}
          onChange={(endOccurrence) => onChange({ ...draft, endOccurrence })}
        />
      )}
    </FormGrid>
  );
}
