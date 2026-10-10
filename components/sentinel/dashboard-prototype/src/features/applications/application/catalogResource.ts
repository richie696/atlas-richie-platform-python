import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createQueryResource } from "../../../shared/state/queryResource";
import type { ObservationCatalogPort } from "../api/catalogPort";
import { validObservationCatalog } from "../model/observationCatalog";

/** Owns the authorized environment/application selector snapshot for one page lifetime. */
export function createObservationCatalogResource(port: ObservationCatalogPort) {
  return createQueryResource<
    void,
    Awaited<ReturnType<ObservationCatalogPort["readObservationCatalog"]>>
  >({
    keyOf: () => "observation-catalog",
    async read(_query, signal) {
      const value = await port.readObservationCatalog(signal);
      if (!validObservationCatalog(value))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid observation catalog", {
          status: 502,
          code: "console_response_invalid",
        });
      return value;
    },
    classify: (value) => (value.environments.length === 0 ? "empty" : "ready"),
  });
}
