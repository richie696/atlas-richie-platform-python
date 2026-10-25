import type { z } from "zod";
import { instantToMilliseconds } from "../../../core/api/protocol/common";
import type { RuleBindingScopeCatalog } from "../model/ruleBindingScope";
import type { RuleBindingScopeCatalogSchema } from "./ruleBindingScopeWire";

/** Map the scope endpoint's wire timestamp into the feature's UTC-millisecond model. */
export function ruleBindingScopeCatalogFromWire(
  value: z.infer<typeof RuleBindingScopeCatalogSchema>,
): RuleBindingScopeCatalog {
  const { asOf, ...catalog } = value;
  return { ...catalog, asOfMs: instantToMilliseconds(asOf) };
}
