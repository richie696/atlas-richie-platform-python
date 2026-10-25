import { useTranslation } from "react-i18next";
import { OBSERVATION_SCOPE, type ObservationContext } from "../../model/observation";
import {
  ALL_APPLICATIONS,
  TIME_RANGE,
  TIME_RANGE_MS,
  TIME_RANGE_LABEL_KEY,
} from "../../types/navigation";
import { Select } from "../Select";

export interface ObservationOption {
  readonly id: string;
  readonly name: string;
}
/** Shared filter controls only. The page/app owns query, URL, scope policy and effects. */
export function ObservationFilters({
  context,
  onChange,
  environments,
  applications,
  allowAllApplications = true,
  clock = Date.now,
}: {
  readonly context: ObservationContext;
  readonly onChange: (context: ObservationContext) => void;
  readonly environments: readonly ObservationOption[];
  readonly applications: readonly ObservationOption[];
  /** Fleet pages may select all applications; the instance directory is single-application. */
  readonly allowAllApplications?: boolean;
  readonly clock?: () => number;
}) {
  const { t } = useTranslation();
  const span = context.window.toMs - context.window.fromMs;
  const range =
    span === TIME_RANGE_MS[TIME_RANGE.Last15Minutes]
      ? TIME_RANGE.Last15Minutes
      : span === TIME_RANGE_MS[TIME_RANGE.Last1Hour]
        ? TIME_RANGE.Last1Hour
        : "custom";
  return (
    <>
      <Select
        label={t("observation.environment")}
        value={context.environmentId}
        options={environments.map((item) => ({ value: item.id, label: item.name }))}
        onChange={(environmentId) => {
          if (environmentId !== context.environmentId)
            onChange({
              ...context,
              environmentId,
              appId: null,
              instanceId: null,
              resource: null,
              scope: OBSERVATION_SCOPE.Fleet,
            });
        }}
      />
      <Select
        label={t("observation.application")}
        value={context.appId ?? ALL_APPLICATIONS}
        options={[
          ...(allowAllApplications
            ? [{ value: ALL_APPLICATIONS, label: t("observation.allApplications") }]
            : []),
          ...applications.map((item) => ({ value: item.id, label: item.name })),
        ]}
        onChange={(id) => {
          const appId = id === ALL_APPLICATIONS ? null : id;
          if (appId !== context.appId)
            onChange({
              ...context,
              appId,
              instanceId: null,
              resource: null,
              scope: appId === null ? OBSERVATION_SCOPE.Fleet : OBSERVATION_SCOPE.Application,
            });
        }}
      />
      <Select
        label={t("observation.window")}
        value={range}
        options={[
          ...Object.values(TIME_RANGE).map((value) => ({
            value,
            label: t(TIME_RANGE_LABEL_KEY[value]),
          })),
          { value: "custom", label: t("observation.window.custom") },
        ]}
        onChange={(value) => {
          if (value !== TIME_RANGE.Last15Minutes && value !== TIME_RANGE.Last1Hour) return;
          const toMs = clock();
          onChange({ ...context, window: { fromMs: toMs - TIME_RANGE_MS[value], toMs } });
        }}
      />
    </>
  );
}
