import { isObservationTime } from "../../../shared/model/observation";
import { hasNonBlankWireContent } from "../../../core/api/protocol/wireString";

export interface EnvironmentOption {
  readonly id: string;
  readonly name: string;
}
export interface ApplicationOption {
  readonly id: string;
  readonly environmentId: string;
  readonly name: string;
}
/** Authorized directory facts used by shared observation filters and route validation. */
export interface ObservationCatalog {
  readonly asOfMs: number;
  readonly environments: readonly EnvironmentOption[];
  readonly applications: readonly ApplicationOption[];
}
/**
 * Retain an application only when it belongs to the environment being selected.
 *
 * Returns `null` for the fleet scope or when the current application is absent
 * from the destination environment, preventing stale cross-environment queries.
 */
export function applicationForEnvironment(
  applications: readonly ApplicationOption[],
  environmentId: string,
  currentAppId: string | null,
): string | null {
  if (currentAppId === null) return null;
  return applications.some(
    (application) => application.id === currentAppId && application.environmentId === environmentId,
  )
    ? currentAppId
    : null;
}
const validLabel = (value: string) => hasNonBlankWireContent(value) && value.length <= 200;
export function validObservationCatalog(value: ObservationCatalog): boolean {
  const environments = new Set(value.environments.map((item) => item.id));
  return (
    isObservationTime(value.asOfMs) &&
    value.environments.length <= 1000 &&
    value.applications.length <= 1000 &&
    environments.size === value.environments.length &&
    new Set(value.applications.map((item) => JSON.stringify([item.environmentId, item.id])))
      .size === value.applications.length &&
    value.environments.every((item) => !!item.id.trim() && validLabel(item.name)) &&
    value.applications.every(
      (item) => !!item.id.trim() && environments.has(item.environmentId) && validLabel(item.name),
    )
  );
}
