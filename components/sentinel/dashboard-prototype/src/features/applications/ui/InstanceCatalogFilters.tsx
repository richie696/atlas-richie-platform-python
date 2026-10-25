import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ObservationFilters,
  type ObservationOption,
} from "../../../shared/ui/observation/ObservationFilters";
import { TextField } from "../../../shared/ui/TextField";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { Select } from "../../../shared/ui/Select";
import type { InstanceCatalogQuery } from "../model/instanceObservation";
import styles from "./InstanceObservation.module.scss";

/** Search is local until submitted; query parameters and side effects remain with the page owner. */
export function InstanceCatalogFilters({
  query,
  onChange,
  environments,
  applications,
  clock,
}: {
  readonly query: InstanceCatalogQuery;
  readonly onChange: (query: InstanceCatalogQuery) => void;
  readonly environments: readonly ObservationOption[];
  readonly applications: readonly ObservationOption[];
  readonly clock?: () => number;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState(query.search);
  return (
    <form
      className={styles.filters}
      data-observation-filters
      onSubmit={(event) => {
        event.preventDefault();
        onChange({ ...query, search, page: 1 });
      }}
    >
      <ObservationFilters
        context={query.context}
        environments={environments}
        applications={applications}
        allowAllApplications={false}
        clock={clock}
        onChange={(context) => onChange({ ...query, context, page: 1 })}
      />
      <Select
        label={t("applications.observed.healthFilter")}
        value={query.attentionOnly ? "attention" : "all"}
        options={[
          { value: "all", label: t("applications.matrix.all") },
          { value: "attention", label: t("applications.matrix.anomaliesOnly") },
        ]}
        onChange={(value) => onChange({ ...query, attentionOnly: value === "attention", page: 1 })}
      />
      <TextField label={t("applications.observed.search")} value={search} onChange={setSearch} />
      <ActionButton className={styles["filter-submit"]} type="submit">
        {t("observation.query")}
      </ActionButton>
    </form>
  );
}
