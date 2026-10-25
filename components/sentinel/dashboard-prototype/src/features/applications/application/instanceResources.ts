import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  createOwnedQueryResource,
  type QueryAccessObserver,
} from "../../../shared/state/ownedQueryResource";
import {
  createQueryResource,
  type QueryResourceOptions,
} from "../../../shared/state/queryResource";
import { OBSERVATION_QUALITY } from "../../../shared/model/observation";
import type { InstancePort } from "../api/instancePort";
import {
  instanceCatalogKey,
  instanceDetailKey,
  INSTANCE_READ_FAILURE,
  validInstanceCatalog,
  validInstanceCatalogQuery,
  validInstanceDetailQuery,
  validInstanceObservation,
  type InstanceCatalog,
  type InstanceCatalogQuery,
  type InstanceDetailQuery,
  type InstanceObservation,
} from "../model/instanceObservation";

const invalid = (status: number) =>
  new AppError(AppErrorKind.PROTOCOL, "Inconsistent instance observation", {
    status,
    code: status === 400 ? "invalid_instance_query" : "invalid_instance_observation",
  });
/** Separate keyed owners: filtering the catalog does not replace the explicitly selected instance. */
export function createInstanceResources(
  port: InstancePort,
  access?: QueryAccessObserver,
  options: { readonly timeoutMs?: number } = {},
) {
  const catalogOptions: QueryResourceOptions<InstanceCatalogQuery, InstanceCatalog> = {
    keyOf: instanceCatalogKey,
    timeoutMs: options.timeoutMs,
    async read(query, signal) {
      if (!validInstanceCatalogQuery(query)) throw invalid(400);
      const value = await port.readCatalog(query, signal);
      if (!validInstanceCatalog(value, query)) throw invalid(502);
      return value;
    },
    classify: (value) =>
      value.totalInstances === 0
        ? "empty"
        : value.items.length === 0
          ? "filtered-empty"
          : value.coverage.expected === null || value.coverage.reporting < value.coverage.expected
            ? "partial"
            : "ready",
  };
  const detailOptions: QueryResourceOptions<InstanceDetailQuery, InstanceObservation> = {
    keyOf: instanceDetailKey,
    timeoutMs: options.timeoutMs,
    invalidatesValue: (error) =>
      error.status === 409 && error.code === INSTANCE_READ_FAILURE.IncarnationChanged,
    async read(query, signal) {
      if (!validInstanceDetailQuery(query)) throw invalid(400);
      const value = await port.readInstance(query, signal);
      if (!validInstanceObservation(value, query)) throw invalid(502);
      return value;
    },
    classify: (value) =>
      value.metrics === null ||
      value.metrics.summary.some((item) => item.quality !== OBSERVATION_QUALITY.Available)
        ? "partial"
        : "ready",
  };
  // Optional access observation is a UI data-retention guard. HTTP endpoint authorization remains authoritative.
  const catalog = access
    ? createOwnedQueryResource<InstanceCatalogQuery, InstanceCatalog>(access, catalogOptions)
    : createQueryResource<InstanceCatalogQuery, InstanceCatalog>(catalogOptions);
  const detail = access
    ? createOwnedQueryResource<InstanceDetailQuery, InstanceObservation>(access, detailOptions)
    : createQueryResource<InstanceDetailQuery, InstanceObservation>(detailOptions);
  return Object.freeze({
    catalog,
    detail,
    dispose() {
      catalog.dispose();
      detail.dispose();
    },
  });
}
