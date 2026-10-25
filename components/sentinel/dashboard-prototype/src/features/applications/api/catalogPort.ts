import type { ObservationCatalog } from "../model/observationCatalog";
/** Authorized environment/application choices; not an exhaustive inventory of instances or resources. */
export interface ObservationCatalogPort {
  readonly readObservationCatalog: (signal: AbortSignal) => Promise<ObservationCatalog>;
}
