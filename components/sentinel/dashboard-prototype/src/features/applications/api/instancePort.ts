import type {
  InstanceCatalog,
  InstanceCatalogQuery,
  InstanceDetailQuery,
  InstanceObservation,
} from "../model/instanceObservation";
/** Read-only instance observations; control-plane configuration writes belong to the rules feature. */
export interface InstancePort {
  readonly readCatalog: (
    query: InstanceCatalogQuery,
    signal: AbortSignal,
  ) => Promise<InstanceCatalog>;
  readonly readInstance: (
    query: InstanceDetailQuery,
    signal: AbortSignal,
  ) => Promise<InstanceObservation>;
}
