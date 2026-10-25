import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { FleetQuery } from "../model/fleet";
import {
  ObservationFilters,
  type ObservationOption,
} from "../../../shared/ui/observation/ObservationFilters";
import { TextField } from "../../../shared/ui/TextField";
import { ActionButton } from "../../../shared/ui/ActionButton";
import styles from "./Fleet.module.scss";
export type { ObservationOption } from "../../../shared/ui/observation/ObservationFilters";

/** Draft text is local; selected env/application/exact window and pagination remain app-owned. */
export function FleetQueryEditor({
  query,
  onChange,
  environments,
  applications,
  clock,
}: {
  readonly query: FleetQuery;
  readonly onChange: (query: FleetQuery) => void;
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
        onChange({ ...query, page: 1, search });
      }}
    >
      <ObservationFilters
        context={query.context}
        environments={environments}
        applications={applications}
        clock={clock}
        onChange={(context) =>
          onChange({
            ...query,
            page: 1,
            search: context.environmentId === query.context.environmentId ? query.search : "",
            context,
          })
        }
      />
      <TextField label={t("observation.fleet.search")} value={search} onChange={setSearch} />
      <ActionButton type="submit">{t("observation.query")}</ActionButton>
    </form>
  );
}
