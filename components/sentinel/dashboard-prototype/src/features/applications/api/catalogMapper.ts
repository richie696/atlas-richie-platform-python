import type { z } from "zod";
import { instantToMilliseconds } from "../../../core/api/protocol/common";
import type { ObservationCatalog } from "../model/observationCatalog";
import type { ObservationCatalogSchema } from "./catalogWire";
export function observationCatalogFromWire(
  value: z.infer<typeof ObservationCatalogSchema>,
): ObservationCatalog {
  const { asOf, ...catalog } = value;
  return { ...catalog, asOfMs: instantToMilliseconds(asOf) };
}
