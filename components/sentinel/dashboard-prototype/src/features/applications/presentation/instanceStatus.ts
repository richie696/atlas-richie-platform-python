import {
  HEALTH_LEVEL,
  RESOURCE_PRESSURE_PERCENT,
  type HealthLevel,
  type InstanceRecord,
} from "../model/instance";
import type { TranslationKey } from "../../../shared/types/translation";

/** Health protocol values map to finite localized presentation keys. */
export const INSTANCE_STATUS_LABEL_KEY: Readonly<Record<HealthLevel, TranslationKey>> =
  Object.freeze({
    [HEALTH_LEVEL.Healthy]: "applications.status.healthy",
    [HEALTH_LEVEL.Warning]: "applications.status.warning",
    [HEALTH_LEVEL.Critical]: "applications.status.critical",
  });

/** Resolve the localized status message from measurements instead of storing UI text in records. */
export function instanceStatusLabelKey(instance: InstanceRecord): TranslationKey {
  if (instance.cpu > RESOURCE_PRESSURE_PERCENT) return "applications.status.cpuHigh";
  if (instance.memory > RESOURCE_PRESSURE_PERCENT) return "applications.status.memoryHigh";
  return INSTANCE_STATUS_LABEL_KEY[instance.status];
}
