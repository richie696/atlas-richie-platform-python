/** Formal instance read surface for app assembly; no fixture or provider selection. */
export { createInstanceResources } from "./application/instanceResources";
export { InstanceObservationPage } from "./ui/InstanceObservationPage";
export { instanceSelection, INSTANCE_LAYER } from "./model/instanceObservation";
export type {
  InstanceCatalogQuery,
  InstanceDetailQuery,
  InstanceCatalog,
  InstanceObservation,
  ObservedInstance,
  InstanceLayer,
} from "./model/instanceObservation";
export type { InstancePort } from "./api/instancePort";
