import { AppError, AppErrorKind, defineUrl } from "@richie696/react-framework";
import type { z } from "zod";
import type {
  ConsoleEndpoint,
  ConsoleTransport,
} from "../../../core/api/transport/consoleEndpoint";
import { validObservationCatalog } from "../model/observationCatalog";
import type { ObservationCatalogPort } from "./catalogPort";
import { ObservationCatalogSchema } from "./catalogWire";
import { observationCatalogFromWire } from "./catalogMapper";

export const OBSERVATION_CATALOG_ENDPOINT: ConsoleEndpoint<
  z.infer<typeof ObservationCatalogSchema>
> = {
  url: defineUrl("/api/v1/observation/catalog"),
  response: ObservationCatalogSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors: ["invalid_request", "unauthenticated", "service_unavailable"],
};
/** Shared, authorized selectors. The browser never synthesizes a default environment/application. */
export function createObservationCatalogHttp(transport: ConsoleTransport): ObservationCatalogPort {
  return Object.freeze({
    async readObservationCatalog(signal) {
      const wire = await transport.send(OBSERVATION_CATALOG_ENDPOINT, { signal });
      const value = observationCatalogFromWire(wire);
      if (!validObservationCatalog(value))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid observation catalog", {
          status: 502,
          code: "console_response_invalid",
        });
      return value;
    },
  } satisfies ObservationCatalogPort);
}
